"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  useQueries,
} from "@tanstack/react-query";
import { AddIcon } from "@/design-system/icons/semantic-icons";
import type { Route } from "next";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import {
  Button,
  focusSurfaceVariants,
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
import { integrationQueries } from "@/features/integrations";
import {
  chunkPaperSummaryDocumentIds,
  hasPaperActivityEvidence,
  researchActivityQueries,
  type PaperActivitySummary,
} from "@/features/research-activity";
import { useSettingsLauncher } from "@/features/settings";
import {
  PaperSearchForm,
  paperSearchQueries,
  usePaperSearchDraft,
  usePaperSearchWorkbench,
} from "@/features/paper-search";
import { WorkspaceShell } from "@/features/workspace-shell";
import { usePrimaryContentReady } from "@/lib/observability/web-performance";
import { isSearchQuery } from "@/lib/search/query";
import {
  ZoteroOperationStatus,
  clearZoteroCallbackParams,
  shouldOpenZoteroLibrary,
  zoteroKeys,
  zoteroOAuthResultKey,
  zoteroQueries,
  type ZoteroOperation,
} from "@/features/zotero";
import {
  createLibraryTag,
  deleteLibraryTag,
  getPaperDownloadUrl,
  libraryKeys,
  libraryQueries,
  renameLibraryTag,
  removeLibraryPapers,
  replaceLibraryTagAssignments,
} from "./api";
import {
  PaperCollectionSidePanelLayout,
  updatePaperStatus,
} from "@/features/paper-collection";
import { OutputsView } from "./components/outputs-view";
import { PapersView } from "./components/papers-view";
import {
  parseLibrarySearch,
  serializeLibrarySearch,
  type LibrarySearchState,
  type LibraryTab,
  type OutputSort,
  type PaperSort,
} from "./library-search";
import { usePaperIngestions } from "./use-paper-ingestions";

const loadAddPapersDialog = () =>
  import("./components/add-papers-dialog").then(
    (module) => module.AddPapersDialog,
  );
const AddPapersDialog = dynamic(loadAddPapersDialog, { ssr: false });
const loadZoteroLibraryDialog = () =>
  import("@/features/zotero").then((module) => module.ZoteroLibraryDialog);
const ZoteroLibraryDialog = dynamic(loadZoteroLibraryDialog, { ssr: false });

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
      className="border-line text-base sm:text-sm"
      onChange={(event) => setInput(event.currentTarget.value)}
      placeholder={label}
      surfaceClassName="rounded-full"
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
  const zoteroT = useTranslations("Zotero.oauth");
  const { signOut } = useAuthSession();
  const { openSection: openSettingsSection } = useSettingsLauncher();
  const parsed = React.useMemo(
    () => parseLibrarySearch(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const paperSearchActive = isSearchQuery(parsed.query);
  const [paperSearchDraft, setPaperSearchDraft] = usePaperSearchDraft(
    parsed.query,
    "library-papers",
  );
  const [collapsed, setCollapsed] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const [addOpen, setAddOpen] = React.useState(false);
  const [zoteroOpen, setZoteroOpen] = React.useState(() =>
    shouldOpenZoteroLibrary(searchParams.toString()),
  );
  const [tagsRequested, setTagsRequested] = React.useState(
    parsed.tagIds.length > 0,
  );
  const [zoteroOperation, setZoteroOperation] =
    React.useState<ZoteroOperation>();
  const [pendingMineruRetry, setPendingMineruRetry] = React.useState<string>();
  const resumingMineruRetry = React.useRef(false);
  const runAction = React.useCallback(
    async (action: () => Promise<unknown>) => {
      try {
        await action();
      } catch {
        toast.notify({ title: t("common.actionFailed") });
      }
    },
    [t, toast],
  );

  React.useEffect(() => {
    if (zoteroOpen) void loadZoteroLibraryDialog();
  }, [zoteroOpen]);

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

  React.useEffect(() => {
    const intent = searchParams.get("zotero_intent");
    const state = searchParams.get("zotero");
    if (intent !== "import" && searchParams.get("zotero_import") !== "1") {
      return;
    }
    if (state && state !== "connected") {
      toast.notify({ title: zoteroT(zoteroOAuthResultKey(state)) });
    }
    if (state) {
      const next = clearZoteroCallbackParams(searchParams.toString());
      const query = next.toString();
      router.replace((query ? `/library?${query}` : "/library") as Route, {
        scroll: false,
      });
    }
  }, [router, searchParams, toast, zoteroT]);

  const summaryQuery = useQuery(libraryQueries.summary());
  const tagsQuery = useQuery({
    ...libraryQueries.tags(),
    enabled: tagsRequested,
  });
  const papersQuery = useInfiniteQuery({
    ...libraryQueries.papers({
      query: parsed.query,
      sort: parsed.sort,
      tagIds: parsed.tagIds,
      statuses: parsed.statuses,
    }),
    enabled: parsed.tab === "papers" && !paperSearchActive,
  });
  const paperSearchQuery = useInfiniteQuery({
    ...paperSearchQueries.infiniteResults(
      parsed.query,
      {
        kind: "personal_library",
      },
      {
        personal_statuses: parsed.statuses,
        personal_tag_ids: parsed.tagIds,
      },
    ),
    enabled: parsed.tab === "papers" && paperSearchActive,
  });
  const paperSearchResults = React.useMemo(
    () => paperSearchQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [paperSearchQuery.data?.pages],
  );
  const paperSearchWorkbench = usePaperSearchWorkbench({
    enabled: parsed.tab === "papers" && paperSearchActive,
    error: paperSearchQuery.error,
    hasMore: paperSearchQuery.hasNextPage,
    loading: paperSearchQuery.isPending,
    loadingMore: paperSearchQuery.isFetchingNextPage,
    onLoadMore: () => paperSearchQuery.fetchNextPage().then(() => undefined),
    onRetry: () => void paperSearchQuery.refetch(),
    onTagClick: (tagId) =>
      replaceSearch({
        cursor: undefined,
        tagIds: parsed.tagIds.includes(tagId)
          ? parsed.tagIds
          : [...parsed.tagIds, tagId],
      }),
    papers: paperSearchResults,
  });
  const outputsQuery = useQuery({
    ...libraryQueries.outputs({
      cursor: parsed.cursor,
      kinds: parsed.kinds,
      query: parsed.query,
      sort: parsed.sort,
    }),
    enabled: parsed.tab === "outputs",
  });
  usePrimaryContentReady(
    parsed.tab === "papers"
      ? paperSearchActive
        ? paperSearchQuery.isSuccess
        : papersQuery.isSuccess
      : outputsQuery.isSuccess,
  );
  const zoteroStatus = useQuery({
    ...zoteroQueries.status(),
    enabled:
      zoteroOpen ||
      papersQuery.isSuccess ||
      paperSearchQuery.isSuccess ||
      outputsQuery.isSuccess,
  });
  const zoteroOperationId =
    zoteroOperation?.id ??
    (zoteroStatus.data?.active_operation_kind === "import"
      ? (zoteroStatus.data.active_operation_id ?? undefined)
      : undefined);
  const paperEntries = React.useMemo(
    () => papersQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [papersQuery.data?.pages],
  );
  const paperActivityIds = React.useMemo(
    () => [
      ...paperEntries.flatMap((entry) =>
        entry.entry_type === "paper" ? [entry.document.document_id] : [],
      ),
      ...paperSearchResults.map((paper) => paper.document_id),
    ],
    [paperEntries, paperSearchResults],
  );
  const paperActivityIdChunks = React.useMemo(
    () => chunkPaperSummaryDocumentIds(paperActivityIds),
    [paperActivityIds],
  );
  const paperActivityQueries = useQueries({
    queries: paperActivityIdChunks.map((documentIds) =>
      researchActivityQueries.paperSummaries(documentIds),
    ),
  });
  const paperActivitySummaries = paperActivityQueries.flatMap(
    (query) => query.data ?? [],
  );
  const paperActivityByDocumentId = React.useMemo(
    () =>
      new Map<string, PaperActivitySummary>(
        paperActivitySummaries
          .filter(hasPaperActivityEvidence)
          .map((summary) => [summary.documentId, summary]),
      ),
    [paperActivitySummaries],
  );
  const paperList = React.useMemo(() => {
    const lastPage = papersQuery.data?.pages.at(-1);
    if (!lastPage) return undefined;
    return {
      ...lastPage,
      items: paperEntries,
      previous_cursor: null,
    };
  }, [paperEntries, papersQuery.data?.pages]);
  const ingestion = usePaperIngestions(paperEntries, {
    onWillIngest: () => {
      if (parsed.cursor) replaceSearch({ cursor: undefined });
    },
  });
  const integrations = useQuery({
    ...integrationQueries.current(),
    enabled: Boolean(pendingMineruRetry),
  });
  const mineru = integrations.data?.items.find(
    (integration) => integration.provider === "mineru",
  );
  React.useEffect(() => {
    if (
      pendingMineruRetry &&
      !resumingMineruRetry.current &&
      mineru?.enabled &&
      ["connected", "connected_unverified"].includes(mineru.state)
    ) {
      const ingestionId = pendingMineruRetry;
      resumingMineruRetry.current = true;
      void runAction(() => ingestion.retry(ingestionId)).finally(() => {
        resumingMineruRetry.current = false;
        setPendingMineruRetry(undefined);
      });
    }
  }, [
    ingestion,
    mineru?.enabled,
    mineru?.state,
    pendingMineruRetry,
    runAction,
  ]);
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
  const tagAssignmentMutation = useMutation({
    mutationFn: ({
      documentIds,
      tagIds,
    }: {
      documentIds: string[];
      tagIds: string[];
    }) => replaceLibraryTagAssignments(documentIds, tagIds),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: [...libraryKeys.all, "papers"],
      });
    },
  });
  const statusMutation = useMutation({
    mutationFn: ({
      documentId,
      status,
    }: {
      documentId: string;
      status: "todo" | "reading" | "completed";
    }) => updatePaperStatus(documentId, status),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: [...libraryKeys.all, "papers"],
        }),
        queryClient.invalidateQueries({ queryKey: ["paper-search"] }),
        queryClient.invalidateQueries({ queryKey: ["projects"] }),
      ]);
    },
  });
  const createTagMutation = useMutation({
    mutationFn: createLibraryTag,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: libraryKeys.tags() });
    },
  });
  const renameTagMutation = useMutation({
    mutationFn: ({ name, tagId }: { name: string; tagId: string }) =>
      renameLibraryTag(tagId, name),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: libraryKeys.tags() }),
        queryClient.invalidateQueries({
          queryKey: [...libraryKeys.all, "papers"],
        }),
      ]);
    },
  });
  const deleteTagMutation = useMutation({
    mutationFn: deleteLibraryTag,
    onSuccess: async (_data, tagId) => {
      if (parsed.tagIds.includes(tagId)) {
        replaceSearch({
          cursor: undefined,
          tagIds: parsed.tagIds.filter((id) => id !== tagId),
        });
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: libraryKeys.tags() }),
        queryClient.invalidateQueries({
          queryKey: [...libraryKeys.all, "papers"],
        }),
      ]);
    },
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

  function handleTabChange(value: string) {
    const tab = value as LibraryTab;
    replaceSearch({
      cursor: undefined,
      kinds: tab === "outputs" ? parsed.kinds : [],
      sort: tab === "outputs" ? "updated_desc" : "added_desc",
      tab,
      tagIds: tab === "papers" ? parsed.tagIds : [],
      statuses: tab === "papers" ? parsed.statuses : [],
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
      mobileHeaderCenter={
        <span className="block truncate text-base font-semibold">
          {t("title")}
        </span>
      }
      mobileHeaderTrailing={
        <IconButton
          label={t("addPapers.open")}
          onClick={() => setAddOpen(true)}
          onFocus={() => void loadAddPapersDialog()}
          onPointerDown={() => void loadAddPapersDialog()}
          onPointerEnter={() => void loadAddPapersDialog()}
          variant="ghost"
        >
          <Icon glyph={AddIcon} size={24} />
        </IconButton>
      }
      onCollapsedChange={setCollapsed}
      onSignOut={handleSignOut}
      signingOut={signingOut}
    >
      <Tabs
        className="flex h-full min-h-0 min-w-0 flex-col"
        onValueChange={handleTabChange}
        value={parsed.tab}
      >
        <div className="w-full shrink-0 px-4 pt-5 sm:px-6 lg:px-8 lg:pt-6">
          <header className="flex min-h-11 items-center justify-between gap-6">
            <div className="flex min-w-0 items-center gap-6">
              <h1 className="hidden shrink-0 text-2xl font-semibold tracking-[-0.02em] lg:block">
                {t("title")}
              </h1>
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
            </div>
            <Button
              className="hidden lg:inline-flex"
              onClick={() => setAddOpen(true)}
              onFocus={() => void loadAddPapersDialog()}
              onPointerDown={() => void loadAddPapersDialog()}
              onPointerEnter={() => void loadAddPapersDialog()}
            >
              <Icon glyph={AddIcon} size={20} tone="inverse" />
              {t("addPapers.open")}
            </Button>
          </header>
          {zoteroOperationId ? (
            <ZoteroOperationStatus
              initialOperation={zoteroOperation}
              operationId={zoteroOperationId}
              onComplete={() => {
                void Promise.all([
                  queryClient.invalidateQueries({
                    queryKey: [...libraryKeys.all, "papers"],
                  }),
                  queryClient.invalidateQueries({
                    queryKey: libraryKeys.summary(),
                  }),
                  queryClient.invalidateQueries({
                    queryKey: zoteroKeys.status(),
                  }),
                ]);
              }}
              onDismiss={() => setZoteroOperation(undefined)}
            />
          ) : null}
        </div>
        <PaperCollectionSidePanelLayout>
          <div className="flex h-full min-h-0 w-full min-w-0 flex-col px-4 sm:px-6 lg:px-8">
            <TabsContent
              className="mt-4 min-h-0 flex-1 overflow-hidden"
              value="papers"
            >
              <PapersView
                activityByDocumentId={paperActivityByDocumentId}
                attentionCount={summaryQuery.data?.attention_count ?? 0}
                data={paperList}
                error={papersQuery.error}
                ingestions={ingestion.rows}
                ingestionCount={summaryQuery.data?.ingestion_count ?? 0}
                loading={papersQuery.isPending}
                loadingMore={papersQuery.isFetchingNextPage}
                hasMore={papersQuery.hasNextPage}
                onCreateTag={(name) => createTagMutation.mutateAsync(name)}
                onDeleteTag={(tagId) => deleteTagMutation.mutateAsync(tagId)}
                onRenameTag={(tagId, name) =>
                  renameTagMutation.mutateAsync({ name, tagId })
                }
                onReplaceTags={(documentIds, tagIds) =>
                  tagAssignmentMutation
                    .mutateAsync({ documentIds, tagIds })
                    .then(() => undefined)
                }
                onDownload={(documentId) => void handleDownload(documentId)}
                onCancelIngestion={(id) =>
                  void runAction(() => ingestion.cancel(id))
                }
                onLoadMore={() =>
                  papersQuery.fetchNextPage().then(() => undefined)
                }
                onNeedTags={() => setTagsRequested(true)}
                onRemove={(documentIds) =>
                  runAction(() => removeMutation.mutateAsync(documentIds))
                }
                onRetryIngestion={(id) =>
                  (() => {
                    const row = ingestion.rows.find((item) => item.id === id);
                    if (row?.requiredIntegration === "mineru") {
                      setPendingMineruRetry(id);
                      openSettingsSection("connections");
                      return;
                    }
                    void runAction(() => ingestion.retry(id));
                  })()
                }
                onRetryLoad={() => void papersQuery.refetch()}
                onSortChange={(sort: PaperSort) =>
                  replaceSearch({ cursor: undefined, sort })
                }
                onStatusChange={(documentId, status) =>
                  statusMutation.mutate({ documentId, status })
                }
                onStatusFilterChange={(statuses) =>
                  replaceSearch({ cursor: undefined, statuses })
                }
                onTagFilterChange={(tagIds) =>
                  replaceSearch({ cursor: undefined, tagIds })
                }
                search={
                  <PaperSearchForm
                    committedQuery={parsed.query}
                    draft={paperSearchDraft}
                    label={t("papers.search")}
                    onCommit={(query) =>
                      replaceSearch({ cursor: undefined, query })
                    }
                    onDraftChange={setPaperSearchDraft}
                  />
                }
                searchTotal={paperSearchQuery.data?.pages[0]?.total}
                searchWorkbench={paperSearchWorkbench}
                paperCount={summaryQuery.data?.paper_count ?? 0}
                resultSetKey={`${parsed.tab}:${parsed.query}:${parsed.sort}:${parsed.statuses.join(",")}:${parsed.tagIds.join(",")}`}
                sort={parsed.sort as PaperSort}
                tagIds={parsed.tagIds}
                statuses={parsed.statuses}
                tags={tagsQuery.data?.items ?? []}
                tagsLoading={tagsQuery.isPending && tagsRequested}
              />
            </TabsContent>
            <TabsContent
              className={`mt-4 min-h-0 flex-1 overflow-y-auto pb-12 ${focusSurfaceVariants({ intent: "scroll" })}`}
              value="outputs"
            >
              <OutputsView
                data={outputsQuery.data}
                error={outputsQuery.error}
                kinds={parsed.kinds}
                loading={outputsQuery.isPending}
                onKindFilterChange={(kinds) =>
                  replaceSearch({ cursor: undefined, kinds })
                }
                onNext={(cursor) => replaceSearch({ cursor })}
                onPrevious={(cursor) => replaceSearch({ cursor })}
                onRetryLoad={() => void outputsQuery.refetch()}
                onSortChange={(sort: OutputSort) =>
                  replaceSearch({ cursor: undefined, sort })
                }
                search={
                  <DebouncedLibrarySearch
                    key={`outputs:${parsed.query}`}
                    label={t("outputs.search")}
                    onQueryChange={(query) =>
                      replaceSearch({ cursor: undefined, query })
                    }
                    value={parsed.query}
                  />
                }
                sort={parsed.sort as OutputSort}
              />
            </TabsContent>
          </div>
        </PaperCollectionSidePanelLayout>
      </Tabs>

      <AddPapersDialog
        onConnectOpenAlex={() => openSettingsSection("connections")}
        onBrowseZotero={() => setZoteroOpen(true)}
        onOpenChange={setAddOpen}
        onSubmitSource={ingestion.submitSource}
        onUploadFiles={ingestion.startUploads}
        open={addOpen}
      />
      <ZoteroLibraryDialog
        onImportAccepted={setZoteroOperation}
        onOpenChange={setZoteroOpen}
        open={zoteroOpen}
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
