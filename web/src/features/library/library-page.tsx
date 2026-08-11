"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "iconoir-react";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import {
  Button,
  IconButton,
  SearchField,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useToast,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { useAuthSession, type Actor } from "@/features/authentication";
import { WorkspaceShell } from "@/features/workspace-shell";
import {
  addPapersToProject,
  assignLibraryTags,
  getPaperDownloadUrl,
  libraryKeys,
  libraryQueries,
  removeLibraryPapers,
  retryPaperIngestion,
} from "./api";
import { AddPapersDialog } from "./components/add-papers-dialog";
import { PapersView } from "./components/papers-view";
import {
  parseLibrarySearch,
  serializeLibrarySearch,
  type LibrarySearchState,
  type LibraryTab,
  type PaperSort,
} from "./library-search";

function useDebouncedValue(value: string, delay: number) {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [delay, value]);
  return debounced;
}

function DebouncedLibrarySearch({
  label,
  onQueryChange,
  value,
}: {
  label: string;
  onQueryChange: (query: string) => void;
  value: string;
}) {
  const [input, setInput] = React.useState(value);
  const debounced = useDebouncedValue(input, 250);
  React.useEffect(() => {
    if (debounced !== value) onQueryChange(debounced);
  }, [debounced, onQueryChange, value]);
  return (
    <SearchField
      aria-label={label}
      onChange={(event) => setInput(event.currentTarget.value)}
      placeholder={label}
      value={input}
    />
  );
}

export function LibraryWorkspace({ actor }: { actor: Actor }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const t = useTranslations("Library");
  const { signOut } = useAuthSession();
  const parsed = React.useMemo(
    () => parseLibrarySearch(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const [collapsed, setCollapsed] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const [addOpen, setAddOpen] = React.useState(false);
  const completedJobIds = React.useRef(new Set<string>());

  const replaceSearch = React.useCallback(
    (patch: Partial<LibrarySearchState>) => {
      const next = { ...parsed, ...patch };
      const query = serializeLibrarySearch(next).toString();
      router.replace((query ? `/library?${query}` : "/library") as Route, {
        scroll: false,
      });
    },
    [parsed, router],
  );

  const conversationsQuery = useQuery(libraryQueries.conversations());
  const summaryQuery = useQuery(libraryQueries.summary());
  const tagsQuery = useQuery(libraryQueries.tags());
  const projectsQuery = useQuery(libraryQueries.projects());
  const jobsQuery = useQuery(libraryQueries.ingestions());
  const papersQuery = useQuery({
    ...libraryQueries.papers({
      cursor: parsed.cursor,
      query: parsed.query,
      sort: parsed.sort,
      tagIds: parsed.tagIds,
    }),
    enabled: parsed.tab === "papers",
  });

  React.useEffect(() => {
    const completed =
      jobsQuery.data?.items.filter((job) => job.status === "completed") ?? [];
    const hasNewCompletion = completed.some(
      (job) => !completedJobIds.current.has(job.id),
    );
    completed.forEach((job) => completedJobIds.current.add(job.id));
    if (hasNewCompletion) {
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: [...libraryKeys.all, "papers"],
        }),
        queryClient.invalidateQueries({ queryKey: libraryKeys.summary() }),
      ]);
    }
  }, [jobsQuery.data, queryClient]);

  const retryMutation = useMutation({
    mutationFn: retryPaperIngestion,
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: libraryKeys.ingestions(),
      });
    },
  });
  const removeMutation = useMutation({
    mutationFn: removeLibraryPapers,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: [...libraryKeys.all, "papers"],
        }),
        queryClient.invalidateQueries({ queryKey: libraryKeys.summary() }),
      ]);
    },
  });
  const tagMutation = useMutation({
    mutationFn: ({
      documentIds,
      tagIds,
    }: {
      documentIds: string[];
      tagIds: string[];
    }) => assignLibraryTags(documentIds, tagIds),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: [...libraryKeys.all, "papers"],
      });
    },
  });
  const projectMutation = useMutation({
    mutationFn: ({
      documentIds,
      projectId,
    }: {
      documentIds: string[];
      projectId: string;
    }) => addPapersToProject(projectId, documentIds),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: libraryKeys.projects() });
    },
  });

  async function runAction(action: () => Promise<unknown>) {
    try {
      await action();
    } catch {
      toast.notify({ title: t("common.actionFailed") });
    }
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

  function handleTabChange(value: string) {
    const tab = value as LibraryTab;
    replaceSearch({
      cursor: undefined,
      kinds: tab === "outputs" ? parsed.kinds : [],
      sort: tab === "outputs" ? "updated_desc" : "added_desc",
      tab,
      tagIds: tab === "papers" ? parsed.tagIds : [],
    });
  }

  async function handleDownload(documentId: string) {
    const pendingWindow = window.open("about:blank", "_blank");
    if (pendingWindow) pendingWindow.opener = null;
    try {
      const data = await getPaperDownloadUrl(documentId);
      if (pendingWindow) pendingWindow.location.href = data.file_url;
      else window.location.assign(data.file_url);
    } catch {
      pendingWindow?.close();
      toast.notify({ title: t("papers.actions.downloadFailed") });
    }
  }

  const countLabel = (count: number | undefined) =>
    typeof count === "number" ? count.toLocaleString() : "—";

  return (
    <WorkspaceShell
      activeDestination="library"
      actor={actor}
      collapsed={collapsed}
      conversations={conversationsQuery.data?.items ?? []}
      mobileHeaderCenter={
        <span className="block truncate text-base font-semibold">
          {t("title")}
        </span>
      }
      mobileHeaderTrailing={
        <IconButton
          label={t("addPapers.open")}
          onClick={() => setAddOpen(true)}
          variant="ghost"
        >
          <Icon glyph={Plus} size={24} />
        </IconButton>
      }
      onCollapsedChange={setCollapsed}
      onSignOut={handleSignOut}
      signingOut={signingOut}
    >
      <div className="mx-auto w-full max-w-6xl px-4 pt-5 pb-12 sm:px-6 lg:px-10 lg:pt-10">
        <header className="hidden items-start justify-between gap-6 lg:flex">
          <div>
            <h1 className="text-3xl font-semibold tracking-[-0.02em]">
              {t("title")}
            </h1>
            <p className="text-secondary mt-2 text-sm">{t("description")}</p>
          </div>
          <Button onClick={() => setAddOpen(true)}>
            <Icon glyph={Plus} size={20} tone="inverse" />
            {t("addPapers.open")}
          </Button>
        </header>

        <Tabs
          className="mt-0 lg:mt-8"
          onValueChange={handleTabChange}
          value={parsed.tab}
        >
          <TabsList className="bg-transparent p-0">
            <TabsTrigger
              className="data-[state=active]:border-primary rounded-none border-b-2 border-transparent px-1 shadow-none data-[state=active]:bg-transparent data-[state=active]:shadow-none"
              value="papers"
            >
              {t("tabs.papers", {
                count: countLabel(summaryQuery.data?.paper_count),
              })}
            </TabsTrigger>
            <TabsTrigger
              className="data-[state=active]:border-primary rounded-none border-b-2 border-transparent px-1 shadow-none data-[state=active]:bg-transparent data-[state=active]:shadow-none"
              value="outputs"
            >
              {t("tabs.outputs", {
                count: countLabel(summaryQuery.data?.output_count),
              })}
            </TabsTrigger>
          </TabsList>
          <TabsContent className="mt-5 grid gap-4" value="papers">
            <div className="max-w-md">
              <DebouncedLibrarySearch
                key={`papers:${parsed.query}`}
                label={t("papers.search")}
                onQueryChange={(query) =>
                  replaceSearch({ cursor: undefined, query })
                }
                value={parsed.query}
              />
            </div>
            <PapersView
              key={`${parsed.query}:${parsed.sort}:${parsed.cursor ?? ""}:${parsed.tagIds.join(",")}`}
              data={papersQuery.data}
              error={papersQuery.error}
              jobs={jobsQuery.data?.items ?? []}
              loading={papersQuery.isPending}
              onAddToProject={(documentIds, projectId) =>
                runAction(() =>
                  projectMutation.mutateAsync({ documentIds, projectId }),
                )
              }
              onAssignTags={(documentIds, tagIds) =>
                runAction(() =>
                  tagMutation.mutateAsync({ documentIds, tagIds }),
                )
              }
              onDownload={(documentId) => void handleDownload(documentId)}
              onNext={(cursor) => replaceSearch({ cursor })}
              onPrevious={(cursor) => replaceSearch({ cursor })}
              onRemove={(documentIds) =>
                runAction(() => removeMutation.mutateAsync(documentIds))
              }
              onRetry={(jobId) =>
                void runAction(() => retryMutation.mutateAsync(jobId))
              }
              onRetryLoad={() => void papersQuery.refetch()}
              onSortChange={(sort: PaperSort) =>
                replaceSearch({ cursor: undefined, sort })
              }
              onTagFilterChange={(tagIds) =>
                replaceSearch({ cursor: undefined, tagIds })
              }
              projects={projectsQuery.data?.items ?? []}
              retryingJobId={retryMutation.variables}
              sort={parsed.sort as PaperSort}
              tagIds={parsed.tagIds}
              tags={tagsQuery.data?.items ?? []}
            />
          </TabsContent>
          <TabsContent className="mt-5 grid gap-4" value="outputs">
            <div className="max-w-md">
              <DebouncedLibrarySearch
                key={`outputs:${parsed.query}`}
                label={t("outputs.search")}
                onQueryChange={(query) =>
                  replaceSearch({ cursor: undefined, query })
                }
                value={parsed.query}
              />
            </div>
            <AsyncFeedback
              description={t("outputs.notAvailableDescription")}
              state="empty"
              title={t("outputs.notAvailableTitle")}
            />
          </TabsContent>
        </Tabs>
      </div>

      <AddPapersDialog
        onIngestionStarted={() => {
          void queryClient.invalidateQueries({
            queryKey: libraryKeys.ingestions(),
          });
        }}
        onOpenChange={setAddOpen}
        open={addOpen}
        projects={projectsQuery.data?.items ?? []}
      />
    </WorkspaceShell>
  );
}

export function LibraryPage() {
  const router = useRouter();
  const t = useTranslations("Library.session");
  const session = useAuthSession();

  React.useEffect(() => {
    if (session.status === "anonymous") {
      router.replace(`/login?returnTo=${encodeURIComponent("/library")}`);
    }
  }, [router, session.status]);

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
  return <LibraryWorkspace actor={session.actor} />;
}
