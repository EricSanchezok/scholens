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
  SearchField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useToast,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  AddIcon,
  AudioIcon,
  BackIcon,
  CitationIcon,
  DataTableIcon,
  DeleteIcon,
  EditIcon,
  MoreIcon,
  QuoteIcon,
} from "@/design-system/icons/semantic-icons";
import { useAuthSession, type Actor } from "@/features/authentication";
import {
  ConversationView,
  useConversationSession,
  type ReasoningLevel,
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
import { ProjectFormDialog } from "./components/project-form-dialog";
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
      onChange={(event) => setInput(event.currentTarget.value)}
      placeholder={label}
      value={input}
    />
  );
}

function ProjectChat({
  conversationId,
  conversations,
  onConversationChange,
  project,
}: {
  conversationId?: string;
  conversations: components["schemas"]["ConversationSummaryResponse"][];
  onConversationChange: (conversationId?: string) => void;
  project: Project;
}) {
  const t = useTranslations("Projects.chat");
  const [reasoningLevel, setReasoningLevel] =
    React.useState<ReasoningLevel>("standard");
  const session = useConversationSession({
    context: { kind: "selection", document_ids: [], project_ids: [project.id] },
    conversationId,
    onConversationCreated: (id) => onConversationChange(id),
    reasoningLevel,
    scopeId: project.id,
    scopeType: "project",
  });
  return (
    <section
      className="bg-canvas flex h-full min-h-0 flex-col"
      aria-label={t("title")}
    >
      <div className="border-line flex h-16 shrink-0 items-center gap-3 border-b px-4">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold">{t("title")}</h2>
          <p className="text-muted truncate text-xs">{project.title}</p>
        </div>
        <Select
          onValueChange={(value) =>
            onConversationChange(value === "new" ? undefined : value)
          }
          value={conversationId ?? "new"}
        >
          <SelectTrigger className="h-9 w-44" aria-label={t("switcher")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="new">{t("new")}</SelectItem>
            {conversations.map((conversation) => (
              <SelectItem key={conversation.id} value={conversation.id}>
                {conversation.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="min-h-0 flex-1">
        <ConversationView
          canSend={session.canSend}
          composerForm={session.composerForm}
          context={session.context}
          contextLabel={project.title}
          contextLocked
          emptyState={{
            description: t("emptyDescription"),
            title: t("emptyTitle"),
          }}
          error={session.turnsQuery.isError}
          layout="side-panel"
          liveTurn={session.liveTurn}
          loading={session.turnsQuery.isPending && Boolean(conversationId)}
          onContextChange={() => undefined}
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

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="border-line border-b py-4 last:border-b-0 sm:border-r sm:border-b-0 sm:px-5 sm:first:pl-0 sm:last:border-r-0">
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      <div className="text-muted mt-1 text-xs">{label}</div>
    </div>
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
    <div className="border-line grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-b px-1 py-2 last:border-b-0">
      <Link
        className="hover:bg-hover grid min-w-0 gap-2 rounded-[var(--radius-md)] px-2 py-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
        href={`/reader/${paper.document_id}?project=${projectId}` as Route}
      >
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">
            {paper.title || t("untitled")}
          </span>
          <span className="text-muted mt-1 block truncate text-xs">
            {paper.authors?.join(", ") || t("unknownAuthors")}
          </span>
        </span>
        <span className="text-muted text-xs">{t("openReader")}</span>
      </Link>
      {canRemove && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <IconButton
              label={t("openMenu")}
              onClick={(event) => onActionTrigger(event.currentTarget)}
              variant="ghost"
            >
              <Icon glyph={MoreIcon} size={20} />
            </IconButton>
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
  paper: ProjectPaper;
  threadCount: number;
};

function paperRemovalImpact(
  error: unknown,
  paper: ProjectPaper,
): PaperRemovalImpact | undefined {
  if (
    !(error instanceof ApiError) ||
    error.code !== "project_document_has_annotations"
  ) {
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
    <div className="border-line flex min-w-0 items-center gap-3 border-b px-1 py-4 last:border-b-0">
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
  const [paperRemoval, setPaperRemoval] =
    React.useState<PaperRemovalImpact | null>(null);
  const paperRemovalTriggerRef = React.useRef<HTMLButtonElement | null>(null);
  const [destructive, setDestructive] = React.useState<
    "delete" | "leave" | null
  >(null);
  const projectQuery = useQuery(projectQueries.detail(projectId));
  const conversationsQuery = useQuery(projectQueries.conversations(projectId));
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
    },
  });
  const removePaperMutation = useMutation({
    mutationFn: ({
      confirmDeleteAnnotations,
      documentId,
    }: {
      confirmDeleteAnnotations: boolean;
      documentId: string;
    }) => removeProjectPaper(projectId, documentId, confirmDeleteAnnotations),
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
        confirmDeleteAnnotations: false,
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
        confirmDeleteAnnotations: true,
        documentId: paperRemoval.paper.document_id,
      });
      setPaperRemoval(null);
      toast.notify({ title: t("detail.papers.removed") });
    } catch {
      toast.notify({ title: t("detail.papers.removeFailed") });
    }
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
  const chat = (
    <ProjectChat
      conversationId={state.conversation}
      conversations={conversationsQuery.data?.items ?? []}
      onConversationChange={(conversation) =>
        replaceSearch({ conversation, panel: "chat" })
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
      conversationHref={(conversationId) =>
        `/projects/${projectId}?conversation=${conversationId}&panel=chat`
      }
      conversations={conversationsQuery.data?.items ?? []}
      mobileHeaderCenter={
        <span className="block truncate text-base font-semibold">
          {state.panel === "chat" ? t("chat.title") : project.title}
        </span>
      }
      mobileHeaderLeading={
        state.panel === "chat" ? (
          <IconButton
            label={t("detail.closeChat")}
            onClick={() => replaceSearch({ panel: undefined })}
            variant="ghost"
          >
            <Icon glyph={BackIcon} size={20} />
          </IconButton>
        ) : undefined
      }
      mobileHeaderTrailing={
        state.panel !== "chat" ? (
          <Button
            onClick={() => replaceSearch({ panel: "chat" })}
            size="sm"
            variant="ghost"
          >
            {t("detail.openChat")}
          </Button>
        ) : null
      }
      onCollapsedChange={setCollapsed}
      onSignOut={handleSignOut}
      showMobileBottomNavigation={state.panel !== "chat"}
      signingOut={signingOut}
    >
      <div className="flex h-full min-h-0">
        <div
          className={
            state.panel === "chat"
              ? "hidden min-w-0 flex-1 lg:block"
              : "min-w-0 flex-1"
          }
        >
          <div className="mx-auto w-full max-w-5xl px-5 py-7 sm:px-8 lg:px-10 lg:py-9">
            <header className="flex min-w-0 items-start gap-4">
              <Link
                aria-label={t("detail.back")}
                className="hover:bg-hover grid size-10 shrink-0 place-items-center rounded-[var(--radius-md)]"
                href="/projects"
              >
                <Icon glyph={BackIcon} size={20} />
              </Link>
              <div className="min-w-0 flex-1">
                <h1 className="truncate text-2xl font-semibold tracking-[-0.02em]">
                  {project.title}
                </h1>
                <p className="text-secondary mt-2 line-clamp-2 max-w-3xl text-sm">
                  {project.description || t("row.noDescription")}
                </p>
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <IconButton label={t("detail.manage")} variant="secondary">
                    <Icon glyph={MoreIcon} size={20} />
                  </IconButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {project.capabilities.edit_project && (
                    <DropdownMenuItem onSelect={() => setEditOpen(true)}>
                      <Icon glyph={EditIcon} size={16} />
                      {t("actions.edit")}
                    </DropdownMenuItem>
                  )}
                  {(project.capabilities.delete ||
                    project.capabilities.leave) &&
                    project.capabilities.edit_project && (
                      <DropdownMenuSeparator />
                    )}
                  {project.capabilities.delete && (
                    <DropdownMenuItem
                      destructive
                      onSelect={() => setDestructive("delete")}
                    >
                      {t("actions.delete")}
                    </DropdownMenuItem>
                  )}
                  {project.capabilities.leave && (
                    <DropdownMenuItem
                      destructive
                      onSelect={() => setDestructive("leave")}
                    >
                      {t("actions.leave")}
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </header>

            <Tabs
              className="mt-7"
              onValueChange={(view: string) =>
                replaceSearch({ view: view as ProjectView })
              }
              value={state.view}
            >
              <TabsList>
                <TabsTrigger value="overview">
                  {t("detail.tabs.overview")}
                </TabsTrigger>
                <TabsTrigger value="papers">
                  {t("detail.tabs.papers")}
                </TabsTrigger>
                <TabsTrigger value="outputs">
                  {t("detail.tabs.outputs")}
                </TabsTrigger>
              </TabsList>

              <TabsContent className="mt-6 grid gap-8" value="overview">
                <section className="border-line bg-surface grid rounded-[var(--radius-xl)] border px-5 sm:grid-cols-3">
                  <Metric
                    label={t("metrics.papers")}
                    value={project.num_papers}
                  />
                  <Metric
                    label={t("metrics.conversations")}
                    value={project.num_conversations}
                  />
                  <Metric
                    label={t("metrics.outputs")}
                    value={project.num_outputs}
                  />
                </section>
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
                  <div className="border-line bg-surface rounded-[var(--radius-xl)] border px-4">
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
                        <p className="text-muted py-8 text-center text-sm">
                          {t("detail.papers.empty")}
                        </p>
                      )}
                  </div>
                </section>
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
                  <div className="border-line bg-surface rounded-[var(--radius-xl)] border px-4">
                    {outputsQuery.data?.items.slice(0, 3).map((output) => (
                      <ProjectOutputRow key={output.item.id} output={output} />
                    ))}
                    {!outputsQuery.isPending &&
                      outputsQuery.data?.items.length === 0 && (
                        <div className="py-8 text-center">
                          <p className="text-muted text-sm">
                            {t("detail.outputs.empty")}
                          </p>
                          <Button
                            className="mt-3"
                            onClick={() => replaceSearch({ panel: "chat" })}
                            size="sm"
                            variant="secondary"
                          >
                            {t("detail.outputs.startChat")}
                          </Button>
                        </div>
                      )}
                  </div>
                </section>
              </TabsContent>

              <TabsContent className="mt-6" value="papers">
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_13rem_auto]">
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
                  {project.capabilities.manage_papers && (
                    <Button onClick={() => setAddPapersOpen(true)}>
                      <Icon glyph={AddIcon} size={20} />
                      {t("detail.papers.add")}
                    </Button>
                  )}
                </div>
                <div className="border-line bg-surface mt-5 rounded-[var(--radius-xl)] border px-4">
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
                    <p className="text-muted py-10 text-center text-sm">
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

              <TabsContent className="mt-6" value="outputs">
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
                <div className="border-line bg-surface mt-5 rounded-[var(--radius-xl)] border px-4">
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
                    <div className="py-10 text-center">
                      <p className="text-muted text-sm">
                        {t("detail.outputs.empty")}
                      </p>
                      <Button
                        className="mt-3"
                        onClick={() => replaceSearch({ panel: "chat" })}
                        size="sm"
                        variant="secondary"
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
        </div>
        <aside
          className={
            state.panel === "chat"
              ? "min-w-0 flex-1 lg:w-[26rem] lg:flex-none"
              : "border-line hidden w-[26rem] shrink-0 border-l lg:block"
          }
        >
          {chat}
        </aside>
      </div>

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
