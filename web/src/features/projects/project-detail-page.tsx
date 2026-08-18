"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  Button,
  CursorPagination,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  IconButton,
  OverflowMenuButton,
  SearchField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useToast,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  AddIcon,
  AccountIcon,
  AudioIcon,
  BackIcon,
  CitationIcon,
  ClosePanelIcon,
  DataTableIcon,
  DeleteIcon,
  EditIcon,
  OpenPanelIcon,
  QuoteIcon,
} from "@/design-system/icons/semantic-icons";
import {
  AnimatePresence,
  m,
  motionTransitions,
  motionVariants,
} from "@/design-system/motion";
import { useAuthSession, type Actor } from "@/features/authentication";
import {
  conversationKeys,
  conversationQueries,
  ConversationSwitcher,
  ConversationView,
  setConversationPinned,
  useConversationSession,
  type ReasoningLevel,
  type ResearchContext,
} from "@/features/conversation";
import { WorkspaceShell } from "@/features/workspace-shell";
import { ApiError } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import {
  addProjectPapers,
  deleteProject,
  leaveProject,
  projectKeys,
  projectQueries,
  removeProjectPaper,
  updateProject,
} from "./api";
import { AddProjectPapersDialog } from "./components/add-project-papers-dialog";
import { ManageProjectCollaboratorsDialog } from "./components/manage-project-collaborators-dialog";
import { ProjectFormDialog } from "./components/project-form-dialog";
import { useDesktopLayout } from "@/lib/utilities/use-desktop-layout";
import {
  parseProjectDetailSearch,
  serializeProjectDetailSearch,
  type ProjectDetailSearchState,
  type ProjectOutputKind,
  type ProjectOutputSort,
  type ProjectPaperSort,
  type ProjectView,
} from "./project-search";

type Project = components["schemas"]["ProjectResponse"];
type ProjectPaper = components["schemas"]["ProjectPaperSummaryResponse"];
type ProjectOutput = components["schemas"]["LibraryOutputResponse"];

function ProjectSearchField({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const [input, setInput] = React.useState(value);
  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      if (input !== value) onChange(input);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [input, onChange, value]);
  return (
    <SearchField
      aria-label={label}
      className="bg-subtle hover:border-line rounded-full border-transparent"
      onChange={(event) => setInput(event.currentTarget.value)}
      placeholder={label}
      value={input}
    />
  );
}

function ProjectChat({
  conversationId,
  conversations,
  conversationsLoading,
  onClose,
  onConversationChange,
  onConversationPin,
  onConversationPinError,
  project,
}: {
  conversationId?: string;
  conversations: components["schemas"]["ConversationSummaryResponse"][];
  conversationsLoading: boolean;
  onClose?: () => void;
  onConversationChange: (conversationId?: string) => void;
  onConversationPin: (id: string, pinned: boolean) => Promise<void>;
  onConversationPinError: () => void;
  project: Project;
}) {
  const t = useTranslations("Projects.chat");
  const [reasoningLevel, setReasoningLevel] =
    React.useState<ReasoningLevel>("standard");
  const [contextOverrides, setContextOverrides] = React.useState<
    Record<string, ResearchContext>
  >({});
  const defaultContext = React.useMemo<ResearchContext>(
    () => ({
      kind: "selection",
      document_ids: [],
      project_ids: [project.id],
    }),
    [project.id],
  );
  const session = useConversationSession({
    context: contextOverrides[conversationId ?? "new"],
    conversationId,
    defaultContext,
    onConversationCreated: (id) => onConversationChange(id),
    reasoningLevel,
    scopeId: project.id,
    scopeType: "project",
    updateExistingContext: true,
  });
  const contextKey = session.activeConversationId ?? "new";

  function handleContextChange(nextContext: ResearchContext) {
    setContextOverrides((current) => ({
      ...current,
      [contextKey]: nextContext,
    }));
  }
  return (
    <section
      className="bg-canvas flex h-full min-h-0 w-full min-w-0 flex-1 flex-col"
      aria-label={t("title")}
      data-project-chat
    >
      <ConversationSwitcher
        activeId={conversationId}
        conversations={conversations}
        labels={{
          empty: t("empty"),
          loading: t("loading"),
          new: t("new"),
          newDraft: t("newDraft"),
          pin: t("pin"),
          pinned: t("pinned"),
          recent: t("recent"),
          search: t("search"),
          switcher: t("switcher"),
          unpin: t("unpin"),
        }}
        loading={conversationsLoading}
        onChange={onConversationChange}
        onNew={() => onConversationChange(undefined)}
        onPin={onConversationPin}
        onPinError={onConversationPinError}
        trailingAction={
          onClose ? (
            <IconButton label={t("close")} onClick={onClose} variant="ghost">
              <Icon glyph={ClosePanelIcon} size={20} />
            </IconButton>
          ) : undefined
        }
      />
      <div className="min-h-0 flex-1">
        <ConversationView
          canSend={session.canSend}
          composerForm={session.composerForm}
          context={session.context}
          emptyState={{
            description: t("emptyDescription"),
            title: t("emptyTitle"),
          }}
          error={session.turnsQuery.isError}
          layout="side-panel"
          liveTurn={session.liveTurn}
          loading={session.turnsQuery.isPending && Boolean(conversationId)}
          onContextChange={handleContextChange}
          onReasoningLevelChange={setReasoningLevel}
          onRetry={() => void session.turnsQuery.refetch()}
          onRetryResponse={(turn) => void session.retryResponse(turn)}
          onEditMessage={(turn, message) => session.editMessage(turn, message)}
          onSelectBranch={(turnId) => void session.selectBranch(turnId)}
          onSelectResponse={(turnId, responseId) =>
            void session.selectResponse(turnId, responseId)
          }
          onStop={session.stop}
          onSubmit={session.sendMessage}
          onUseSuggestion={session.useSuggestion}
          papers={[]}
          projects={[project]}
          reasoningLevel={reasoningLevel}
          readOnlyReason={session.conversationQuery.data?.read_only_reason}
          submissionPending={session.submissionPending}
          turns={session.turnsQuery.data?.items ?? []}
        />
      </div>
    </section>
  );
}

function ProjectPaperRow({
  canRemove,
  onActionTrigger,
  onRemove,
  paper,
  projectId,
}: {
  canRemove: boolean;
  onActionTrigger: (trigger: HTMLButtonElement) => void;
  onRemove: (paper: ProjectPaper) => void;
  paper: ProjectPaper;
  projectId: string;
}) {
  const t = useTranslations("Projects.detail.papers");
  return (
    <div className="motion-control group/interactive-row hover:bg-hover focus-within:bg-hover active:bg-pressed grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-[var(--radius-lg)] py-2">
      <Link
        className="hover:bg-hover grid min-w-0 gap-2 rounded-[var(--radius-md)] px-2 py-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
        href={`/reader/${paper.document_id}?project=${projectId}` as Route}
      >
        <span className="min-w-0">
          <span className="line-clamp-2 text-sm font-medium sm:line-clamp-1">
            {paper.title || t("untitled")}
          </span>
          <span className="text-secondary mt-1 block truncate text-xs">
            {paper.authors?.join(", ") || t("unknownAuthors")}
          </span>
        </span>
        <span className="text-secondary text-xs">{t("openReader")}</span>
      </Link>
      {canRemove && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <OverflowMenuButton
              label={t("openMenu")}
              onClick={(event) => onActionTrigger(event.currentTarget)}
              visibility="contextual"
            />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem destructive onSelect={() => onRemove(paper)}>
              <Icon glyph={DeleteIcon} size={16} />
              {t("remove")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

type PaperRemovalImpact = {
  commentCount: number;
  confirmationToken: string;
  paper: ProjectPaper;
  threadCount: number;
};

function paperRemovalImpact(
  error: unknown,
  paper: ProjectPaper,
): PaperRemovalImpact | undefined {
  if (!(error instanceof ApiError) || error.code !== "confirmation_required") {
    return undefined;
  }
  const response =
    error.details && typeof error.details === "object"
      ? (error.details as Record<string, unknown>)
      : undefined;
  const details =
    response?.details && typeof response.details === "object"
      ? (response.details as Record<string, unknown>)
      : undefined;
  return {
    commentCount:
      typeof details?.comment_count === "number" ? details.comment_count : 0,
    confirmationToken:
      typeof details?.confirmation_token === "string"
        ? details.confirmation_token
        : "",
    paper,
    threadCount:
      typeof details?.thread_count === "number" ? details.thread_count : 0,
  };
}

const outputIcons = {
  annotation_thread: QuoteIcon,
  citation: CitationIcon,
  audio_overview: AudioIcon,
  data_table: DataTableIcon,
} as const;

function ProjectOutputRow({ output }: { output: ProjectOutput }) {
  const t = useTranslations("Projects.detail.outputs");
  const format = useFormatter();
  const kind = output.item.kind;
  return (
    <div className="motion-control hover:bg-hover flex min-w-0 items-center gap-3 rounded-[var(--radius-lg)] px-3 py-4">
      <div className="bg-subtle grid size-9 shrink-0 place-items-center rounded-[var(--radius-md)]">
        <Icon glyph={outputIcons[kind]} size={20} tone="secondary" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{output.title}</p>
        <p className="text-muted mt-1 text-xs">{t(`kinds.${kind}`)}</p>
      </div>
      <time className="text-muted hidden text-xs sm:block">
        {format.dateTime(new Date(output.item.updated_at), "short")}
      </time>
    </div>
  );
}

function ProjectManageMenu({
  onAddPapers,
  onManageCollaborators,
  onDelete,
  onEdit,
  onLeave,
  project,
}: {
  onAddPapers: () => void;
  onManageCollaborators: () => void;
  onDelete: () => void;
  onEdit: () => void;
  onLeave: () => void;
  project: Project;
}) {
  const t = useTranslations("Projects");
  const hasProjectAction =
    project.capabilities.edit_project ||
    project.capabilities.delete ||
    project.capabilities.leave;
  const hasWorkspaceAction =
    project.capabilities.manage_papers ||
    project.capabilities.manage_collaborators;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <OverflowMenuButton label={t("detail.manage")} visibility="always" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {project.capabilities.manage_papers ? (
          <DropdownMenuItem onSelect={onAddPapers}>
            <Icon glyph={AddIcon} size={16} />
            {t("detail.papers.add")}
          </DropdownMenuItem>
        ) : null}
        {project.capabilities.manage_collaborators ? (
          <DropdownMenuItem onSelect={onManageCollaborators}>
            <Icon glyph={AccountIcon} size={16} />
            {t("collaborators.manage")}
          </DropdownMenuItem>
        ) : null}
        {hasWorkspaceAction && hasProjectAction ? (
          <DropdownMenuSeparator />
        ) : null}
        {project.capabilities.edit_project ? (
          <DropdownMenuItem onSelect={onEdit}>
            <Icon glyph={EditIcon} size={16} />
            {t("actions.edit")}
          </DropdownMenuItem>
        ) : null}
        {(project.capabilities.delete || project.capabilities.leave) &&
        project.capabilities.edit_project ? (
          <DropdownMenuSeparator />
        ) : null}
        {project.capabilities.delete ? (
          <DropdownMenuItem destructive onSelect={onDelete}>
            {t("actions.delete")}
          </DropdownMenuItem>
        ) : null}
        {project.capabilities.leave ? (
          <DropdownMenuItem destructive onSelect={onLeave}>
            {t("actions.leave")}
          </DropdownMenuItem>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function ProjectDetailWorkspace({
  actor,
  projectId,
}: {
  actor: Actor;
  projectId: string;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const t = useTranslations("Projects");
  const desktopLayout = useDesktopLayout();
  const { signOut } = useAuthSession();
  const state = React.useMemo(
    () =>
      parseProjectDetailSearch(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const [collapsed, setCollapsed] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const [editOpen, setEditOpen] = React.useState(false);
  const [addPapersOpen, setAddPapersOpen] = React.useState(false);
  const [collaboratorsOpen, setCollaboratorsOpen] = React.useState(false);
  const [paperRemoval, setPaperRemoval] =
    React.useState<PaperRemovalImpact | null>(null);
  const paperRemovalTriggerRef = React.useRef<HTMLButtonElement | null>(null);
  const mobileChatTriggerRef = React.useRef<HTMLButtonElement | null>(null);
  const [destructive, setDestructive] = React.useState<
    "delete" | "leave" | null
  >(null);
  const projectQuery = useQuery(projectQueries.detail(projectId));
  const conversationsQuery = useQuery(
    conversationQueries.list({ scopeId: projectId, scopeType: "project" }),
  );
  const sidebarConversationsQuery = useQuery(conversationQueries.list());
  const papersQuery = useQuery({
    ...projectQueries.papers(projectId, state),
    enabled: state.view === "papers" || state.view === "overview",
  });
  const outputsQuery = useQuery({
    ...projectQueries.outputs(projectId, state),
    enabled: state.view === "outputs" || state.view === "overview",
  });
  const libraryPapersQuery = useQuery({
    ...projectQueries.libraryPapers(),
    enabled: addPapersOpen,
  });

  const replaceSearch = React.useCallback(
    (patch: Partial<ProjectDetailSearchState>) => {
      const next = serializeProjectDetailSearch({
        ...state,
        ...patch,
      }).toString();
      router.replace(
        (next
          ? `/projects/${projectId}?${next}`
          : `/projects/${projectId}`) as Route,
        { scroll: false },
      );
    },
    [projectId, router, state],
  );
  const updateMutation = useMutation({
    mutationFn: (value: { title: string; description: string | null }) =>
      updateProject(projectId, value),
    onSuccess: async (project) => {
      queryClient.setQueryData(projectKeys.detail(projectId), project);
      await queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
  const addPapersMutation = useMutation({
    mutationFn: (documentIds: string[]) =>
      addProjectPapers(projectId, documentIds),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: projectKeys.detail(projectId),
        }),
        queryClient.invalidateQueries({
          queryKey: [...projectKeys.detail(projectId), "papers"],
        }),
        queryClient.invalidateQueries({ queryKey: projectKeys.lists() }),
      ]);
      replaceSearch({
        paperCursor: undefined,
        paperQuery: "",
        paperSort: "added_desc",
        view: "papers",
      });
    },
  });
  const removePaperMutation = useMutation({
    mutationFn: ({
      confirmationToken,
      documentId,
    }: {
      confirmationToken?: string;
      documentId: string;
    }) => removeProjectPaper(projectId, documentId, confirmationToken),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: projectKeys.detail(projectId),
        }),
        queryClient.invalidateQueries({ queryKey: projectKeys.lists() }),
      ]);
    },
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteProject(projectId),
  });
  const leaveMutation = useMutation({
    mutationFn: () => leaveProject(projectId),
  });

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await signOut();
      router.replace("/login");
    } finally {
      setSigningOut(false);
    }
  }

  async function confirmDestructive() {
    try {
      if (destructive === "delete") await deleteMutation.mutateAsync();
      else await leaveMutation.mutateAsync();
      await queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
      router.replace("/projects");
    } catch {
      toast.notify({ title: t("feedback.actionFailed") });
    }
  }

  async function requestPaperRemoval(paper: ProjectPaper) {
    try {
      await removePaperMutation.mutateAsync({
        documentId: paper.document_id,
      });
      toast.notify({ title: t("detail.papers.removed") });
    } catch (error) {
      const impact = paperRemovalImpact(error, paper);
      if (impact) setPaperRemoval(impact);
      else toast.notify({ title: t("detail.papers.removeFailed") });
    }
  }

  async function confirmPaperRemoval() {
    if (!paperRemoval) return;
    try {
      await removePaperMutation.mutateAsync({
        confirmationToken: paperRemoval.confirmationToken,
        documentId: paperRemoval.paper.document_id,
      });
      setPaperRemoval(null);
      toast.notify({ title: t("detail.papers.removed") });
    } catch {
      toast.notify({ title: t("detail.papers.removeFailed") });
    }
  }

  async function pinConversation(id: string, pinned: boolean) {
    await setConversationPinned(id, pinned);
    await queryClient.invalidateQueries({
      queryKey: conversationKeys.lists(),
    });
  }

  if (projectQuery.isPending) {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <div className="w-full max-w-lg">
          <LoadingState />
        </div>
      </main>
    );
  }
  if (projectQuery.isError || !projectQuery.data) {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <AsyncFeedback
          action={{
            label: t("feedback.retry"),
            onClick: () => void projectQuery.refetch(),
          }}
          description={t("detail.errorDescription")}
          state="error"
          title={t("detail.errorTitle")}
        />
      </main>
    );
  }
  const project = projectQuery.data;
  const memberCount = project.num_collaborators + 1;
  const ownerInitial =
    project.owner.display_name.trim().charAt(0).toUpperCase() || "?";
  const renderChat = (onClose?: () => void) => (
    <ProjectChat
      conversationId={state.conversation}
      conversations={conversationsQuery.data?.items ?? []}
      conversationsLoading={conversationsQuery.isPending}
      onClose={onClose}
      onConversationChange={(conversation) =>
        replaceSearch({ conversation, panel: "chat" })
      }
      onConversationPin={pinConversation}
      onConversationPinError={() =>
        toast.notify({ title: t("feedback.actionFailed") })
      }
      project={project}
    />
  );

  return (
    <WorkspaceShell
      activeConversationId={state.conversation}
      activeDestination="projects"
      actor={actor}
      collapsed={collapsed}
      conversations={sidebarConversationsQuery.data?.items ?? []}
      mobileHeaderCenter={
        <span
          className="block truncate text-base font-semibold"
          data-project-title
        >
          {project.title}
        </span>
      }
      mobileHeaderLeading={
        <Link
          aria-label={t("detail.back")}
          className="hover:bg-hover grid size-11 shrink-0 place-items-center rounded-[var(--radius-md)]"
          href="/projects"
        >
          <Icon glyph={BackIcon} size={20} />
        </Link>
      }
      mobileHeaderTrailing={
        <div className="flex items-center gap-1">
          <ProjectManageMenu
            onAddPapers={() => setAddPapersOpen(true)}
            onDelete={() => setDestructive("delete")}
            onEdit={() => setEditOpen(true)}
            onLeave={() => setDestructive("leave")}
            onManageCollaborators={() => setCollaboratorsOpen(true)}
            project={project}
          />
          <IconButton
            label={
              state.panel === "chat"
                ? t("detail.closeChat")
                : t("detail.openChat")
            }
            onClick={() =>
              replaceSearch({
                panel: state.panel === "chat" ? undefined : "chat",
              })
            }
            ref={mobileChatTriggerRef}
            aria-pressed={state.panel === "chat"}
            variant="ghost"
          >
            <Icon
              glyph={state.panel === "chat" ? ClosePanelIcon : OpenPanelIcon}
              size={20}
            />
          </IconButton>
        </div>
      }
      onCollapsedChange={setCollapsed}
      onSignOut={handleSignOut}
      showMobileBottomNavigation={state.panel !== "chat"}
      signingOut={signingOut}
    >
      <m.div
        className="flex h-full min-h-0"
        layout="size"
        transition={motionTransitions.layout}
      >
        <m.div
          className="min-w-0 flex-1 overflow-y-auto"
          layout="size"
          transition={motionTransitions.layout}
        >
          <div className="mx-auto w-full max-w-5xl min-w-0 px-4 pt-5 pb-12 sm:px-6 lg:px-10 lg:pt-6">
            <header className="hidden min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3 lg:grid">
              <Link
                aria-label={t("detail.back")}
                className="hover:bg-hover grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)]"
                href="/projects"
              >
                <Icon glyph={BackIcon} size={20} />
              </Link>
              <div className="min-w-0 pt-0.5">
                <div className="flex min-w-0 flex-wrap items-baseline gap-x-5 gap-y-1">
                  <h1
                    className="max-w-3xl min-w-0 text-2xl font-semibold tracking-[-0.02em] break-words"
                    data-project-title
                  >
                    {project.title}
                  </h1>
                  <dl className="text-muted flex shrink-0 flex-wrap gap-x-4 gap-y-1 text-xs">
                    <div className="flex items-center gap-1.5">
                      <dt>{t("metrics.papers")}</dt>
                      <dd className="text-secondary tabular-nums">
                        {project.num_papers}
                      </dd>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <dt>{t("metrics.conversations")}</dt>
                      <dd className="text-secondary tabular-nums">
                        {project.num_conversations}
                      </dd>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <dt>{t("metrics.outputs")}</dt>
                      <dd className="text-secondary tabular-nums">
                        {project.num_outputs}
                      </dd>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <dt>{t("metrics.members")}</dt>
                      <dd className="text-secondary tabular-nums">
                        {memberCount}
                      </dd>
                    </div>
                  </dl>
                </div>
                {project.description ? (
                  <p className="text-secondary mt-1 line-clamp-1 max-w-4xl text-sm">
                    {project.description}
                  </p>
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <ProjectManageMenu
                  onAddPapers={() => setAddPapersOpen(true)}
                  onDelete={() => setDestructive("delete")}
                  onEdit={() => setEditOpen(true)}
                  onLeave={() => setDestructive("leave")}
                  onManageCollaborators={() => setCollaboratorsOpen(true)}
                  project={project}
                />
                <IconButton
                  label={
                    state.panel === "chat"
                      ? t("detail.closeChat")
                      : t("detail.openChat")
                  }
                  onClick={() =>
                    replaceSearch({
                      panel: state.panel === "chat" ? undefined : "chat",
                    })
                  }
                  aria-pressed={state.panel === "chat"}
                  variant="ghost"
                >
                  <Icon
                    glyph={
                      state.panel === "chat" ? ClosePanelIcon : OpenPanelIcon
                    }
                    size={20}
                  />
                </IconButton>
              </div>
            </header>

            <section className="grid gap-3 lg:hidden">
              {project.description ? (
                <p className="text-secondary line-clamp-3 text-sm leading-6">
                  {project.description}
                </p>
              ) : null}
              <dl className="text-muted flex flex-wrap gap-x-4 gap-y-1 text-xs">
                <div className="flex items-center gap-1.5">
                  <dt>{t("metrics.papers")}</dt>
                  <dd className="text-secondary tabular-nums">
                    {project.num_papers}
                  </dd>
                </div>
                <div className="flex items-center gap-1.5">
                  <dt>{t("metrics.conversations")}</dt>
                  <dd className="text-secondary tabular-nums">
                    {project.num_conversations}
                  </dd>
                </div>
                <div className="flex items-center gap-1.5">
                  <dt>{t("metrics.outputs")}</dt>
                  <dd className="text-secondary tabular-nums">
                    {project.num_outputs}
                  </dd>
                </div>
                <div className="flex items-center gap-1.5">
                  <dt>{t("metrics.members")}</dt>
                  <dd className="text-secondary tabular-nums">{memberCount}</dd>
                </div>
              </dl>
            </section>

            <Tabs
              className="mt-6 lg:mt-4"
              onValueChange={(view: string) =>
                replaceSearch({ view: view as ProjectView })
              }
              value={state.view}
            >
              <TabsList className="bg-transparent p-0">
                <TabsTrigger
                  className="data-[state=active]:border-primary rounded-none border-b-2 border-transparent px-1 shadow-none data-[state=active]:bg-transparent data-[state=active]:shadow-none"
                  value="overview"
                >
                  {t("detail.tabs.overview")}
                </TabsTrigger>
                <TabsTrigger
                  className="data-[state=active]:border-primary rounded-none border-b-2 border-transparent px-1 shadow-none data-[state=active]:bg-transparent data-[state=active]:shadow-none"
                  value="papers"
                >
                  {t("detail.tabs.papers")}
                </TabsTrigger>
                <TabsTrigger
                  className="data-[state=active]:border-primary rounded-none border-b-2 border-transparent px-1 shadow-none data-[state=active]:bg-transparent data-[state=active]:shadow-none"
                  value="outputs"
                >
                  {t("detail.tabs.outputs")}
                </TabsTrigger>
              </TabsList>

              <TabsContent className="mt-5" value="overview">
                <div className="grid gap-10 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)] lg:items-start">
                  <section>
                    <div className="mb-3 flex items-center justify-between">
                      <h2 className="text-base font-semibold">
                        {t("detail.recentPapers")}
                      </h2>
                      <Button
                        onClick={() => replaceSearch({ view: "papers" })}
                        size="sm"
                        variant="ghost"
                      >
                        {t("detail.viewAll")}
                      </Button>
                    </div>
                    <div className="divide-line-subtle border-line-subtle divide-y border-y">
                      {papersQuery.data?.items.slice(0, 3).map((paper) => (
                        <ProjectPaperRow
                          canRemove={project.capabilities.manage_papers}
                          key={paper.document_id}
                          onActionTrigger={(trigger) => {
                            paperRemovalTriggerRef.current = trigger;
                          }}
                          onRemove={(paper) => void requestPaperRemoval(paper)}
                          paper={paper}
                          projectId={projectId}
                        />
                      ))}
                      {!papersQuery.isPending &&
                        papersQuery.data?.items.length === 0 && (
                          <p className="text-muted py-12 text-center text-sm">
                            {t("detail.papers.empty")}
                          </p>
                        )}
                    </div>
                  </section>
                  <div className="grid gap-10">
                    <section>
                      <div className="mb-3 flex items-center justify-between">
                        <h2 className="text-base font-semibold">
                          {t("detail.recentOutputs")}
                        </h2>
                        <Button
                          onClick={() => replaceSearch({ view: "outputs" })}
                          size="sm"
                          variant="ghost"
                        >
                          {t("detail.viewAll")}
                        </Button>
                      </div>
                      <div className="divide-line-subtle border-line-subtle divide-y border-y">
                        {outputsQuery.data?.items.slice(0, 3).map((output) => (
                          <ProjectOutputRow
                            key={output.item.id}
                            output={output}
                          />
                        ))}
                        {!outputsQuery.isPending &&
                          outputsQuery.data?.items.length === 0 && (
                            <div className="py-12 text-center">
                              <p className="text-muted text-sm">
                                {t("detail.outputs.empty")}
                              </p>
                              <Button
                                className="mt-3"
                                onClick={() => replaceSearch({ panel: "chat" })}
                                size="sm"
                                variant="ghost"
                              >
                                {t("detail.outputs.startChat")}
                              </Button>
                            </div>
                          )}
                      </div>
                    </section>
                    <section aria-labelledby="project-collaboration-heading">
                      <div className="mb-3 flex items-center justify-between">
                        <h2
                          className="text-base font-semibold"
                          id="project-collaboration-heading"
                        >
                          {t("detail.collaboration")}
                        </h2>
                        {project.capabilities.manage_collaborators ? (
                          <Button
                            onClick={() => setCollaboratorsOpen(true)}
                            size="sm"
                            variant="ghost"
                          >
                            {t("detail.manageMembers")}
                          </Button>
                        ) : null}
                      </div>
                      <div className="border-line-subtle flex items-center justify-between gap-3 border-y py-3">
                        <span className="flex min-w-0 items-center gap-3">
                          <span
                            aria-hidden="true"
                            className="bg-pressed grid size-8 shrink-0 place-items-center rounded-full text-sm font-medium"
                          >
                            {ownerInitial}
                          </span>
                          <span className="text-secondary truncate text-sm">
                            {project.owner.display_name}
                          </span>
                        </span>
                        <span className="text-secondary shrink-0 text-xs tabular-nums">
                          {t("detail.memberCount", {
                            count: memberCount,
                          })}
                        </span>
                      </div>
                    </section>
                  </div>
                </div>
              </TabsContent>

              <TabsContent className="mt-5" value="papers">
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_13rem]">
                  <ProjectSearchField
                    key={state.paperQuery}
                    label={t("detail.papers.search")}
                    onChange={(paperQuery) =>
                      replaceSearch({ paperCursor: undefined, paperQuery })
                    }
                    value={state.paperQuery}
                  />
                  <Select
                    onValueChange={(paperSort: ProjectPaperSort) =>
                      replaceSearch({ paperCursor: undefined, paperSort })
                    }
                    value={state.paperSort}
                  >
                    <SelectTrigger aria-label={t("detail.papers.sortLabel")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="added_desc">
                        {t("detail.papers.sortAdded")}
                      </SelectItem>
                      <SelectItem value="title_asc">
                        {t("detail.papers.sortTitle")}
                      </SelectItem>
                      <SelectItem value="published_desc">
                        {t("detail.papers.sortPublished")}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="divide-line-subtle border-line-subtle mt-5 divide-y border-y">
                  {papersQuery.isPending ? (
                    <div className="py-6">
                      <LoadingState />
                    </div>
                  ) : papersQuery.isError ? (
                    <div className="py-6">
                      <AsyncFeedback
                        action={{
                          label: t("feedback.retry"),
                          onClick: () => void papersQuery.refetch(),
                        }}
                        state="error"
                      />
                    </div>
                  ) : papersQuery.data.items.length === 0 ? (
                    <p className="text-muted py-12 text-center text-sm">
                      {t("detail.papers.empty")}
                    </p>
                  ) : (
                    papersQuery.data.items.map((paper) => (
                      <ProjectPaperRow
                        canRemove={project.capabilities.manage_papers}
                        key={paper.document_id}
                        onActionTrigger={(trigger) => {
                          paperRemovalTriggerRef.current = trigger;
                        }}
                        onRemove={(paper) => void requestPaperRemoval(paper)}
                        paper={paper}
                        projectId={projectId}
                      />
                    ))
                  )}
                </div>
                {papersQuery.data &&
                  (papersQuery.data.previous_cursor ||
                    papersQuery.data.next_cursor) && (
                    <div className="mt-5 flex justify-end">
                      <CursorPagination
                        nextDisabled={!papersQuery.data.next_cursor}
                        nextLabel={t("pagination.next")}
                        onNext={() =>
                          papersQuery.data.next_cursor &&
                          replaceSearch({
                            paperCursor: papersQuery.data.next_cursor,
                          })
                        }
                        onPrevious={() =>
                          papersQuery.data.previous_cursor &&
                          replaceSearch({
                            paperCursor: papersQuery.data.previous_cursor,
                          })
                        }
                        previousDisabled={!papersQuery.data.previous_cursor}
                        previousLabel={t("pagination.previous")}
                      />
                    </div>
                  )}
              </TabsContent>

              <TabsContent className="mt-5" value="outputs">
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_13rem_13rem]">
                  <ProjectSearchField
                    key={state.outputQuery}
                    label={t("detail.outputs.search")}
                    onChange={(outputQuery) =>
                      replaceSearch({ outputCursor: undefined, outputQuery })
                    }
                    value={state.outputQuery}
                  />
                  <Select
                    onValueChange={(value) =>
                      replaceSearch({
                        outputCursor: undefined,
                        outputKinds:
                          value === "all" ? [] : [value as ProjectOutputKind],
                      })
                    }
                    value={state.outputKinds[0] ?? "all"}
                  >
                    <SelectTrigger aria-label={t("detail.outputs.kindLabel")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">
                        {t("detail.outputs.allKinds")}
                      </SelectItem>
                      {(
                        [
                          "annotation_thread",
                          "citation",
                          "audio_overview",
                          "data_table",
                        ] as const
                      ).map((kind) => (
                        <SelectItem key={kind} value={kind}>
                          {t(`detail.outputs.kinds.${kind}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select
                    onValueChange={(outputSort: ProjectOutputSort) =>
                      replaceSearch({ outputCursor: undefined, outputSort })
                    }
                    value={state.outputSort}
                  >
                    <SelectTrigger aria-label={t("detail.outputs.sortLabel")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="updated_desc">
                        {t("detail.outputs.sortUpdated")}
                      </SelectItem>
                      <SelectItem value="title_asc">
                        {t("detail.outputs.sortTitle")}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="divide-line-subtle border-line-subtle mt-5 divide-y border-y">
                  {outputsQuery.isPending ? (
                    <div className="py-6">
                      <LoadingState />
                    </div>
                  ) : outputsQuery.isError ? (
                    <div className="py-6">
                      <AsyncFeedback
                        action={{
                          label: t("feedback.retry"),
                          onClick: () => void outputsQuery.refetch(),
                        }}
                        state="error"
                      />
                    </div>
                  ) : outputsQuery.data.items.length === 0 ? (
                    <div className="py-12 text-center">
                      <p className="text-muted text-sm">
                        {t("detail.outputs.empty")}
                      </p>
                      <Button
                        className="mt-3"
                        onClick={() => replaceSearch({ panel: "chat" })}
                        size="sm"
                        variant="ghost"
                      >
                        {t("detail.outputs.startChat")}
                      </Button>
                    </div>
                  ) : (
                    outputsQuery.data.items.map((output) => (
                      <ProjectOutputRow key={output.item.id} output={output} />
                    ))
                  )}
                </div>
                {outputsQuery.data &&
                  (outputsQuery.data.previous_cursor ||
                    outputsQuery.data.next_cursor) && (
                    <div className="mt-5 flex justify-end">
                      <CursorPagination
                        nextDisabled={!outputsQuery.data.next_cursor}
                        nextLabel={t("pagination.next")}
                        onNext={() =>
                          outputsQuery.data.next_cursor &&
                          replaceSearch({
                            outputCursor: outputsQuery.data.next_cursor,
                          })
                        }
                        onPrevious={() =>
                          outputsQuery.data.previous_cursor &&
                          replaceSearch({
                            outputCursor: outputsQuery.data.previous_cursor,
                          })
                        }
                        previousDisabled={!outputsQuery.data.previous_cursor}
                        previousLabel={t("pagination.previous")}
                      />
                    </div>
                  )}
              </TabsContent>
            </Tabs>
          </div>
        </m.div>
        <AnimatePresence initial={false}>
          {desktopLayout && state.panel === "chat" ? (
            <m.aside
              animate="animate"
              className="border-line flex w-[clamp(23rem,34vw,31.25rem)] shrink-0 border-l"
              exit="exit"
              initial="initial"
              key="project-chat"
              variants={motionVariants.panel}
            >
              {renderChat()}
            </m.aside>
          ) : null}
        </AnimatePresence>
      </m.div>

      {!desktopLayout ? (
        <Sheet
          onOpenChange={(open) => {
            if (!open) replaceSearch({ panel: undefined });
          }}
          open={state.panel === "chat"}
        >
          <SheetContent
            className="inset-0 h-[100dvh] w-full max-w-none border-0 p-0 pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] data-[state=closed]:hidden"
            closeLabel={t("detail.closeChat")}
            forceMount
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              mobileChatTriggerRef.current?.focus();
            }}
            showCloseButton={false}
          >
            <SheetTitle className="sr-only">{t("chat.title")}</SheetTitle>
            {renderChat(() => replaceSearch({ panel: undefined }))}
          </SheetContent>
        </Sheet>
      ) : null}

      <ProjectFormDialog
        initialValue={{
          description: project.description ?? "",
          title: project.title,
        }}
        mode="edit"
        onOpenChange={setEditOpen}
        onSubmit={(value) => updateMutation.mutateAsync(value)}
        open={editOpen}
      />
      <AddProjectPapersDialog
        entries={libraryPapersQuery.data?.items ?? []}
        loading={libraryPapersQuery.isPending}
        onOpenChange={setAddPapersOpen}
        onSubmit={(documentIds) => addPapersMutation.mutateAsync(documentIds)}
        open={addPapersOpen}
      />
      {project.capabilities.manage_collaborators ? (
        <ManageProjectCollaboratorsDialog
          actorId={actor.id}
          onOpenChange={setCollaboratorsOpen}
          open={collaboratorsOpen}
          project={project}
        />
      ) : null}
      <AlertDialog
        onOpenChange={(open) => !open && setDestructive(null)}
        open={Boolean(destructive)}
      >
        <AlertDialogContent>
          <AlertDialogTitle>
            {t(`confirm.${destructive ?? "delete"}.title`)}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t(`confirm.${destructive ?? "delete"}.description`, {
              title: project.title,
            })}
          </AlertDialogDescription>
          <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-end">
            <AlertDialogCancel asChild>
              <Button className="w-full sm:w-auto" variant="secondary">
                {t("confirm.cancel")}
              </Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                className="w-full sm:w-auto"
                loading={deleteMutation.isPending || leaveMutation.isPending}
                onClick={() => void confirmDestructive()}
                variant="danger"
              >
                {t(`confirm.${destructive ?? "delete"}.action`)}
              </Button>
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog
        onOpenChange={(open) => !open && setPaperRemoval(null)}
        open={Boolean(paperRemoval)}
      >
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            paperRemovalTriggerRef.current?.focus();
          }}
        >
          <AlertDialogTitle>
            {t("detail.papers.confirm.title")}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t("detail.papers.confirm.description", {
              comments: paperRemoval?.commentCount ?? 0,
              threads: paperRemoval?.threadCount ?? 0,
              title: paperRemoval?.paper.title || t("detail.papers.untitled"),
            })}
          </AlertDialogDescription>
          <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-end">
            <AlertDialogCancel asChild>
              <Button className="w-full sm:w-auto" variant="secondary">
                {t("confirm.cancel")}
              </Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                className="w-full sm:w-auto"
                loading={removePaperMutation.isPending}
                onClick={() => void confirmPaperRemoval()}
                variant="danger"
              >
                {t("detail.papers.confirm.action")}
              </Button>
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </WorkspaceShell>
  );
}

export function ProjectDetailPage({ projectId }: { projectId: string }) {
  const router = useRouter();
  const t = useTranslations("Projects.session");
  const session = useAuthSession();
  React.useEffect(() => {
    if (session.status === "anonymous") {
      router.replace(
        `/login?returnTo=${encodeURIComponent(`/projects/${projectId}`)}`,
      );
    }
  }, [projectId, router, session.status]);
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
  return <ProjectDetailWorkspace actor={session.actor} projectId={projectId} />;
}
