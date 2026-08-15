"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { useToast } from "@/components/ui/toast";
import { useAuthSession, type Actor } from "@/features/authentication";
import {
  ConversationView,
  conversationQueries,
  ReasoningMenu,
  ResearchComposer,
  useConversationSession,
  type ReasoningLevel,
  type ResearchContext,
} from "@/features/conversation";
import {
  WorkspaceNewChatAction,
  WorkspaceShell,
} from "@/features/workspace-shell";
import { HomeDashboard } from "./components/home-dashboard";
import { useDesktopLayout } from "./hooks/use-desktop-layout";
import { useMobileKeyboard } from "./hooks/use-mobile-keyboard";
import { homeQueries } from "./api/queries";

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
  const toast = useToast();
  const t = useTranslations("Home");
  const { signOut } = useAuthSession();
  const [collapsed, setCollapsed] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const [contextOverrides, setContextOverrides] = React.useState<
    Record<string, ResearchContext>
  >({});
  const [reasoningLevel, setReasoningLevel] =
    React.useState<ReasoningLevel>("standard");
  const isDesktop = useDesktopLayout();
  const mobileDockRef = React.useRef<HTMLDivElement>(null);
  const measuredMobileKeyboard = useMobileKeyboard(mobileDockRef, !isDesktop);
  const mobileViewport = mobileKeyboardOverride ?? measuredMobileKeyboard;

  const conversationsQuery = useQuery(conversationQueries.list());
  const papersQuery = useQuery(homeQueries.papers());
  const projectsQuery = useQuery(homeQueries.projects());
  const conversations = conversationsQuery.data?.items ?? [];
  const papers = (papersQuery.data?.items ?? []).flatMap((entry) =>
    entry.entry_type === "paper" ? [entry] : [],
  );
  const projects = projectsQuery.data?.items ?? [];
  const requestedContext = contextOverrides[initialConversationId ?? "new"];
  const conversation = useConversationSession({
    conversationId: initialConversationId,
    context: requestedContext,
    onConversationCreated: (conversationId) => {
      setContextOverrides((current) => ({
        ...current,
        [conversationId]:
          requestedContext ?? ({ kind: "library" } satisfies ResearchContext),
      }));
      router.replace(`/?conversation=${conversationId}`, { scroll: false });
    },
    onCreateError: () =>
      toast.notify({
        title: t("conversation.error"),
        description: t("conversation.retryHint"),
      }),
    reasoningLevel,
    scopeType: "global",
    updateExistingContext: true,
  });
  const contextKey = conversation.activeConversationId ?? "new";
  const context = conversation.context;

  function handleContextChange(nextContext: ResearchContext) {
    setContextOverrides((current) => ({
      ...current,
      [contextKey]: nextContext,
    }));
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

  const mobileComposer = !isDesktop ? (
    <ResearchComposer
      busy={
        conversation.activeConversationId
          ? conversation.conversationBusy
          : undefined
      }
      context={context}
      form={conversation.composerForm}
      onContextChange={handleContextChange}
      onReasoningLevelChange={setReasoningLevel}
      onStop={conversation.activeConversationId ? conversation.stop : undefined}
      onSubmit={conversation.sendMessage}
      papers={papers}
      projects={projects}
      reasoningLevel={reasoningLevel}
      intent={conversation.activeConversationId ? "follow-up" : "new"}
      surface="workspace"
      unavailable={
        conversation.activeConversationId
          ? conversation.conversationUnavailable
          : undefined
      }
    />
  ) : undefined;

  return (
    <WorkspaceShell
      activeConversationId={conversation.activeConversationId}
      activeDestination="ask"
      actor={actor}
      collapsed={collapsed}
      conversations={conversations}
      onCollapsedChange={setCollapsed}
      onSignOut={handleSignOut}
      signingOut={signingOut}
      mobileBottomContent={mobileComposer}
      mobileBottomRef={mobileDockRef}
      mobileHeaderCenter={
        <ReasoningMenu
          onChange={setReasoningLevel}
          value={reasoningLevel}
          variant="mobileHeader"
        />
      }
      mobileHeaderTrailing={<WorkspaceNewChatAction />}
      mobileViewport={mobileViewport}
    >
      {conversation.activeConversationId ? (
        <ConversationView
          layout="workspace"
          canSend={conversation.canSend}
          composerForm={conversation.composerForm}
          context={context}
          error={
            conversation.conversationQuery.isError ||
            conversation.turnsQuery.isError
          }
          liveTurn={conversation.liveTurn}
          loading={
            conversation.conversationQuery.isPending ||
            conversation.turnsQuery.isPending
          }
          submissionPending={conversation.submissionPending}
          turns={conversation.turnsQuery.data?.items ?? []}
          onContextChange={handleContextChange}
          onReasoningLevelChange={setReasoningLevel}
          onRetry={() => {
            void conversation.conversationQuery.refetch();
            void conversation.turnsQuery.refetch();
          }}
          onRetryResponse={(turn) => void conversation.retryResponse(turn)}
          onEditMessage={(turn, message) =>
            conversation.editMessage(turn, message)
          }
          onSelectBranch={(turnId) => void conversation.selectBranch(turnId)}
          onSelectResponse={(turnId, responseId) =>
            void conversation.selectResponse(turnId, responseId)
          }
          onStop={conversation.stop}
          onSubmit={conversation.sendMessage}
          onUseSuggestion={conversation.useSuggestion}
          papers={papers}
          projects={projects}
          reasoningLevel={reasoningLevel}
          readOnlyReason={conversation.conversationQuery.data?.read_only_reason}
          showComposer={isDesktop}
        />
      ) : (
        <HomeDashboard
          composerForm={conversation.composerForm}
          context={context}
          onContextChange={handleContextChange}
          onReasoningLevelChange={setReasoningLevel}
          onRetryPapers={() => void papersQuery.refetch()}
          onRetryProjects={() => void projectsQuery.refetch()}
          onSubmit={conversation.sendMessage}
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
    </WorkspaceShell>
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
