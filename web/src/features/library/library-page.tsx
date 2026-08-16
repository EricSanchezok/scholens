"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AddIcon } from "@/design-system/icons/semantic-icons";
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
import { integrationQueries } from "@/features/integrations";
import { useSettingsNavigation } from "@/features/settings";
import { WorkspaceShell } from "@/features/workspace-shell";
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
import { AddPapersDialog } from "./components/add-papers-dialog";
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
      className="bg-subtle hover:border-line rounded-full border-transparent"
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
  const { setSection: setSettingsSection } = useSettingsNavigation();
  const parsed = React.useMemo(
    () => parseLibrarySearch(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const [collapsed, setCollapsed] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const [addOpen, setAddOpen] = React.useState(false);
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
  const papersQuery = useQuery({
    ...libraryQueries.papers({
      cursor: parsed.cursor,
      query: parsed.query,
      sort: parsed.sort,
      tagIds: parsed.tagIds,
    }),
    enabled: parsed.tab === "papers",
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
  const paperEntries = React.useMemo(
    () => papersQuery.data?.items ?? [],
    [papersQuery.data?.items],
  );
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
          <Icon glyph={AddIcon} size={24} />
        </IconButton>
      }
      onCollapsedChange={setCollapsed}
      onSignOut={handleSignOut}
      signingOut={signingOut}
    >
      <div className="mx-auto w-full max-w-6xl min-w-0 px-4 pt-5 pb-12 sm:px-6 lg:px-10 lg:pt-6">
        <Tabs
          className="min-w-0"
          onValueChange={handleTabChange}
          value={parsed.tab}
        >
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
            >
              <Icon glyph={AddIcon} size={20} tone="inverse" />
              {t("addPapers.open")}
            </Button>
          </header>
          <TabsContent className="mt-4 grid min-w-0 gap-4" value="papers">
            <PapersView
              attentionCount={summaryQuery.data?.attention_count ?? 0}
              key={`${parsed.query}:${parsed.sort}:${parsed.cursor ?? ""}:${parsed.tagIds.join(",")}`}
              data={papersQuery.data}
              error={papersQuery.error}
              ingestions={ingestion.rows}
              ingestionCount={summaryQuery.data?.ingestion_count ?? 0}
              loading={papersQuery.isPending}
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
              onNext={(cursor) => replaceSearch({ cursor })}
              onOpenDocument={(documentId) =>
                router.push(`/reader/${documentId}` as Route)
              }
              onPrevious={(cursor) => replaceSearch({ cursor })}
              onRemove={(documentIds) =>
                runAction(() => removeMutation.mutateAsync(documentIds))
              }
              onRetryIngestion={(id) =>
                (() => {
                  const row = ingestion.rows.find((item) => item.id === id);
                  if (row?.requiredIntegration === "mineru") {
                    setPendingMineruRetry(id);
                    setSettingsSection("connections");
                    return;
                  }
                  void runAction(() => ingestion.retry(id));
                })()
              }
              onRetryLoad={() => void papersQuery.refetch()}
              onSortChange={(sort: PaperSort) =>
                replaceSearch({ cursor: undefined, sort })
              }
              onTagFilterChange={(tagIds) =>
                replaceSearch({ cursor: undefined, tagIds })
              }
              search={
                <DebouncedLibrarySearch
                  key={`papers:${parsed.query}`}
                  label={t("papers.search")}
                  onQueryChange={(query) =>
                    replaceSearch({ cursor: undefined, query })
                  }
                  value={parsed.query}
                />
              }
              paperCount={summaryQuery.data?.paper_count ?? 0}
              sort={parsed.sort as PaperSort}
              tagIds={parsed.tagIds}
              tags={tagsQuery.data?.items ?? []}
            />
          </TabsContent>
          <TabsContent className="mt-4 grid min-w-0 gap-4" value="outputs">
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
        </Tabs>
      </div>

      <AddPapersDialog
        onConnectOpenAlex={() => setSettingsSection("connections")}
        onOpenChange={setAddOpen}
        onSubmitSource={ingestion.submitSource}
        onUploadFiles={ingestion.startUploads}
        open={addOpen}
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
