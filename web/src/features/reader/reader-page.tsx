"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, List, Search } from "iconoir-react";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import {
  Button,
  IconButton,
  SearchField,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { useAuthSession, type Actor } from "@/features/authentication";
import { conversationQueries } from "@/features/conversation";
import { WorkspaceShell } from "@/features/workspace-shell";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import { getReaderDownloadUrl, readerQueries } from "./api/queries";
import { PdfPage, type ReaderFitMode } from "./components/pdf-page";
import { PdfThumbnail } from "./components/pdf-thumbnail";
import {
  ReaderToolbar,
  type ReaderToolbarLabels,
} from "./components/reader-toolbar";
import {
  PdfDocumentAdapter,
  type PdfOutlineEntry,
} from "./pdf-document-adapter";
import {
  flattenReaderSearchResults,
  moveReaderSearchCursor,
} from "./reader-search";

type ReaderPanel = "ask" | "annotations" | "details" | "outline" | "search";
type ReaderDocument = components["schemas"]["DocumentResponse"];

function parsePositiveInteger(value: string | null, fallback = 1) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : fallback;
}

function readPanel(value: string | null): ReaderPanel | undefined {
  return value === "ask" ||
    value === "annotations" ||
    value === "details" ||
    value === "outline" ||
    value === "search"
    ? value
    : undefined;
}

function ReaderOutline({
  entries,
  onSelect,
}: {
  entries: PdfOutlineEntry[];
  onSelect: (destination: unknown) => void;
}) {
  return (
    <ul className="grid gap-0.5">
      {entries.map((entry, index) => (
        <li key={`${entry.title}:${index}`}>
          <button
            className="hover:bg-hover w-full rounded-[var(--radius-md)] px-2 py-2 text-left text-sm"
            onClick={() => onSelect(entry.destination)}
            type="button"
          >
            {entry.title}
          </button>
          {entry.children.length > 0 && (
            <div className="border-line ml-3 border-l pl-2">
              <ReaderOutline entries={entry.children} onSelect={onSelect} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function ReaderDocumentWorkspace({
  actor,
  documentId,
}: {
  actor: Actor;
  documentId: string;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useTranslations("Reader");
  const { signOut } = useAuthSession();
  const [collapsed, setCollapsed] = React.useState(true);
  const [signingOut, setSigningOut] = React.useState(false);
  const [adapterState, setAdapterState] = React.useState<{
    adapter: PdfDocumentAdapter;
    documentId: string;
  }>();
  const [adapterErrorState, setAdapterErrorState] = React.useState<{
    documentId: string;
    error: unknown;
  }>();
  const [pageCount, setPageCount] = React.useState(1);
  const [fitMode, setFitMode] = React.useState<ReaderFitMode>("width");
  const [zoom, setZoom] = React.useState(1);
  const [outline, setOutline] = React.useState<PdfOutlineEntry[]>([]);
  const [searchQuery, setSearchQuery] = React.useState("");
  const [searchState, setSearchState] = React.useState<{
    query: string;
    results: Awaited<ReturnType<PdfDocumentAdapter["search"]>>;
  }>();
  const [searchIndex, setSearchIndex] = React.useState(-1);
  const documentQuery = useQuery(readerQueries.document(documentId));
  const conversationsQuery = useQuery(
    conversationQueries.list({ scopeId: documentId, scopeType: "paper" }),
  );

  const rawPage = parsePositiveInteger(searchParams.get("page"));
  const pageNumber = Math.min(rawPage, pageCount);
  const panel = readPanel(searchParams.get("panel"));
  const conversationId = searchParams.get("conversation") ?? undefined;
  const adapter =
    adapterState?.documentId === documentId ? adapterState.adapter : undefined;
  const adapterError =
    adapterErrorState?.documentId === documentId
      ? adapterErrorState.error
      : undefined;

  const updateLocation = React.useCallback(
    (patch: {
      page?: number;
      panel?: ReaderPanel | null;
      conversation?: string | null;
    }) => {
      const next = new URLSearchParams(searchParams.toString());
      if (patch.page !== undefined) next.set("page", String(patch.page));
      if (patch.panel === null) next.delete("panel");
      else if (patch.panel) next.set("panel", patch.panel);
      if (patch.conversation === null) next.delete("conversation");
      else if (patch.conversation) next.set("conversation", patch.conversation);
      const query = next.toString();
      router.replace(
        `/reader/${documentId}${query ? `?${query}` : ""}` as Route,
        { scroll: false },
      );
    },
    [documentId, router, searchParams],
  );

  const refreshFileUrl = React.useCallback(
    () => getReaderDownloadUrl(documentId),
    [documentId],
  );

  React.useEffect(() => {
    if (documentQuery.data?.processing_status !== "completed") return;
    let active = true;
    let opened: PdfDocumentAdapter | undefined;
    void PdfDocumentAdapter.open(refreshFileUrl)
      .then(async (nextAdapter) => {
        opened = nextAdapter;
        if (!active) {
          await nextAdapter.destroy();
          return;
        }
        setAdapterState({ adapter: nextAdapter, documentId });
        setPageCount(nextAdapter.pageCount);
        setOutline(await nextAdapter.getOutline());
      })
      .catch((error: unknown) => {
        if (active) setAdapterErrorState({ documentId, error });
      });
    return () => {
      active = false;
      void opened?.destroy();
    };
  }, [documentId, documentQuery.data?.processing_status, refreshFileUrl]);

  React.useEffect(() => {
    if (!adapter || !searchQuery.trim()) return;
    let active = true;
    const timer = window.setTimeout(() => {
      void adapter.search(searchQuery).then((results) => {
        if (!active) return;
        setSearchState({ query: searchQuery, results });
        setSearchIndex(results.length > 0 ? 0 : -1);
      });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [adapter, searchQuery]);

  const flatSearchResults = React.useMemo(
    () =>
      flattenReaderSearchResults(
        searchState?.query === searchQuery ? searchState.results : [],
      ),
    [searchQuery, searchState],
  );

  React.useEffect(() => {
    const activeMatch = flatSearchResults[searchIndex];
    if (activeMatch && activeMatch.pageNumber !== pageNumber) {
      updateLocation({ page: activeMatch.pageNumber });
    }
  }, [flatSearchResults, pageNumber, searchIndex, updateLocation]);

  const resolveDestination = React.useCallback(
    async (destination: unknown) => {
      const target = await adapter?.resolveDestination(destination);
      if (target) updateLocation({ page: target, panel: null });
    },
    [adapter, updateLocation],
  );

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await signOut();
      router.replace("/login");
    } finally {
      setSigningOut(false);
    }
  }

  async function handleDownload() {
    window.open(await refreshFileUrl(), "_blank", "noopener,noreferrer");
  }

  const toolbarLabels = React.useMemo<ReaderToolbarLabels>(
    () => ({
      download: t("toolbar.download"),
      fit: t("toolbar.fit"),
      fitPage: t("toolbar.fitPage"),
      fitWidth: t("toolbar.fitWidth"),
      nextPage: t("toolbar.nextPage"),
      openPanel: t("toolbar.openPanel"),
      outline: t("toolbar.outline"),
      page: t("toolbar.page"),
      previousPage: t("toolbar.previousPage"),
      search: t("toolbar.search"),
      zoomIn: t("toolbar.zoomIn"),
      zoomOut: t("toolbar.zoomOut"),
    }),
    [t],
  );

  const document = documentQuery.data;
  const title = document?.title ?? document?.original_filename ?? t("untitled");
  const desktopPanelOpen =
    panel === "ask" || panel === "annotations" || panel === "details";

  return (
    <WorkspaceShell
      activeConversationId={conversationId}
      activeDestination="library"
      actor={actor}
      collapsed={collapsed}
      conversations={conversationsQuery.data?.items ?? []}
      mobileHeaderCenter={
        <span className="block truncate text-sm font-medium">{title}</span>
      }
      mobileHeaderLeading={
        <IconButton
          label={t("returnLibrary")}
          onClick={() => router.push("/library")}
          variant="ghost"
        >
          <Icon glyph={ArrowLeft} size={24} />
        </IconButton>
      }
      onCollapsedChange={setCollapsed}
      onSignOut={handleSignOut}
      showMobileBottomNavigation={false}
      signingOut={signingOut}
    >
      <div className="flex h-full min-h-0 flex-col overflow-hidden">
        <div className="border-line bg-canvas hidden h-14 shrink-0 items-center justify-between gap-4 border-b px-4 lg:flex">
          <button
            className="min-w-0 text-left"
            onClick={() => router.push("/library")}
            type="button"
          >
            <span className="text-muted block text-xs">{t("library")}</span>
            <span className="block max-w-[50vw] truncate text-sm font-medium">
              {title}
            </span>
          </button>
          <Button
            onClick={() => updateLocation({ panel: "ask" })}
            size="sm"
            variant="secondary"
          >
            {t("panels.ask")}
          </Button>
        </div>

        {documentQuery.isPending && (
          <div className="m-auto w-full max-w-sm p-6">
            <LoadingState label={t("loadingDocument")} />
          </div>
        )}
        {documentQuery.error && (
          <div className="m-auto w-full max-w-md p-6">
            <AsyncFeedback
              action={{
                label: t("tryAgain"),
                onClick: () => void documentQuery.refetch(),
              }}
              description={t("documentErrorDescription")}
              state="error"
              title={t("documentErrorTitle")}
            />
          </div>
        )}
        {document?.processing_status === "failed" && (
          <div className="m-auto w-full max-w-md p-6">
            <AsyncFeedback
              description={t("failedDescription")}
              state="error"
              title={t("failedTitle")}
            />
          </div>
        )}
        {(document?.processing_status === "pending" ||
          document?.processing_status === "processing") && (
          <div className="m-auto w-full max-w-md p-6">
            <AsyncFeedback
              description={t("processingDescription")}
              state="loading"
              title={t("processingTitle")}
            />
          </div>
        )}
        {document?.processing_status === "completed" &&
          !adapter &&
          !adapterError && (
            <div className="m-auto w-full max-w-sm p-6">
              <LoadingState label={t("loadingPdf")} />
            </div>
          )}
        {adapterError !== undefined && (
          <div className="m-auto w-full max-w-md p-6">
            <AsyncFeedback
              action={{
                label: t("downloadInstead"),
                onClick: () => void handleDownload(),
              }}
              description={t("pdfErrorDescription")}
              state="error"
              title={t("pdfErrorTitle")}
            />
          </div>
        )}

        {adapter && (
          <div className="flex min-h-0 flex-1 flex-col">
            <ReaderToolbar
              fitMode={fitMode}
              labels={toolbarLabels}
              onDownload={() => void handleDownload()}
              onFitModeChange={setFitMode}
              onOpenOutline={() => updateLocation({ panel: "outline" })}
              onOpenPanel={() =>
                updateLocation({ panel: desktopPanelOpen ? null : "ask" })
              }
              onOpenSearch={() => updateLocation({ panel: "search" })}
              onPageChange={(page) =>
                updateLocation({ page: Math.min(Math.max(page, 1), pageCount) })
              }
              onZoomChange={(nextZoom) => {
                setZoom(nextZoom);
                setFitMode("custom");
              }}
              pageCount={pageCount}
              pageNumber={pageNumber}
              panelOpen={desktopPanelOpen}
              zoom={zoom}
            />
            <div className="flex min-h-0 flex-1">
              <aside className="border-line bg-canvas hidden w-28 shrink-0 overflow-y-auto border-r p-2 md:block">
                <div className="grid gap-1">
                  {Array.from(
                    { length: pageCount },
                    (_, index) => index + 1,
                  ).map((number) => (
                    <PdfThumbnail
                      adapter={adapter}
                      current={pageNumber === number}
                      key={number}
                      label={t("thumbnail", { page: number })}
                      onSelect={() => updateLocation({ page: number })}
                      pageNumber={number}
                    />
                  ))}
                </div>
              </aside>
              <PdfPage
                adapter={adapter}
                fitMode={fitMode}
                loadingLabel={t("renderingPage")}
                onInternalDestination={(destination) =>
                  void resolveDestination(destination)
                }
                pageNumber={pageNumber}
                searchQuery={searchQuery}
                zoom={zoom}
              />
              {desktopPanelOpen && (
                <ReaderContextPanel
                  className="hidden lg:flex"
                  document={document}
                  onClose={() => updateLocation({ panel: null })}
                  onPanelChange={(nextPanel) =>
                    updateLocation({ panel: nextPanel })
                  }
                  panel={panel ?? "ask"}
                  title={title}
                />
              )}
            </div>
          </div>
        )}
      </div>

      <Sheet
        onOpenChange={(open) => {
          if (!open) updateLocation({ panel: null });
        }}
        open={panel === "search" || panel === "outline"}
      >
        <SheetContent
          className="inset-x-0 top-auto bottom-0 h-[min(82dvh,42rem)] w-full max-w-none rounded-t-[var(--radius-xl)] border-x-0 border-t p-0 lg:inset-y-0 lg:right-0 lg:left-auto lg:h-full lg:w-[26rem] lg:rounded-none lg:border-t-0 lg:border-l"
          closeLabel={t("closePanel")}
        >
          {panel === "search" ? (
            <ReaderSearchPanel
              currentIndex={searchIndex}
              labels={{
                empty: t("search.empty"),
                next: t("search.next"),
                previous: t("search.previous"),
                results: t("search.results", {
                  count: flatSearchResults.length,
                }),
                title: t("search.title"),
              }}
              matchCount={flatSearchResults.length}
              onMove={(direction) =>
                setSearchIndex((current) =>
                  moveReaderSearchCursor(
                    current,
                    flatSearchResults.length,
                    direction,
                  ),
                )
              }
              onQueryChange={(query) => {
                setSearchQuery(query);
                setSearchIndex(-1);
              }}
              query={searchQuery}
            />
          ) : (
            <div className="flex h-full flex-col p-5">
              <SheetTitle className="pr-12 text-lg font-semibold">
                {t("outline.title")}
              </SheetTitle>
              <SheetDescription className="text-muted mt-1 text-sm">
                {t("outline.description")}
              </SheetDescription>
              <div className="mt-5 min-h-0 flex-1 overflow-y-auto">
                {outline.length > 0 ? (
                  <ReaderOutline
                    entries={outline}
                    onSelect={(destination) =>
                      void resolveDestination(destination)
                    }
                  />
                ) : (
                  <p className="text-muted py-12 text-center text-sm">
                    {t("outline.empty")}
                  </p>
                )}
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>

      <Sheet
        onOpenChange={(open) => {
          if (!open) updateLocation({ panel: null });
        }}
        open={panel === "ask" || panel === "annotations" || panel === "details"}
      >
        <SheetContent
          className="inset-x-0 top-auto bottom-0 h-[min(90dvh,48rem)] w-full max-w-none rounded-t-[var(--radius-xl)] border-x-0 border-t p-0 lg:hidden"
          closeLabel={t("closePanel")}
        >
          <ReaderContextPanel
            document={document}
            onClose={() => updateLocation({ panel: null })}
            onPanelChange={(nextPanel) => updateLocation({ panel: nextPanel })}
            panel={panel ?? "ask"}
            title={title}
          />
        </SheetContent>
      </Sheet>
    </WorkspaceShell>
  );
}

function ReaderSearchPanel({
  currentIndex,
  labels,
  matchCount,
  onMove,
  onQueryChange,
  query,
}: {
  currentIndex: number;
  labels: {
    empty: string;
    next: string;
    previous: string;
    results: string;
    title: string;
  };
  matchCount: number;
  onMove: (direction: -1 | 1) => void;
  onQueryChange: (query: string) => void;
  query: string;
}) {
  return (
    <div className="flex h-full flex-col p-5">
      <SheetTitle className="pr-12 text-lg font-semibold">
        {labels.title}
      </SheetTitle>
      <SheetDescription className="sr-only">{labels.title}</SheetDescription>
      <SearchField
        autoFocus
        className="mt-5"
        onChange={(event) => onQueryChange(event.currentTarget.value)}
        placeholder={labels.title}
        value={query}
      />
      <div className="mt-3 flex items-center justify-between gap-3">
        <p aria-live="polite" className="text-muted text-sm">
          {query.trim() && matchCount === 0 ? labels.empty : labels.results}
        </p>
        <div className="flex gap-1">
          <IconButton
            disabled={matchCount === 0}
            label={labels.previous}
            onClick={() => onMove(-1)}
            variant="ghost"
          >
            <Icon glyph={ArrowLeft} size={20} />
          </IconButton>
          <IconButton
            disabled={matchCount === 0}
            label={labels.next}
            onClick={() => onMove(1)}
            variant="ghost"
          >
            <Icon className="rotate-180" glyph={ArrowLeft} size={20} />
          </IconButton>
        </div>
      </div>
      {matchCount > 0 && (
        <p className="text-secondary mt-8 text-center text-sm tabular-nums">
          {currentIndex + 1} / {matchCount}
        </p>
      )}
    </div>
  );
}

function ReaderContextPanel({
  className,
  document,
  onClose,
  onPanelChange,
  panel,
  title,
}: {
  className?: string;
  document: ReaderDocument | undefined;
  onClose: () => void;
  onPanelChange: (panel: "ask" | "annotations" | "details") => void;
  panel: ReaderPanel;
  title: string;
}) {
  const t = useTranslations("Reader");
  const activePanel =
    panel === "annotations" || panel === "details" ? panel : "ask";
  return (
    <aside
      className={cn(
        "border-line bg-canvas w-full shrink-0 flex-col border-l lg:w-[23rem]",
        className ?? "flex",
      )}
    >
      <div className="border-line flex h-14 items-center gap-1 border-b px-3">
        {(["ask", "annotations", "details"] as const).map((item) => (
          <Button
            className="h-9 min-h-9 px-2"
            key={item}
            onClick={() => onPanelChange(item)}
            size="sm"
            variant={activePanel === item ? "secondary" : "ghost"}
          >
            {t(`panels.${item}`)}
          </Button>
        ))}
        <IconButton
          className="ml-auto lg:hidden"
          label={t("closePanel")}
          onClick={onClose}
          variant="ghost"
        >
          <Icon glyph={ArrowLeft} size={20} />
        </IconButton>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {activePanel === "details" ? (
          <dl className="grid gap-5 text-sm">
            <div>
              <dt className="text-muted">{t("details.title")}</dt>
              <dd className="mt-1 font-medium">{title}</dd>
            </div>
            <div>
              <dt className="text-muted">{t("details.authors")}</dt>
              <dd className="mt-1">
                {document?.authors?.join(", ") || t("details.unknown")}
              </dd>
            </div>
            <div>
              <dt className="text-muted">{t("details.abstract")}</dt>
              <dd className="mt-1 leading-6">
                {document?.abstract || t("details.unknown")}
              </dd>
            </div>
            <div>
              <dt className="text-muted">{t("details.doi")}</dt>
              <dd className="mt-1">{document?.doi || t("details.unknown")}</dd>
            </div>
            <div>
              <dt className="text-muted">{t("details.file")}</dt>
              <dd className="mt-1">{document?.original_filename}</dd>
            </div>
          </dl>
        ) : (
          <div className="grid min-h-48 place-items-center text-center">
            <div>
              <Icon
                glyph={activePanel === "ask" ? Search : List}
                size={24}
                tone="secondary"
              />
              <h2 className="mt-3 text-sm font-medium">
                {t(`phaseFour.${activePanel}.title`)}
              </h2>
              <p className="text-muted mt-1 max-w-64 text-sm">
                {t(`phaseFour.${activePanel}.description`)}
              </p>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

export function ReaderPage({ documentId }: { documentId: string }) {
  const router = useRouter();
  const t = useTranslations("Reader.session");
  const session = useAuthSession();

  React.useEffect(() => {
    if (session.status === "anonymous") {
      const returnTo = `/reader/${documentId}`;
      router.replace(`/login?returnTo=${encodeURIComponent(returnTo)}`);
    }
  }, [documentId, router, session.status]);

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
    <ReaderDocumentWorkspace actor={session.actor} documentId={documentId} />
  );
}
