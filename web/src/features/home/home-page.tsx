"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { useToast } from "@/components/ui/toast";
import { useAuthSession, type Actor } from "@/features/authentication";
import { AppShell } from "./components/app-shell";
import { ConversationView } from "./components/conversation-view";
import {
  conversationFailureFromError,
  createLiveTurn,
  reduceLiveTurn,
  type LiveTurn,
} from "./conversation-state";
import { HomeDashboard } from "./components/home-dashboard";
import { useDesktopLayout } from "./hooks/use-desktop-layout";
import {
  createConversation,
  selectConversationResponse,
  streamConversationRetry,
  streamConversationTurn,
  updateConversationContext,
  type ConversationStreamEvent,
} from "./api/conversations";
import { homeKeys } from "./api/keys";
import { homeQueries } from "./api/queries";
import {
  updateLatestTurnSuggestions,
  upsertConversationTurn,
  type ConversationTurnsResponse,
} from "./api/conversation-cache";
import {
  ResearchComposer,
  useResearchComposerForm,
  type ReasoningLevel,
  type ResearchContext,
} from "./components/research-composer";
import type { ConversationTurn } from "./components/conversation-view";

type StreamSession = {
  conversationId: string;
  turnId: string;
  responseId: string;
  controller: AbortController;
  started: boolean;
  ready: boolean;
  superseded: boolean;
};

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

export function HomeWorkspace({
  actor,
  initialConversationId,
  mobileKeyboardOverride,
}: {
  actor: Actor;
  initialConversationId?: string;
  mobileKeyboardOverride?: { open: boolean; viewportHeight?: number };
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const toast = useToast();
  const t = useTranslations("Home");
  const locale = useLocale() === "zh-CN" ? "zh-CN" : "en";
  const { signOut } = useAuthSession();
  const [pendingConversationId, setPendingConversationId] =
    React.useState<string>();
  const [collapsed, setCollapsed] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const [contextOverrides, setContextOverrides] = React.useState<
    Record<string, ResearchContext>
  >({});
  const [reasoningLevel, setReasoningLevel] =
    React.useState<ReasoningLevel>("standard");
  const [liveTurn, setLiveTurn] = React.useState<LiveTurn | null>(null);
  const [liveTurnConversationId, setLiveTurnConversationId] =
    React.useState<string>();
  const [submissionPending, setSubmissionPending] = React.useState(false);
  const streamSession = React.useRef<StreamSession | null>(null);
  const submissionInFlight = React.useRef(false);
  const composerForm = useResearchComposerForm();
  const isDesktop = useDesktopLayout();

  const activeConversationId = initialConversationId ?? pendingConversationId;

  const conversationsQuery = useQuery(homeQueries.conversations());
  const papersQuery = useQuery(homeQueries.papers());
  const projectsQuery = useQuery(homeQueries.projects());
  const conversationQuery = useQuery({
    ...homeQueries.conversation(activeConversationId ?? ""),
    enabled: Boolean(activeConversationId),
  });
  const turnsQuery = useQuery({
    ...homeQueries.turns(activeConversationId ?? ""),
    enabled: Boolean(activeConversationId),
  });

  React.useEffect(
    () => () => {
      const session = streamSession.current;
      if (session) {
        session.superseded = true;
        session.controller.abort();
      }
    },
    [],
  );

  const conversations = conversationsQuery.data?.items ?? [];
  const papers = papersQuery.data?.items ?? [];
  const projects = projectsQuery.data?.items ?? [];
  const contextKey = activeConversationId ?? "new";
  const context =
    contextOverrides[contextKey] ??
    conversationQuery.data?.paper_context ??
    ({ kind: "library" } satisfies ResearchContext);

  function handleContextChange(nextContext: ResearchContext) {
    setContextOverrides((current) => ({
      ...current,
      [contextKey]: nextContext,
    }));
  }

  function supersedeReadyStream() {
    const session = streamSession.current;
    if (!session?.ready) return;
    session.superseded = true;
    streamSession.current = null;
    session.controller.abort();
  }

  function releaseSubmission(session: StreamSession) {
    if (streamSession.current !== session) return;
    submissionInFlight.current = false;
    setSubmissionPending(false);
  }

  function applyStreamEvent(
    session: StreamSession,
    event: ConversationStreamEvent,
  ) {
    if (streamSession.current !== session || session.superseded) return;
    if (event.type === "start") {
      if (
        event.turn_id !== session.turnId ||
        event.response_id !== session.responseId
      ) {
        return;
      }
      session.started = true;
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
        homeKeys.turns(session.conversationId),
        (current) => upsertConversationTurn(current, event.turn),
      );
      releaseSubmission(session);
      void queryClient.invalidateQueries({
        queryKey: homeKeys.conversations(),
      });
      void queryClient.invalidateQueries({
        queryKey: homeKeys.conversation(session.conversationId),
      });
    } else if (event.type === "suggestions") {
      if (
        event.turn_id !== session.turnId ||
        event.response_id !== session.responseId
      ) {
        return;
      }
      queryClient.setQueryData<ConversationTurnsResponse>(
        homeKeys.turns(session.conversationId),
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

    if (event.type === "error") releaseSubmission(session);
    if (event.type === "complete") {
      void queryClient.invalidateQueries({
        queryKey: homeKeys.conversations(),
      });
      void queryClient.invalidateQueries({
        queryKey: homeKeys.conversation(session.conversationId),
      });
      if (streamSession.current === session) streamSession.current = null;
      setLiveTurn((current) =>
        current?.turnId === session.turnId &&
        current.responseId === session.responseId
          ? null
          : current,
      );
    }
  }

  async function sendMessage(message: string) {
    if (submissionInFlight.current) return;
    submissionInFlight.current = true;
    setSubmissionPending(true);
    supersedeReadyStream();
    const previousLiveTurn = liveTurn;
    const creatingConversation = !activeConversationId;
    let conversationId = activeConversationId;
    let session: StreamSession | null = null;
    try {
      if (!conversationId) {
        const conversation = await createConversation({
          scope_type: "global",
          paper_context: context,
        });
        conversationId = conversation.id;
        setPendingConversationId(conversation.id);
        setContextOverrides((current) => ({
          ...current,
          [conversation.id]: context,
        }));
        queryClient.setQueryData(
          homeKeys.conversation(conversation.id),
          conversation,
        );
        router.replace(`/?conversation=${conversation.id}`, { scroll: false });
      } else if (
        conversationQuery.data &&
        !sameContext(context, conversationQuery.data.paper_context)
      ) {
        await updateConversationContext(conversationId, context);
      }

      const controller = new AbortController();
      const turnId = crypto.randomUUID();
      const responseId = crypto.randomUUID();
      session = {
        conversationId,
        turnId,
        responseId,
        controller,
        started: false,
        ready: false,
        superseded: false,
      };
      streamSession.current = session;
      setLiveTurnConversationId(conversationId);
      setLiveTurn(createLiveTurn(turnId, responseId, message));
      composerForm.reset();
      await streamConversationTurn({
        conversationId,
        request: {
          turn_id: turnId,
          response_id: responseId,
          user_query: message,
          locale,
          time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
          reasoning_level: reasoningLevel,
        },
        signal: controller.signal,
        onEvent: (event) => applyStreamEvent(session!, event),
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        if (session && !session.superseded && !session.ready) {
          const responseId = session.responseId;
          setLiveTurn((current) =>
            current?.responseId === responseId
              ? { ...current, state: "cancelled" }
              : current,
          );
        }
        if (conversationId && session && !session.ready) {
          await Promise.all([
            queryClient.invalidateQueries({
              queryKey: homeKeys.turns(conversationId),
            }),
            queryClient.invalidateQueries({
              queryKey: homeKeys.conversation(conversationId),
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
          toast.notify({
            title: t("conversation.error"),
            description: t("conversation.retryHint"),
          });
        }
      }
    } finally {
      if (!session || streamSession.current === session) {
        if (streamSession.current === session) streamSession.current = null;
        submissionInFlight.current = false;
        setSubmissionPending(false);
      }
      setPendingConversationId(undefined);
    }
  }

  async function retryResponse(turn: ConversationTurn) {
    if (!activeConversationId || submissionInFlight.current) return;
    submissionInFlight.current = true;
    setSubmissionPending(true);
    supersedeReadyStream();
    const previousLiveTurn = liveTurn;
    const responseId = crypto.randomUUID();
    const controller = new AbortController();
    const session: StreamSession = {
      conversationId: activeConversationId,
      turnId: turn.id,
      responseId,
      controller,
      started: false,
      ready: false,
      superseded: false,
    };
    streamSession.current = session;
    setLiveTurnConversationId(activeConversationId);
    setLiveTurn(createLiveTurn(turn.id, responseId, turn.user_query, "retry"));
    try {
      await streamConversationRetry({
        conversationId: activeConversationId,
        turnId: turn.id,
        request: { response_id: responseId },
        signal: controller.signal,
        onEvent: (event) => applyStreamEvent(session, event),
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        if (!session.superseded && !session.ready) {
          setLiveTurn((current) =>
            current?.responseId === session.responseId
              ? { ...current, state: "cancelled" }
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
      await queryClient.invalidateQueries({
        queryKey: homeKeys.turns(activeConversationId),
      });
    } finally {
      if (streamSession.current === session) {
        streamSession.current = null;
        submissionInFlight.current = false;
        setSubmissionPending(false);
      }
    }
  }

  async function selectResponse(turnId: string, responseId: string) {
    if (!activeConversationId || submissionInFlight.current) return;
    await selectConversationResponse({
      conversationId: activeConversationId,
      turnId,
      responseId,
    });
    await queryClient.invalidateQueries({
      queryKey: homeKeys.turns(activeConversationId),
    });
  }

  function useSuggestion(suggestion: string) {
    composerForm.setValue("message", suggestion, {
      shouldDirty: true,
      shouldValidate: true,
    });
    composerForm.setFocus("message");
  }

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await signOut();
      router.replace("/login");
    } finally {
      setSigningOut(false);
    }
  }

  const conversationBusy = submissionPending || liveTurn?.state === "streaming";
  const conversationUnavailable =
    conversationQuery.isPending ||
    conversationQuery.isError ||
    turnsQuery.isError ||
    conversationQuery.data?.capabilities.send !== true;
  const mobileComposer = !isDesktop ? (
    <ResearchComposer
      busy={activeConversationId ? conversationBusy : undefined}
      compact={Boolean(activeConversationId)}
      context={context}
      form={composerForm}
      onContextChange={handleContextChange}
      onReasoningLevelChange={setReasoningLevel}
      onStop={
        activeConversationId
          ? () => streamSession.current?.controller.abort()
          : undefined
      }
      onSubmit={sendMessage}
      papers={papers}
      projects={projects}
      reasoningLevel={reasoningLevel}
      unavailable={activeConversationId ? conversationUnavailable : undefined}
    />
  ) : undefined;

  return (
    <AppShell
      activeConversationId={activeConversationId}
      actor={actor}
      collapsed={collapsed}
      conversations={conversations}
      onCollapsedChange={setCollapsed}
      onReasoningLevelChange={setReasoningLevel}
      onSignOut={handleSignOut}
      reasoningLevel={reasoningLevel}
      signingOut={signingOut}
      mobileComposer={mobileComposer}
      mobileKeyboardOverride={mobileKeyboardOverride}
    >
      {activeConversationId ? (
        <ConversationView
          canSend={conversationQuery.data?.capabilities.send === true}
          composerForm={composerForm}
          context={context}
          error={conversationQuery.isError || turnsQuery.isError}
          liveTurn={
            liveTurnConversationId === activeConversationId ? liveTurn : null
          }
          loading={conversationQuery.isPending || turnsQuery.isPending}
          submissionPending={submissionPending}
          turns={turnsQuery.data?.items ?? []}
          onContextChange={handleContextChange}
          onReasoningLevelChange={setReasoningLevel}
          onRetry={() => {
            void conversationQuery.refetch();
            void turnsQuery.refetch();
          }}
          onRetryResponse={(turn) => void retryResponse(turn)}
          onSelectResponse={(turnId, responseId) =>
            void selectResponse(turnId, responseId)
          }
          onStop={() => streamSession.current?.controller.abort()}
          onSubmit={sendMessage}
          onUseSuggestion={useSuggestion}
          papers={papers}
          projects={projects}
          reasoningLevel={reasoningLevel}
          readOnlyReason={conversationQuery.data?.read_only_reason}
          showComposer={isDesktop}
        />
      ) : (
        <HomeDashboard
          composerForm={composerForm}
          context={context}
          onContextChange={handleContextChange}
          onReasoningLevelChange={setReasoningLevel}
          onRetryPapers={() => void papersQuery.refetch()}
          onRetryProjects={() => void projectsQuery.refetch()}
          onSubmit={sendMessage}
          papers={papers}
          papersError={papersQuery.isError}
          papersLoading={papersQuery.isPending}
          projects={projects}
          projectsError={projectsQuery.isError}
          projectsLoading={projectsQuery.isPending}
          reasoningLevel={reasoningLevel}
          showComposer={isDesktop}
        />
      )}
    </AppShell>
  );
}

export function HomePage({ conversationId }: { conversationId?: string }) {
  const router = useRouter();
  const t = useTranslations("Home.session");
  const session = useAuthSession();

  React.useEffect(() => {
    if (session.status === "anonymous") {
      const returnTo = conversationId
        ? `/?conversation=${encodeURIComponent(conversationId)}`
        : "/";
      router.replace(`/login?returnTo=${encodeURIComponent(returnTo)}`);
    }
  }, [conversationId, router, session.status]);

  if (session.status === "bootstrapping" || session.status === "anonymous") {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <div className="w-full max-w-sm">
          <LoadingState label={t("checking")} />
        </div>
      </main>
    );
  }
  if (session.status === "unavailable") {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <AsyncFeedback
          action={{ label: t("retry"), onClick: session.retryBootstrap }}
          description={t("unavailableDescription")}
          state="offline"
          title={t("unavailableTitle")}
        />
      </main>
    );
  }
  if (!session.actor) return null;
  return (
    <HomeWorkspace
      actor={session.actor}
      initialConversationId={conversationId}
    />
  );
}
