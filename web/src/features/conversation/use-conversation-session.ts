"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale } from "next-intl";
import * as React from "react";

import { ApiError } from "@/lib/api";
import {
  readSessionState,
  removeSessionState,
  writeSessionState,
} from "@/lib/browser/session-state";
import type { components } from "@/lib/api/generated/schema";
import {
  createConversationPerformanceTracker,
  type ConversationPerformanceTracker,
} from "@/lib/observability/conversation-performance";
import {
  updateLatestTurnSuggestions,
  upsertConversationTurn,
} from "./api/conversation-cache";
import {
  cancelConversationGeneration,
  selectConversationBranch,
  selectConversationResponse,
  streamConversationBranch,
  streamConversationRetry,
  streamConversationStart,
  streamConversationTurn,
  subscribeConversationEvents,
  updateConversationContext,
  type ConversationStreamKind,
  type ConversationStreamEvent,
  type ConversationTurnCreateRequest,
} from "./api/conversations";
import { conversationKeys } from "./api/keys";
import { conversationQueries } from "./api/queries";
import {
  conversationFailureFromError,
  createLiveTurn,
  persistedResponseStatus,
  type LiveTurn,
} from "./conversation-state";
import type { ConversationTurn } from "./components/conversation-view";
import { ConversationLiveStore } from "./conversation-live-store";
import {
  useResearchComposerForm,
  type ReasoningLevel,
  type ResearchContext,
} from "./components/research-composer";

type ConversationTurnsResponse =
  components["schemas"]["ConversationTurnsResponse"];
type ConversationScopeType = components["schemas"]["ConversationScopeType"];
type PendingGeneration = {
  conversationId: string;
  identity: string;
  responseId: string;
  turnId: string;
};
type StreamSession = {
  conversationId: string;
  turnId: string;
  responseId: string;
  controller: AbortController;
  accepted: boolean;
  startNotified: boolean;
  ready: boolean;
  superseded: boolean;
  resolveAccepted?: () => void;
  rejectAccepted?: (error: unknown) => void;
  pendingLiveTurn?: LiveTurn;
  performance?: ConversationPerformanceTracker;
};

type ConversationDraftV1 = {
  context: ResearchContext;
  message: string;
  reasoningLevel: ReasoningLevel;
  version: 1;
};

function isConversationDraft(value: unknown): value is ConversationDraftV1 {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ConversationDraftV1>;
  const context = candidate.context as
    | {
        document_ids?: unknown;
        kind?: unknown;
        project_ids?: unknown;
      }
    | undefined;
  const validStringArray = (items: unknown) =>
    items === undefined ||
    (Array.isArray(items) && items.every((item) => typeof item === "string"));
  const validContext =
    context?.kind === "library" ||
    (context?.kind === "selection" &&
      validStringArray(context.project_ids) &&
      validStringArray(context.document_ids));
  return Boolean(
    candidate.version === 1 &&
    typeof candidate.message === "string" &&
    candidate.message.trim() &&
    (candidate.reasoningLevel === "standard" ||
      candidate.reasoningLevel === "deep") &&
    validContext,
  );
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
  actorId,
  conversationId,
  context: requestedContext,
  getTurnContexts,
  onConversationCreated,
  onSubmissionError,
  onTurnStarted,
  reasoningLevel,
  scopeId,
  scopeType,
  updateExistingContext = false,
  defaultContext = { kind: "library" } satisfies ResearchContext,
  draftScope,
  onDraftRestored,
}: {
  actorId: number;
  conversationId?: string;
  context?: ResearchContext;
  getTurnContexts?: () => ConversationTurnCreateRequest["contexts"];
  onConversationCreated: (conversationId: string) => void;
  onSubmissionError?: () => void;
  onTurnStarted?: () => void;
  reasoningLevel: ReasoningLevel;
  scopeId?: string;
  scopeType: ConversationScopeType;
  updateExistingContext?: boolean;
  defaultContext?: ResearchContext;
  draftScope: string;
  onDraftRestored?: (draft: {
    context: ResearchContext;
    reasoningLevel: ReasoningLevel;
  }) => void;
}) {
  const queryClient = useQueryClient();
  const locale = useLocale() === "zh-CN" ? "zh-CN" : "en";
  const [createdConversationId, setCreatedConversationId] =
    React.useState<string>();
  const [createdConversationAccepted, setCreatedConversationAccepted] =
    React.useState(false);
  const liveStoreRef = React.useRef<ConversationLiveStore | null>(null);
  liveStoreRef.current ??= new ConversationLiveStore();
  const liveStore = liveStoreRef.current;
  const liveTurnConversationId = React.useRef<string | undefined>(undefined);
  const [submissionPendingConversationId, setSubmissionPendingConversationId] =
    React.useState<string | null>();
  const [recoveryPolling, setRecoveryPolling] = React.useState(false);
  const [stopAvailable, setStopAvailable] = React.useState(false);
  const [completionAnnouncementId, setCompletionAnnouncementId] =
    React.useState<string>();
  const streamSession = React.useRef<StreamSession | null>(null);
  const pendingGeneration = React.useRef<PendingGeneration | null>(null);
  const cancellingSession = React.useRef<StreamSession | null>(null);
  const settlingSessions = React.useRef(new Map<string, StreamSession>());
  const completedPerformance = React.useRef(
    new Map<string, ConversationPerformanceTracker>(),
  );
  const detachedResponseOwners = React.useRef(new Map<string, string>());
  const submissionInFlight = React.useRef(false);
  const submissionEpoch = React.useRef(0);
  const restoreComposerFocus = React.useRef(false);
  const composerForm = useResearchComposerForm();
  const scopeIdentity = `${scopeType}:${scopeId ?? ""}`;
  const previousScopeIdentityRef = React.useRef(scopeIdentity);
  const activeConversationId = conversationId ?? createdConversationId;
  const previousActiveConversationIdRef = React.useRef(activeConversationId);
  const conversationPersisted = Boolean(
    conversationId || createdConversationAccepted,
  );

  const conversationQuery = useQuery({
    ...conversationQueries.detail(activeConversationId ?? ""),
    enabled: Boolean(activeConversationId) && conversationPersisted,
  });
  const turnsQuery = useQuery({
    ...conversationQueries.turns(activeConversationId ?? ""),
    enabled: Boolean(activeConversationId) && conversationPersisted,
    refetchInterval: (query) =>
      query.state.data?.items.some((turn) =>
        turn.responses.some((response) => response.status === "running"),
      ) && recoveryPolling
        ? 5_000
        : false,
  });

  const setLiveTurn = React.useCallback(
    (
      next: LiveTurn | null | ((current: LiveTurn | null) => LiveTurn | null),
    ) => {
      if (typeof next === "function") liveStore.update(next);
      else liveStore.reset(next);
    },
    [liveStore],
  );

  const settleSessionInBackground = React.useCallback(
    function settleSessionInBackground(session: StreamSession) {
      if (streamSession.current !== session || !session.ready) return;
      streamSession.current = null;
      settlingSessions.current.set(session.responseId, session);
      submissionInFlight.current = false;
      setSubmissionPendingConversationId(undefined);
      setStopAvailable(false);
      setRecoveryPolling(false);
      setLiveTurn((current) =>
        current?.responseId === session.responseId ? null : current,
      );
    },
    [setLiveTurn],
  );

  function setLiveTurnConversationId(next: string | undefined) {
    liveTurnConversationId.current = next;
  }
  const context =
    requestedContext ?? conversationQuery.data?.paper_context ?? defaultContext;
  const draftKey = `scholens:conversation-draft:v1:${actorId}:${draftScope}:${conversationId ?? "new"}`;
  const draftDefaultsRef = React.useRef({ context, reasoningLevel });
  draftDefaultsRef.current = { context, reasoningLevel };
  const activeDraftRef = React.useRef<{
    draft: ConversationDraftV1;
    key: string;
  }>({
    draft: { context, message: "", reasoningLevel, version: 1 },
    key: draftKey,
  });
  const draftInitializedRef = React.useRef(false);
  const loadedDraftKeyRef = React.useRef<string | undefined>(undefined);
  const restoringDraftRef = React.useRef(false);
  const draftWriteTimerRef = React.useRef<number | undefined>(undefined);
  const onDraftRestoredRef = React.useRef(onDraftRestored);
  onDraftRestoredRef.current = onDraftRestored;
  if (activeDraftRef.current.key === draftKey) {
    activeDraftRef.current.draft = {
      ...activeDraftRef.current.draft,
      context,
      reasoningLevel,
    };
  }

  const flushDraft = React.useCallback(() => {
    if (draftWriteTimerRef.current !== undefined) {
      window.clearTimeout(draftWriteTimerRef.current);
      draftWriteTimerRef.current = undefined;
    }
    const { draft, key } = activeDraftRef.current;
    if (draft.message.trim()) writeSessionState(key, draft);
    else if (!submissionInFlight.current) removeSessionState(key);
  }, []);

  React.useLayoutEffect(() => {
    if (loadedDraftKeyRef.current === draftKey) return;
    if (draftInitializedRef.current) flushDraft();
    const storedValue = readSessionState<unknown>(draftKey);
    const storedDraft = isConversationDraft(storedValue)
      ? storedValue
      : undefined;
    if (storedValue !== undefined && !storedDraft) {
      removeSessionState(draftKey);
    }
    const draft = storedDraft
      ? storedDraft
      : {
          ...draftDefaultsRef.current,
          message: "",
          version: 1 as const,
        };
    activeDraftRef.current = { draft, key: draftKey };
    draftInitializedRef.current = true;
    loadedDraftKeyRef.current = draftKey;
    restoringDraftRef.current = true;
    composerForm.reset({ message: draft.message }, { keepDefaultValues: true });
    restoringDraftRef.current = false;
    if (storedDraft) {
      onDraftRestoredRef.current?.({
        context: storedDraft.context,
        reasoningLevel: storedDraft.reasoningLevel,
      });
    }
  }, [composerForm, draftKey, flushDraft]);

  React.useEffect(() => {
    const subscription = composerForm.watch((value) => {
      if (restoringDraftRef.current) return;
      activeDraftRef.current = {
        draft: {
          context,
          message: value.message ?? "",
          reasoningLevel,
          version: 1,
        },
        key: draftKey,
      };
      if (draftWriteTimerRef.current !== undefined) {
        window.clearTimeout(draftWriteTimerRef.current);
      }
      draftWriteTimerRef.current = window.setTimeout(flushDraft, 250);
    });
    const handlePageHide = () => flushDraft();
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") flushDraft();
    };
    window.addEventListener("pagehide", handlePageHide);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      subscription.unsubscribe();
      window.removeEventListener("pagehide", handlePageHide);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      flushDraft();
    };
  }, [composerForm, context, draftKey, flushDraft, reasoningLevel]);
  const runningTurn = turnsQuery.data?.items.findLast((turn) =>
    turn.responses.some((response) => response.status === "running"),
  );
  const runningResponse = runningTurn?.responses.find(
    (response) => response.status === "running",
  );

  React.useLayoutEffect(() => {
    if (!conversationId) return;
    setCreatedConversationId(undefined);
    setCreatedConversationAccepted(false);
    pendingGeneration.current = null;
    restoreComposerFocus.current = false;
  }, [conversationId]);

  React.useLayoutEffect(() => {
    if (previousActiveConversationIdRef.current === activeConversationId)
      return;
    previousActiveConversationIdRef.current = activeConversationId;
    setCompletionAnnouncementId(undefined);
  }, [activeConversationId]);

  React.useLayoutEffect(() => {
    if (previousScopeIdentityRef.current === scopeIdentity) return;
    previousScopeIdentityRef.current = scopeIdentity;
    submissionEpoch.current += 1;
    setCreatedConversationId(undefined);
    setCreatedConversationAccepted(false);
    setCompletionAnnouncementId(undefined);
    pendingGeneration.current = null;
    restoreComposerFocus.current = false;
    const session = streamSession.current;
    if (session) {
      if (session.ready) {
        settleSessionInBackground(session);
      } else {
        session.performance?.markTerminal();
        session.superseded = true;
        streamSession.current = null;
        session.controller.abort();
        submissionInFlight.current = false;
        setSubmissionPendingConversationId(undefined);
        setStopAvailable(false);
      }
    }
    setRecoveryPolling(false);
    setLiveTurn(null);
    setLiveTurnConversationId(undefined);
  }, [scopeIdentity, setLiveTurn, settleSessionInBackground]);

  React.useEffect(
    () => () => {
      submissionEpoch.current += 1;
      const sessions = new Set(settlingSessions.current.values());
      if (streamSession.current) sessions.add(streamSession.current);
      if (cancellingSession.current) sessions.add(cancellingSession.current);
      streamSession.current = null;
      settlingSessions.current.clear();
      cancellingSession.current = null;
      pendingGeneration.current = null;
      submissionInFlight.current = false;
      restoreComposerFocus.current = false;
      liveTurnConversationId.current = undefined;
      sessions.forEach((session) => {
        session.performance?.markTerminal();
        session.superseded = true;
        session.controller.abort();
      });
      completedPerformance.current.clear();
      detachedResponseOwners.current.clear();
      liveStore.discardPending();
    },
    [liveStore],
  );

  function supersedeReadyStream() {
    const session = streamSession.current;
    if (!session?.ready) return;
    settleSessionInBackground(session);
  }

  function ownsSession(session: StreamSession) {
    return (
      streamSession.current === session ||
      settlingSessions.current.get(session.responseId) === session
    );
  }

  function forgetSession(session: StreamSession) {
    if (streamSession.current === session) streamSession.current = null;
    if (settlingSessions.current.get(session.responseId) === session) {
      settlingSessions.current.delete(session.responseId);
    }
    detachedResponseOwners.current.delete(session.responseId);
  }

  function releaseSubmission(session: StreamSession) {
    if (streamSession.current !== session) return;
    submissionInFlight.current = false;
    setSubmissionPendingConversationId(undefined);
    setStopAvailable(false);
  }

  const detachForeignStream = React.useCallback(
    function detachForeignStream(nextConversationId: string | undefined) {
      const session = streamSession.current;
      if (session && session.conversationId !== nextConversationId) {
        detachedResponseOwners.current.set(
          session.responseId,
          session.conversationId,
        );
        if (detachedResponseOwners.current.size > 16) {
          const oldestResponseId = detachedResponseOwners.current
            .keys()
            .next().value;
          if (oldestResponseId) {
            detachedResponseOwners.current.delete(oldestResponseId);
          }
        }
        if (session.ready) {
          settleSessionInBackground(session);
        } else {
          session.performance?.markTerminal();
          session.superseded = true;
          streamSession.current = null;
          session.controller.abort();
          submissionInFlight.current = false;
          setStopAvailable(false);
          setRecoveryPolling(false);
        }
      }
      if (liveTurnConversationId.current !== nextConversationId) {
        submissionEpoch.current += 1;
        submissionInFlight.current = false;
        setLiveTurn(null);
        setLiveTurnConversationId(nextConversationId);
      }
      if (
        submissionPendingConversationId !== undefined &&
        submissionPendingConversationId !== (nextConversationId ?? null)
      ) {
        setSubmissionPendingConversationId(undefined);
      }
    },
    [setLiveTurn, settleSessionInBackground, submissionPendingConversationId],
  );

  React.useLayoutEffect(() => {
    detachForeignStream(activeConversationId);
  }, [activeConversationId, detachForeignStream]);

  const applyPersistedStreamEvent = React.useEffectEvent(
    (session: StreamSession, event: ConversationStreamEvent) => {
      applyStreamEvent(session, event);
    },
  );

  React.useEffect(() => {
    const session = streamSession.current;
    if (!session?.accepted || session.ready || !recoveryPolling) return;
    const status = persistedResponseStatus(
      turnsQuery.data?.items,
      session.turnId,
      session.responseId,
    );
    if (!status || status === "running") return;

    if (status === "completed") {
      const persistedTurn = turnsQuery.data?.items.find(
        (turn) =>
          turn.id === session.turnId &&
          turn.responses.some((response) => response.id === session.responseId),
      );
      if (persistedTurn) {
        applyPersistedStreamEvent(session, {
          type: "response_ready",
          turn: persistedTurn,
        });
      }
      return;
    }

    session.performance?.markTerminal();
    session.superseded = true;
    streamSession.current = null;
    session.controller.abort();
    submissionInFlight.current = false;
    setSubmissionPendingConversationId(undefined);
    setStopAvailable(false);
    setRecoveryPolling(false);
    setLiveTurn((current) =>
      current?.responseId === session.responseId ? null : current,
    );
  }, [recoveryPolling, setLiveTurn, turnsQuery.data?.items]);

  function updateConnectionState(
    session: StreamSession,
    state: "connected" | "offline" | "reconnecting",
  ) {
    if (streamSession.current !== session || session.superseded) return;
    setRecoveryPolling(state !== "connected");
    setLiveTurn((current) =>
      current?.responseId === session.responseId
        ? {
            ...current,
            connectionState: state,
            stopFailure: false,
          }
        : current,
    );
  }

  function reserveGeneration(
    identity: string,
    conversationId?: string,
    turnId?: string,
  ) {
    const retry =
      pendingGeneration.current?.identity === identity
        ? pendingGeneration.current
        : null;
    const reserved: PendingGeneration = {
      conversationId:
        conversationId ?? retry?.conversationId ?? crypto.randomUUID(),
      identity,
      responseId: retry?.responseId ?? crypto.randomUUID(),
      turnId: turnId ?? retry?.turnId ?? crypto.randomUUID(),
    };
    pendingGeneration.current = reserved;
    return reserved;
  }

  function clearPendingGeneration(
    session: Pick<StreamSession, "conversationId" | "turnId" | "responseId">,
  ) {
    const pending = pendingGeneration.current;
    if (
      pending?.conversationId === session.conversationId &&
      pending.turnId === session.turnId &&
      pending.responseId === session.responseId
    ) {
      pendingGeneration.current = null;
    }
  }

  function markStreamAccepted(
    session: StreamSession,
    streamKind: ConversationStreamKind,
  ) {
    if (
      streamSession.current !== session ||
      session.superseded ||
      session.accepted
    ) {
      return false;
    }
    session.accepted = true;
    clearPendingGeneration(session);
    setStopAvailable(true);
    session.performance?.markAccepted(streamKind);
    session.resolveAccepted?.();
    session.resolveAccepted = undefined;
    session.rejectAccepted = undefined;
    const pendingLiveTurn = session.pendingLiveTurn;
    session.pendingLiveTurn = undefined;
    setLiveTurn((current) => {
      if (pendingLiveTurn) {
        return {
          ...pendingLiveTurn,
          connectionState: "connected",
          phase: "queued",
        };
      }
      return current?.responseId === session.responseId
        ? { ...current, connectionState: "connected", phase: "queued" }
        : current;
    });
    return true;
  }

  function applyStreamEvent(
    session: StreamSession,
    event: ConversationStreamEvent,
  ) {
    if (!ownsSession(session) || session.superseded) return;
    const foreground = streamSession.current === session;
    session.performance?.markEvent();
    if (
      event.type === "assistant_item_delta" ||
      event.type === "assistant_candidate_delta"
    ) {
      if (event.response_id !== session.responseId) return;
      if (foreground) liveStore.dispatch(event);
      return;
    }
    if (event.type === "start") {
      if (
        event.turn_id !== session.turnId ||
        event.response_id !== session.responseId
      ) {
        return;
      }
      if (!session.startNotified) {
        session.startNotified = true;
        onTurnStarted?.();
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
      session.performance?.markReady();
      queryClient.setQueryData<ConversationTurnsResponse>(
        conversationKeys.turns(session.conversationId),
        (current) => upsertConversationTurn(current, event.turn),
      );
      if (foreground) releaseSubmission(session);
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

    if (foreground) liveStore.dispatch(event);

    if (event.type === "error" || event.type === "cancelled") {
      session.performance?.markTerminal();
      if (foreground) releaseSubmission(session);
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.turns(session.conversationId),
      });
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.detail(session.conversationId),
      });
      forgetSession(session);
      if (foreground) setRecoveryPolling(false);
    }
    if (event.type === "complete") {
      if (foreground) setCompletionAnnouncementId(session.responseId);
      session.performance?.markReady();
      session.performance?.markTerminal();
      if (session.performance) {
        completedPerformance.current.set(
          session.responseId,
          session.performance,
        );
        if (completedPerformance.current.size > 8) {
          const oldestResponseId = completedPerformance.current
            .keys()
            .next().value;
          if (oldestResponseId) {
            completedPerformance.current.delete(oldestResponseId);
          }
        }
      }
      if (foreground) releaseSubmission(session);
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.lists(),
      });
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.turns(session.conversationId),
      });
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.detail(session.conversationId),
      });
      forgetSession(session);
      if (foreground) {
        setRecoveryPolling(false);
        setLiveTurn((current) =>
          current?.turnId === session.turnId &&
          current.responseId === session.responseId
            ? null
            : current,
        );
      }
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
      accepted: true,
      startNotified: true,
      ready: false,
      superseded: false,
    };
    streamSession.current = session;
    submissionInFlight.current = true;
    setStopAvailable(true);
    setSubmissionPendingConversationId(activeConversationId);
    setRecoveryPolling(true);
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
      phase: runningResponse.content ? "answering" : "working",
    });

    void subscribeConversationEvents({
      conversationId: activeConversationId,
      turnId: runningTurn.id,
      responseId: runningResponse.id,
      signal: controller.signal,
      onEvent: (event) => applyStreamEvent(session, event),
      onConnectionState: (state) => {
        updateConnectionState(session, state);
      },
    })
      .catch((error: unknown) => {
        if (
          controller.signal.aborted ||
          streamSession.current !== session ||
          session.superseded
        ) {
          return;
        }
        setRecoveryPolling(false);
        setLiveTurn((current) =>
          current?.responseId === session.responseId
            ? {
                ...current,
                connectionState: "connected",
                failure: conversationFailureFromError(error),
                phase: "error",
              }
            : current,
        );
      })
      .finally(() => {
        if (settlingSessions.current.get(session.responseId) === session) {
          settlingSessions.current.delete(session.responseId);
        }
        if (streamSession.current !== session) return;
        streamSession.current = null;
        submissionInFlight.current = false;
        setSubmissionPendingConversationId(undefined);
        setStopAvailable(false);
        setRecoveryPolling(false);
        void queryClient.invalidateQueries({
          queryKey: conversationKeys.turns(activeConversationId),
        });
      });
  });

  React.useEffect(() => {
    recoverRunningGeneration();
  }, [
    activeConversationId,
    runningResponse?.id,
    runningTurn?.id,
    // The subscription owns recovery for this immutable response identity.
  ]);

  async function sendMessage(message: string) {
    detachForeignStream(activeConversationId);
    if (submissionInFlight.current) return;
    const submissionIdentity = ++submissionEpoch.current;
    const creatingConversation = !activeConversationId;
    const turnContexts = getTurnContexts?.();
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const generationIdentity = JSON.stringify({
      operation: creatingConversation ? "start" : "turn",
      conversationId: activeConversationId ?? null,
      context: creatingConversation || updateExistingContext ? context : null,
      locale,
      message,
      reasoningLevel,
      scopeId,
      scopeType,
      timeZone,
      turnContexts,
    });
    const reservedGeneration = reserveGeneration(
      generationIdentity,
      activeConversationId,
    );
    const {
      conversationId: nextConversationId,
      turnId,
      responseId,
    } = reservedGeneration;
    supersedeReadyStream();
    liveStore.flush();
    const currentLiveTurn = liveStore.getSnapshot();
    const previousLiveTurn =
      currentLiveTurn?.phase === "ready" ? null : currentLiveTurn;
    submissionInFlight.current = true;
    setCompletionAnnouncementId(undefined);
    setStopAvailable(false);
    setSubmissionPendingConversationId(nextConversationId);
    setLiveTurnConversationId(nextConversationId);
    if (creatingConversation) {
      previousActiveConversationIdRef.current = nextConversationId;
      setCreatedConversationAccepted(false);
      setCreatedConversationId(nextConversationId);
    }
    let session: StreamSession | null = null;
    const submittedDraftKey = draftKey;
    const performance = createConversationPerformanceTracker();
    setLiveTurn(
      createLiveTurn(
        turnId,
        responseId,
        message,
        "initial",
        (turnsQuery.data?.items.at(-1)?.depth ?? 0) + 1,
      ),
    );
    window.requestAnimationFrame(() => performance.markFeedback());
    activeDraftRef.current = {
      ...activeDraftRef.current,
      draft: { ...activeDraftRef.current.draft, message: "" },
    };
    composerForm.reset();
    try {
      if (
        !creatingConversation &&
        updateExistingContext &&
        conversationQuery.data &&
        !sameContext(context, conversationQuery.data.paper_context)
      ) {
        await updateConversationContext(nextConversationId, context);
        if (submissionEpoch.current !== submissionIdentity) return;
      }

      const controller = new AbortController();
      session = {
        conversationId: nextConversationId,
        turnId,
        responseId,
        controller,
        accepted: false,
        startNotified: false,
        ready: false,
        superseded: false,
        performance,
      };
      streamSession.current = session;
      setLiveTurnConversationId(nextConversationId);
      const turnRequest: ConversationTurnCreateRequest = {
        contexts: turnContexts,
        turn_id: turnId,
        response_id: responseId,
        user_query: message,
        locale,
        time_zone: timeZone,
        reasoning_level: reasoningLevel,
      };
      const onAccepted = (streamKind: ConversationStreamKind) => {
        if (!session || !markStreamAccepted(session, streamKind)) return;
        removeSessionState(submittedDraftKey);
        if (
          creatingConversation &&
          submissionEpoch.current === submissionIdentity
        ) {
          setCreatedConversationAccepted(true);
          void queryClient.invalidateQueries({
            queryKey: conversationKeys.lists(),
          });
          onConversationCreated(nextConversationId);
        }
      };
      const onEvent = (event: ConversationStreamEvent) => {
        if (session) applyStreamEvent(session, event);
      };
      const onConnectionState = (
        state: "connected" | "offline" | "reconnecting",
      ) => {
        if (session) updateConnectionState(session, state);
      };
      if (creatingConversation) {
        await streamConversationStart({
          conversationId: nextConversationId,
          request: {
            conversation: {
              scope_type: scopeType,
              scope_id: scopeId,
              paper_context: context,
            },
            turn: turnRequest,
          },
          signal: controller.signal,
          onEvent,
          onAccepted,
          onConnectionState,
        });
      } else {
        await streamConversationTurn({
          conversationId: nextConversationId,
          request: turnRequest,
          signal: controller.signal,
          onEvent,
          onAccepted,
          onConnectionState,
        });
      }
    } catch (error) {
      if (submissionEpoch.current !== submissionIdentity) return;
      liveStore.flush();
      if (error instanceof DOMException && error.name === "AbortError") {
        if (session && !session.superseded && !session.ready) {
          const responseId = session.responseId;
          setLiveTurn((current) =>
            current?.responseId === responseId
              ? {
                  ...current,
                  durationMs: Math.max(0, Date.now() - current.startedAtMs),
                  phase: "cancelled",
                }
              : current,
          );
        }
        if (session?.accepted && !session.ready) {
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
        // response_ready already reconciled the canonical response.
      } else if (session?.accepted) {
        session.performance?.markTerminal();
        const responseId = session.responseId;
        setLiveTurn((current) =>
          current?.responseId === responseId
            ? {
                ...current,
                failure: conversationFailureFromError(error),
                phase: "error",
              }
            : current,
        );
      } else {
        setLiveTurn(previousLiveTurn);
        composerForm.setValue("message", message, {
          shouldDirty: true,
          shouldValidate: true,
        });
        restoreComposerFocus.current = true;
        onSubmissionError?.();
        if (creatingConversation) {
          if (error instanceof ApiError && error.status === 409) {
            clearPendingGeneration(session ?? reservedGeneration);
          }
          setCreatedConversationId(undefined);
          setCreatedConversationAccepted(false);
        }
      }
    } finally {
      liveStore.flush();
      if (
        session &&
        settlingSessions.current.get(session.responseId) === session
      ) {
        settlingSessions.current.delete(session.responseId);
      }
      if (
        submissionEpoch.current === submissionIdentity &&
        (!session || streamSession.current === session)
      ) {
        if (streamSession.current === session) streamSession.current = null;
        submissionInFlight.current = false;
        setSubmissionPendingConversationId(undefined);
        setStopAvailable(false);
        setRecoveryPolling(false);
      }
    }
  }

  function runExistingGeneration({
    generationIdentity,
    reservedTurnId,
    userMessage,
    generationKind,
    depth,
    stream,
  }: {
    generationIdentity: string;
    reservedTurnId?: string;
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
    const reservedGeneration = reserveGeneration(
      generationIdentity,
      sessionConversationId,
      reservedTurnId,
    );
    const { turnId, responseId } = reservedGeneration;
    supersedeReadyStream();
    liveStore.flush();
    const currentLiveTurn = liveStore.getSnapshot();
    const previousLiveTurn =
      currentLiveTurn?.phase === "ready" ? null : currentLiveTurn;
    submissionInFlight.current = true;
    setCompletionAnnouncementId(undefined);
    setStopAvailable(false);
    setSubmissionPendingConversationId(activeConversationId);
    const controller = new AbortController();
    const session: StreamSession = {
      conversationId: sessionConversationId,
      turnId,
      responseId,
      controller,
      accepted: false,
      startNotified: false,
      ready: false,
      superseded: false,
      performance: createConversationPerformanceTracker(),
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
    window.requestAnimationFrame(() => session.performance?.markFeedback());
    if (generationKind === "branch") session.pendingLiveTurn = nextLiveTurn;
    else setLiveTurn(nextLiveTurn);
    async function runStream() {
      try {
        await stream(session);
      } catch (error) {
        liveStore.flush();
        if (session.superseded || !ownsSession(session)) return;
        if (error instanceof DOMException && error.name === "AbortError") {
          if (!session.accepted) {
            session.rejectAccepted?.(error);
            session.resolveAccepted = undefined;
            session.rejectAccepted = undefined;
            if (!session.superseded) setLiveTurn(previousLiveTurn);
          } else if (!session.superseded && !session.ready) {
            setLiveTurn((current) =>
              current?.responseId === session.responseId
                ? {
                    ...current,
                    durationMs: Math.max(0, Date.now() - current.startedAtMs),
                    phase: "cancelled",
                  }
                : current,
            );
          }
        } else if (session.ready) {
          // response_ready already reconciled the canonical response.
        } else if (!session.accepted) {
          if (error instanceof ApiError && error.status === 409) {
            clearPendingGeneration(session);
          }
          session.rejectAccepted?.(error);
          session.resolveAccepted = undefined;
          session.rejectAccepted = undefined;
          setLiveTurn(previousLiveTurn);
          if (generationKind === "retry") onSubmissionError?.();
        } else {
          session.performance?.markTerminal();
          setLiveTurn((current) =>
            current?.responseId === session.responseId
              ? {
                  ...current,
                  failure: conversationFailureFromError(error),
                  phase: "error",
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
        liveStore.flush();
        if (settlingSessions.current.get(session.responseId) === session) {
          settlingSessions.current.delete(session.responseId);
        }
        if (!session.accepted) {
          session.rejectAccepted?.(
            new Error("Generation ended before the request was accepted"),
          );
          session.resolveAccepted = undefined;
          session.rejectAccepted = undefined;
          if (!session.superseded) setLiveTurn(previousLiveTurn);
        }
        if (streamSession.current === session) {
          streamSession.current = null;
          submissionInFlight.current = false;
          setSubmissionPendingConversationId(undefined);
          setStopAvailable(false);
          setRecoveryPolling(false);
        }
      }
    }
    void runStream();
    return accepted;
  }

  async function retryResponse(
    turn: Pick<ConversationTurn, "id" | "user_query" | "depth">,
  ) {
    if (!activeConversationId) return;
    try {
      await runExistingGeneration({
        generationIdentity: JSON.stringify({
          operation: "retry",
          conversationId: activeConversationId,
          turnId: turn.id,
        }),
        reservedTurnId: turn.id,
        userMessage: turn.user_query,
        generationKind: "retry",
        depth: turn.depth,
        stream: (session) =>
          streamConversationRetry({
            conversationId: session.conversationId,
            turnId: turn.id,
            request: { response_id: session.responseId },
            signal: session.controller.signal,
            onEvent: (event) => applyStreamEvent(session, event),
            onAccepted: (streamKind) => markStreamAccepted(session, streamKind),
            onConnectionState: (state) => updateConnectionState(session, state),
          }),
      });
    } catch {
      // The existing transcript remains the retry recovery surface.
    }
  }

  async function editMessage(turn: ConversationTurn, message: string) {
    if (!activeConversationId) {
      throw new Error("Conversation is unavailable");
    }
    await runExistingGeneration({
      generationIdentity: JSON.stringify({
        operation: "branch",
        conversationId: activeConversationId,
        sourceTurnId: turn.id,
        message,
      }),
      userMessage: message,
      generationKind: "branch",
      depth: turn.depth,
      stream: (session) =>
        streamConversationBranch({
          conversationId: session.conversationId,
          turnId: turn.id,
          request: {
            turn_id: session.turnId,
            response_id: session.responseId,
            user_query: message,
          },
          signal: session.controller.signal,
          onEvent: (event) => applyStreamEvent(session, event),
          onAccepted: (streamKind) => markStreamAccepted(session, streamKind),
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

  function markContentVisible(responseId: string) {
    const session = streamSession.current;
    if (session?.responseId === responseId && !session.superseded) {
      session.performance?.markContentVisible();
    }
    const completedTracker = completedPerformance.current.get(responseId);
    completedTracker?.markContentVisible();
    completedPerformance.current.delete(responseId);
  }

  function stop() {
    const session = streamSession.current;
    if (!session?.accepted || cancellingSession.current === session) return;
    cancellingSession.current = session;
    restoreComposerFocus.current = true;
    setStopAvailable(false);
    void cancelConversationGeneration({
      conversationId: session.conversationId,
      turnId: session.turnId,
      responseId: session.responseId,
    })
      .then(async (result) => {
        if (session.superseded || streamSession.current !== session) return;
        session.performance?.markTerminal();
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
                  phase: "cancelled",
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
        if (!streamSession.current || streamSession.current === session) {
          setRecoveryPolling(false);
        }
      })
      .catch(() => {
        if (session.superseded || streamSession.current !== session) return;
        if (streamSession.current === session) setStopAvailable(true);
        setLiveTurn((current) =>
          current?.responseId === session.responseId
            ? { ...current, stopFailure: true }
            : current,
        );
      })
      .finally(() => {
        if (cancellingSession.current === session) {
          cancellingSession.current = null;
        }
      });
  }

  const activeLiveTurn = liveStore;
  const activeSubmissionPending =
    submissionPendingConversationId !== undefined &&
    submissionPendingConversationId === (activeConversationId ?? null);
  React.useEffect(() => {
    if (activeSubmissionPending || !restoreComposerFocus.current) return;
    restoreComposerFocus.current = false;
    composerForm.setFocus("message");
  }, [activeSubmissionPending, composerForm]);
  const conversationBusy = activeSubmissionPending;
  const conversationUnavailable = activeConversationId
    ? !activeSubmissionPending &&
      (conversationQuery.isPending ||
        conversationQuery.isError ||
        turnsQuery.isError ||
        conversationQuery.data?.capabilities.send !== true)
    : false;

  return {
    activeConversationId,
    canSend:
      activeSubmissionPending ||
      !activeConversationId ||
      conversationQuery.data?.capabilities.send === true,
    composerForm,
    completionAnnouncementId,
    context,
    conversationBusy,
    conversationQuery,
    conversationUnavailable,
    editMessage,
    liveTurn: activeLiveTurn,
    markContentVisible,
    retryResponse,
    selectBranch,
    selectResponse,
    sendMessage,
    stop,
    stopAvailable,
    submissionPending: activeSubmissionPending,
    turnsQuery,
    useSuggestion,
  };
}
