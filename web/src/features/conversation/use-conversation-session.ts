"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale } from "next-intl";
import * as React from "react";

import type { components } from "@/lib/api/generated/schema";
import {
  updateLatestTurnSuggestions,
  upsertConversationTurn,
} from "./api/conversation-cache";
import {
  cancelConversationGeneration,
  createConversation,
  selectConversationBranch,
  selectConversationResponse,
  streamConversationBranch,
  streamConversationRetry,
  streamConversationTurn,
  subscribeConversationEvents,
  updateConversationContext,
  type ConversationStreamEvent,
  type ConversationTurnCreateRequest,
} from "./api/conversations";
import { conversationKeys } from "./api/keys";
import { conversationQueries } from "./api/queries";
import {
  conversationFailureFromError,
  createLiveTurn,
  persistedResponseStatus,
  reduceLiveTurn,
  reduceLiveTurnEvents,
  type LiveTurn,
} from "./conversation-state";
import type { ConversationTurn } from "./components/conversation-view";
import {
  ConversationDeltaBuffer,
  type ConversationDeltaEvent,
} from "./conversation-delta-buffer";
import {
  useResearchComposerForm,
  type ReasoningLevel,
  type ResearchContext,
} from "./components/research-composer";

type ConversationTurnsResponse =
  components["schemas"]["ConversationTurnsResponse"];
type ConversationScopeType = components["schemas"]["ConversationScopeType"];
type StreamSession = {
  conversationId: string;
  turnId: string;
  responseId: string;
  controller: AbortController;
  started: boolean;
  startNotified: boolean;
  ready: boolean;
  superseded: boolean;
  resolveAccepted?: () => void;
  rejectAccepted?: (error: unknown) => void;
  pendingLiveTurn?: LiveTurn;
  deltaBuffer?: ConversationDeltaBuffer;
  durable: boolean;
};

function discardStreamDeltas(session: StreamSession) {
  session.deltaBuffer?.discard();
  session.deltaBuffer = undefined;
}

function sameContext(left: ResearchContext, right: ResearchContext) {
  if (left.kind !== right.kind) return false;
  if (left.kind === "library" || right.kind === "library") return true;
  return (
    [...(left.project_ids ?? [])].sort().join(",") ===
      [...(right.project_ids ?? [])].sort().join(",") &&
    [...(left.document_ids ?? [])].sort().join(",") ===
      [...(right.document_ids ?? [])].sort().join(",")
  );
}

export function useConversationSession({
  conversationId,
  context: requestedContext,
  getTurnContexts,
  onConversationCreated,
  onCreateError,
  onTurnStarted,
  reasoningLevel,
  scopeId,
  scopeType,
  updateExistingContext = false,
  defaultContext = { kind: "library" } satisfies ResearchContext,
}: {
  conversationId?: string;
  context?: ResearchContext;
  getTurnContexts?: () => ConversationTurnCreateRequest["contexts"];
  onConversationCreated: (conversationId: string) => void;
  onCreateError?: () => void;
  onTurnStarted?: () => void;
  reasoningLevel: ReasoningLevel;
  scopeId?: string;
  scopeType: ConversationScopeType;
  updateExistingContext?: boolean;
  defaultContext?: ResearchContext;
}) {
  const queryClient = useQueryClient();
  const locale = useLocale() === "zh-CN" ? "zh-CN" : "en";
  const [createdConversationId, setCreatedConversationId] =
    React.useState<string>();
  const [liveTurn, setLiveTurn] = React.useState<LiveTurn | null>(null);
  const [liveTurnConversationId, setLiveTurnConversationId] =
    React.useState<string>();
  const [submissionPendingConversationId, setSubmissionPendingConversationId] =
    React.useState<string | null>();
  const streamSession = React.useRef<StreamSession | null>(null);
  const detachedResponseOwners = React.useRef(new Map<string, string>());
  const submissionInFlight = React.useRef(false);
  const composerForm = useResearchComposerForm();
  const scopeIdentity = `${scopeType}:${scopeId ?? ""}`;
  const previousScopeIdentityRef = React.useRef(scopeIdentity);
  const activeConversationId = conversationId ?? createdConversationId;

  const conversationQuery = useQuery({
    ...conversationQueries.detail(activeConversationId ?? ""),
    enabled: Boolean(activeConversationId),
  });
  const turnsQuery = useQuery({
    ...conversationQueries.turns(activeConversationId ?? ""),
    enabled: Boolean(activeConversationId),
    refetchInterval: (query) =>
      query.state.data?.items.some((turn) =>
        turn.responses.some((response) => response.status === "running"),
      )
        ? 2_000
        : false,
  });
  const context =
    requestedContext ?? conversationQuery.data?.paper_context ?? defaultContext;
  const runningTurn = turnsQuery.data?.items.findLast((turn) =>
    turn.responses.some((response) => response.status === "running"),
  );
  const runningResponse = runningTurn?.responses.find(
    (response) => response.status === "running",
  );

  React.useEffect(() => {
    if (conversationId) setCreatedConversationId(undefined);
  }, [conversationId]);

  React.useEffect(() => {
    if (previousScopeIdentityRef.current === scopeIdentity) return;
    previousScopeIdentityRef.current = scopeIdentity;
    setCreatedConversationId(undefined);
    const session = streamSession.current;
    if (session) {
      session.superseded = true;
      discardStreamDeltas(session);
      streamSession.current = null;
      session.controller.abort();
      submissionInFlight.current = false;
      setSubmissionPendingConversationId(undefined);
    }
  }, [scopeIdentity]);

  React.useEffect(
    () => () => {
      const session = streamSession.current;
      if (session) {
        session.superseded = true;
        discardStreamDeltas(session);
        session.controller.abort();
      }
    },
    [],
  );

  function supersedeReadyStream() {
    const session = streamSession.current;
    if (!session?.ready) return;
    session.superseded = true;
    discardStreamDeltas(session);
    streamSession.current = null;
    session.controller.abort();
    setLiveTurn((current) =>
      current?.responseId === session.responseId ? null : current,
    );
  }

  function releaseSubmission(session: StreamSession) {
    if (streamSession.current !== session) return;
    submissionInFlight.current = false;
    setSubmissionPendingConversationId(undefined);
  }

  const detachForeignStream = React.useCallback(
    function detachForeignStream(nextConversationId: string | undefined) {
      const session = streamSession.current;
      if (session && session.conversationId !== nextConversationId) {
        detachedResponseOwners.current.set(
          session.responseId,
          session.conversationId,
        );
        session.superseded = true;
        discardStreamDeltas(session);
        streamSession.current = null;
        session.controller.abort();
        submissionInFlight.current = false;
      }
      if (liveTurnConversationId !== nextConversationId) {
        setLiveTurn(null);
        setLiveTurnConversationId(undefined);
      }
      if (
        submissionPendingConversationId !== undefined &&
        submissionPendingConversationId !== (nextConversationId ?? null)
      ) {
        setSubmissionPendingConversationId(undefined);
      }
    },
    [liveTurnConversationId, submissionPendingConversationId],
  );

  React.useEffect(() => {
    detachForeignStream(activeConversationId);
  }, [activeConversationId, detachForeignStream]);

  React.useEffect(() => {
    const session = streamSession.current;
    if (!session?.durable) return;
    const status = persistedResponseStatus(
      turnsQuery.data?.items,
      session.turnId,
      session.responseId,
    );
    if (!status || status === "running") return;

    session.superseded = true;
    streamSession.current = null;
    discardStreamDeltas(session);
    session.controller.abort();
    submissionInFlight.current = false;
    setSubmissionPendingConversationId(undefined);
    setLiveTurn((current) =>
      current?.responseId === session.responseId ? null : current,
    );
  }, [turnsQuery.data?.items]);

  function updateConnectionState(
    session: StreamSession,
    state: "connected" | "reconnecting",
  ) {
    if (streamSession.current !== session || session.superseded) return;
    setLiveTurn((current) =>
      current?.responseId === session.responseId
        ? { ...current, connectionState: state }
        : current,
    );
  }

  function flushStreamDeltas(session: StreamSession) {
    session.deltaBuffer?.flush();
  }

  function queueStreamDelta(
    session: StreamSession,
    event: ConversationDeltaEvent,
  ) {
    session.deltaBuffer ??= new ConversationDeltaBuffer((events) => {
      if (streamSession.current !== session || session.superseded) return;
      setLiveTurn((current) => reduceLiveTurnEvents(current, events));
    });
    session.deltaBuffer.push(event);
  }

  function applyStreamEvent(
    session: StreamSession,
    event: ConversationStreamEvent,
  ) {
    if (streamSession.current !== session || session.superseded) return;
    if (
      event.type === "assistant_item_delta" ||
      event.type === "assistant_candidate_delta"
    ) {
      if (event.response_id !== session.responseId) return;
      queueStreamDelta(session, event);
      return;
    }
    flushStreamDeltas(session);
    if (event.type === "start") {
      if (
        event.turn_id !== session.turnId ||
        event.response_id !== session.responseId
      ) {
        return;
      }
      session.started = true;
      session.resolveAccepted?.();
      session.resolveAccepted = undefined;
      session.rejectAccepted = undefined;
      if (!session.startNotified) {
        session.startNotified = true;
        onTurnStarted?.();
      }
      if (session.pendingLiveTurn) {
        setLiveTurn({
          ...session.pendingLiveTurn,
          startedAtMs: Date.now(),
          variantIndex: event.variant_index,
        });
        session.pendingLiveTurn = undefined;
        return;
      }
    } else if (event.type === "response_ready") {
      if (
        event.turn.id !== session.turnId ||
        !event.turn.responses.some(
          (response) => response.id === session.responseId,
        )
      ) {
        return;
      }
      session.ready = true;
      queryClient.setQueryData<ConversationTurnsResponse>(
        conversationKeys.turns(session.conversationId),
        (current) => upsertConversationTurn(current, event.turn),
      );
      releaseSubmission(session);
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.lists(),
      });
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.detail(session.conversationId),
      });
    } else if (event.type === "suggestions") {
      if (
        event.turn_id !== session.turnId ||
        event.response_id !== session.responseId
      ) {
        return;
      }
      queryClient.setQueryData<ConversationTurnsResponse>(
        conversationKeys.turns(session.conversationId),
        (current) =>
          updateLatestTurnSuggestions(
            current,
            event.turn_id,
            event.suggestions,
          ),
      );
    } else if (event.response_id !== session.responseId) {
      return;
    }

    setLiveTurn((current) => reduceLiveTurn(current, event));

    if (event.type === "error" || event.type === "cancelled") {
      releaseSubmission(session);
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.turns(session.conversationId),
      });
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.detail(session.conversationId),
      });
      if (streamSession.current === session) streamSession.current = null;
      discardStreamDeltas(session);
    }
    if (event.type === "complete") {
      releaseSubmission(session);
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.lists(),
      });
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.detail(session.conversationId),
      });
      if (streamSession.current === session) streamSession.current = null;
      discardStreamDeltas(session);
      setLiveTurn((current) =>
        current?.turnId === session.turnId &&
        current.responseId === session.responseId
          ? null
          : current,
      );
    }
  }

  const recoverRunningGeneration = React.useEffectEvent(() => {
    if (
      !activeConversationId ||
      !runningTurn ||
      !runningResponse ||
      streamSession.current
    ) {
      return;
    }
    const detachedOwner = detachedResponseOwners.current.get(
      runningResponse.id,
    );
    if (detachedOwner && detachedOwner !== activeConversationId) return;
    detachedResponseOwners.current.delete(runningResponse.id);
    const controller = new AbortController();
    const session: StreamSession = {
      conversationId: activeConversationId,
      turnId: runningTurn.id,
      responseId: runningResponse.id,
      controller,
      started: true,
      startNotified: true,
      ready: false,
      superseded: false,
      durable: true,
    };
    streamSession.current = session;
    submissionInFlight.current = true;
    setSubmissionPendingConversationId(activeConversationId);
    setLiveTurnConversationId(activeConversationId);
    setLiveTurn({
      ...createLiveTurn(
        runningTurn.id,
        runningResponse.id,
        runningTurn.user_query,
        runningResponse.variant_index > 1 ? "retry" : "initial",
        runningTurn.depth,
      ),
      variantIndex: runningResponse.variant_index,
      content: runningResponse.content ?? "",
      entries: runningResponse.trace?.entries ?? [],
      trace: runningResponse.trace,
      references: runningResponse.references as Record<string, unknown> | null,
      connectionState: "reconnecting",
    });

    void subscribeConversationEvents({
      conversationId: activeConversationId,
      turnId: runningTurn.id,
      responseId: runningResponse.id,
      signal: controller.signal,
      onEvent: (event) => applyStreamEvent(session, event),
      onConnectionState: (state) => updateConnectionState(session, state),
    })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setLiveTurn((current) =>
          current?.responseId === session.responseId
            ? {
                ...current,
                connectionState: "reconnecting",
                failure: conversationFailureFromError(error),
              }
            : current,
        );
      })
      .finally(() => {
        if (streamSession.current !== session) return;
        streamSession.current = null;
        submissionInFlight.current = false;
        setSubmissionPendingConversationId(undefined);
        void queryClient.invalidateQueries({
          queryKey: conversationKeys.turns(activeConversationId),
        });
      });

    return () => {
      if (streamSession.current === session) {
        session.superseded = true;
        streamSession.current = null;
        submissionInFlight.current = false;
        setSubmissionPendingConversationId(undefined);
        setLiveTurn((current) =>
          current?.responseId === session.responseId ? null : current,
        );
      }
      discardStreamDeltas(session);
      controller.abort();
    };
  });

  React.useEffect(() => {
    return recoverRunningGeneration();
  }, [
    activeConversationId,
    runningResponse?.id,
    runningTurn?.id,
    // The subscription owns recovery for this immutable response identity.
  ]);

  async function sendMessage(message: string) {
    detachForeignStream(activeConversationId);
    if (submissionInFlight.current) return;
    submissionInFlight.current = true;
    setSubmissionPendingConversationId(activeConversationId ?? null);
    setLiveTurnConversationId(activeConversationId);
    supersedeReadyStream();
    const previousLiveTurn =
      liveTurn?.state === "ready" || liveTurn?.state === "complete"
        ? null
        : liveTurn;
    const creatingConversation = !activeConversationId;
    let nextConversationId = activeConversationId;
    let session: StreamSession | null = null;
    try {
      if (!nextConversationId) {
        const conversation = await createConversation({
          scope_type: scopeType,
          scope_id: scopeId,
          paper_context: context,
        });
        nextConversationId = conversation.id;
        setSubmissionPendingConversationId(conversation.id);
        setCreatedConversationId(conversation.id);
        queryClient.setQueryData(
          conversationKeys.detail(conversation.id),
          conversation,
        );
        queryClient.setQueryData<ConversationTurnsResponse>(
          conversationKeys.turns(conversation.id),
          { items: [], next_cursor: null, path_revision: 0 },
        );
        void queryClient.invalidateQueries({
          queryKey: conversationKeys.lists(),
        });
        onConversationCreated(conversation.id);
      } else if (
        updateExistingContext &&
        conversationQuery.data &&
        !sameContext(context, conversationQuery.data.paper_context)
      ) {
        await updateConversationContext(nextConversationId, context);
      }

      const controller = new AbortController();
      const turnId = crypto.randomUUID();
      const responseId = crypto.randomUUID();
      session = {
        conversationId: nextConversationId,
        turnId,
        responseId,
        controller,
        started: false,
        startNotified: false,
        ready: false,
        superseded: false,
        durable: false,
      };
      streamSession.current = session;
      setLiveTurnConversationId(nextConversationId);
      setLiveTurn(
        createLiveTurn(
          turnId,
          responseId,
          message,
          "initial",
          (turnsQuery.data?.items.at(-1)?.depth ?? 0) + 1,
        ),
      );
      composerForm.reset();
      await streamConversationTurn({
        conversationId: nextConversationId,
        request: {
          contexts: getTurnContexts?.(),
          turn_id: turnId,
          response_id: responseId,
          user_query: message,
          locale,
          time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
          reasoning_level: reasoningLevel,
        },
        signal: controller.signal,
        onEvent: (event) => applyStreamEvent(session!, event),
        onAccepted: (durable) => {
          session!.durable = durable;
        },
        onConnectionState: (state) => updateConnectionState(session!, state),
      });
    } catch (error) {
      if (session) flushStreamDeltas(session);
      if (error instanceof DOMException && error.name === "AbortError") {
        if (session && !session.superseded && !session.ready) {
          const responseId = session.responseId;
          setLiveTurn((current) =>
            current?.responseId === responseId
              ? {
                  ...current,
                  durationMs: Math.max(0, Date.now() - current.startedAtMs),
                  state: "cancelled",
                }
              : current,
          );
        }
        if (nextConversationId && session && !session.ready) {
          await Promise.all([
            queryClient.invalidateQueries({
              queryKey: conversationKeys.turns(nextConversationId),
            }),
            queryClient.invalidateQueries({
              queryKey: conversationKeys.detail(nextConversationId),
            }),
          ]);
        }
      } else if (session?.ready) {
        const responseId = session.responseId;
        setLiveTurn((current) =>
          current?.responseId === responseId
            ? { ...current, state: "complete" }
            : current,
        );
      } else if (session?.started) {
        const responseId = session.responseId;
        setLiveTurn((current) =>
          current?.responseId === responseId
            ? {
                ...current,
                failure: conversationFailureFromError(error),
                state: "error",
              }
            : current,
        );
      } else {
        setLiveTurn(previousLiveTurn);
        composerForm.setValue("message", message, {
          shouldDirty: true,
          shouldValidate: true,
        });
        if (creatingConversation) {
          setCreatedConversationId(undefined);
          onCreateError?.();
        }
      }
    } finally {
      if (session) discardStreamDeltas(session);
      if (!session || streamSession.current === session) {
        if (streamSession.current === session) streamSession.current = null;
        submissionInFlight.current = false;
        setSubmissionPendingConversationId(undefined);
      }
    }
  }

  function runExistingGeneration({
    turnId,
    responseId,
    userMessage,
    generationKind,
    depth,
    stream,
  }: {
    turnId: string;
    responseId: string;
    userMessage: string;
    generationKind: "retry" | "branch";
    depth: number;
    stream: (session: StreamSession) => Promise<void>;
  }): Promise<void> {
    detachForeignStream(activeConversationId);
    if (!activeConversationId || submissionInFlight.current) {
      return Promise.reject(new Error("Conversation is unavailable or busy"));
    }
    const sessionConversationId = activeConversationId;
    submissionInFlight.current = true;
    setSubmissionPendingConversationId(activeConversationId);
    supersedeReadyStream();
    const previousLiveTurn =
      liveTurn?.state === "ready" || liveTurn?.state === "complete"
        ? null
        : liveTurn;
    const controller = new AbortController();
    const session: StreamSession = {
      conversationId: sessionConversationId,
      turnId,
      responseId,
      controller,
      started: false,
      startNotified: false,
      ready: false,
      superseded: false,
      durable: false,
    };
    const accepted = new Promise<void>((resolve, reject) => {
      session.resolveAccepted = resolve;
      session.rejectAccepted = reject;
    });
    streamSession.current = session;
    setLiveTurnConversationId(sessionConversationId);
    const nextLiveTurn = createLiveTurn(
      turnId,
      responseId,
      userMessage,
      generationKind,
      depth,
    );
    if (generationKind === "branch") session.pendingLiveTurn = nextLiveTurn;
    else setLiveTurn(nextLiveTurn);
    async function runStream() {
      try {
        await stream(session);
      } catch (error) {
        flushStreamDeltas(session);
        if (error instanceof DOMException && error.name === "AbortError") {
          if (!session.started) {
            session.rejectAccepted?.(error);
            session.resolveAccepted = undefined;
            session.rejectAccepted = undefined;
            setLiveTurn(previousLiveTurn);
          } else if (!session.superseded && !session.ready) {
            setLiveTurn((current) =>
              current?.responseId === session.responseId
                ? {
                    ...current,
                    durationMs: Math.max(0, Date.now() - current.startedAtMs),
                    state: "cancelled",
                  }
                : current,
            );
          }
        } else if (session.ready) {
          setLiveTurn((current) =>
            current?.responseId === session.responseId
              ? { ...current, state: "complete" }
              : current,
          );
        } else if (!session.started) {
          session.rejectAccepted?.(error);
          session.resolveAccepted = undefined;
          session.rejectAccepted = undefined;
          setLiveTurn(previousLiveTurn);
        } else {
          setLiveTurn((current) =>
            current?.responseId === session.responseId
              ? {
                  ...current,
                  failure: conversationFailureFromError(error),
                  state: "error",
                }
              : current,
          );
        }
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: conversationKeys.turns(sessionConversationId),
          }),
          queryClient.invalidateQueries({
            queryKey: conversationKeys.detail(sessionConversationId),
          }),
        ]);
      } finally {
        discardStreamDeltas(session);
        if (!session.started) {
          session.rejectAccepted?.(
            new Error("Generation ended before the request was accepted"),
          );
          session.resolveAccepted = undefined;
          session.rejectAccepted = undefined;
          setLiveTurn(previousLiveTurn);
        }
        if (streamSession.current === session) {
          streamSession.current = null;
          submissionInFlight.current = false;
          setSubmissionPendingConversationId(undefined);
        }
      }
    }
    void runStream();
    return accepted;
  }

  async function retryResponse(
    turn: Pick<ConversationTurn, "id" | "user_query" | "depth">,
  ) {
    const responseId = crypto.randomUUID();
    try {
      await runExistingGeneration({
        turnId: turn.id,
        responseId,
        userMessage: turn.user_query,
        generationKind: "retry",
        depth: turn.depth,
        stream: (session) =>
          streamConversationRetry({
            conversationId: session.conversationId,
            turnId: turn.id,
            request: { response_id: responseId },
            signal: session.controller.signal,
            onEvent: (event) => applyStreamEvent(session, event),
            onAccepted: (durable) => {
              session.durable = durable;
            },
            onConnectionState: (state) => updateConnectionState(session, state),
          }),
      });
    } catch {
      // The existing transcript remains the retry recovery surface.
    }
  }

  async function editMessage(turn: ConversationTurn, message: string) {
    const turnId = crypto.randomUUID();
    const responseId = crypto.randomUUID();
    await runExistingGeneration({
      turnId,
      responseId,
      userMessage: message,
      generationKind: "branch",
      depth: turn.depth,
      stream: (session) =>
        streamConversationBranch({
          conversationId: session.conversationId,
          turnId: turn.id,
          request: {
            turn_id: turnId,
            response_id: responseId,
            user_query: message,
          },
          signal: session.controller.signal,
          onEvent: (event) => applyStreamEvent(session, event),
          onAccepted: (durable) => {
            session.durable = durable;
          },
          onConnectionState: (state) => updateConnectionState(session, state),
        }),
    });
  }

  async function selectResponse(turnId: string, responseId: string) {
    if (!activeConversationId || submissionInFlight.current) return;
    supersedeReadyStream();
    await selectConversationResponse({
      conversationId: activeConversationId,
      turnId,
      responseId,
    });
    await queryClient.invalidateQueries({
      queryKey: conversationKeys.turns(activeConversationId),
    });
  }

  async function selectBranch(turnId: string) {
    if (!activeConversationId || submissionInFlight.current) return;
    supersedeReadyStream();
    const selected = await selectConversationBranch({
      conversationId: activeConversationId,
      turnId,
    });
    queryClient.setQueryData<ConversationTurnsResponse>(
      conversationKeys.turns(activeConversationId),
      selected,
    );
    await queryClient.invalidateQueries({
      queryKey: conversationKeys.detail(activeConversationId),
    });
  }

  function useSuggestion(suggestion: string) {
    composerForm.setValue("message", suggestion, {
      shouldDirty: true,
      shouldValidate: true,
    });
    composerForm.setFocus("message");
  }

  function stop() {
    const session = streamSession.current;
    if (!session) return;
    if (!session.durable) {
      session.controller.abort();
      return;
    }
    void cancelConversationGeneration({
      conversationId: session.conversationId,
      turnId: session.turnId,
      responseId: session.responseId,
    })
      .then(async (result) => {
        session.superseded = true;
        session.controller.abort();
        releaseSubmission(session);
        if (streamSession.current === session) streamSession.current = null;
        if (result.status === "cancelled") {
          setLiveTurn((current) =>
            current?.responseId === session.responseId
              ? {
                  ...current,
                  durationMs: Math.max(0, Date.now() - current.startedAtMs),
                  state: "cancelled",
                }
              : current,
          );
        }
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: conversationKeys.turns(session.conversationId),
          }),
          queryClient.invalidateQueries({
            queryKey: conversationKeys.detail(session.conversationId),
          }),
        ]);
        if (result.status !== "cancelled") {
          setLiveTurn((current) =>
            current?.responseId === session.responseId ? null : current,
          );
        }
      })
      .catch(() => {
        setLiveTurn((current) =>
          current?.responseId === session.responseId
            ? { ...current, connectionState: "stop_failed" }
            : current,
        );
      });
  }

  const activeLiveTurn =
    liveTurnConversationId === activeConversationId ? liveTurn : null;
  const activeSubmissionPending =
    submissionPendingConversationId !== undefined &&
    submissionPendingConversationId === (activeConversationId ?? null);
  const conversationBusy =
    activeSubmissionPending || activeLiveTurn?.state === "streaming";
  const conversationUnavailable = activeConversationId
    ? conversationQuery.isPending ||
      conversationQuery.isError ||
      turnsQuery.isError ||
      conversationQuery.data?.capabilities.send !== true
    : false;

  return {
    activeConversationId,
    canSend: activeConversationId
      ? conversationQuery.data?.capabilities.send === true
      : true,
    composerForm,
    context,
    conversationBusy,
    conversationQuery,
    conversationUnavailable,
    editMessage,
    liveTurn: activeLiveTurn,
    retryResponse,
    selectBranch,
    selectResponse,
    sendMessage,
    stop,
    submissionPending: activeSubmissionPending,
    turnsQuery,
    useSuggestion,
  };
}
