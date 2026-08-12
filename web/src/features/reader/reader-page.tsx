"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "iconoir-react";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import {
  IconButton,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  useToast,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { useAuthSession, type Actor } from "@/features/authentication";
import {
  conversationKeys,
  conversationQueries,
  useConversationSession,
  type ReasoningLevel,
} from "@/features/conversation";
import { WorkspaceShell } from "@/features/workspace-shell";
import {
  createReaderComment,
  createReaderHighlight,
  deleteReaderComment,
  deleteReaderHighlight,
  getReaderDownloadUrl,
  readerKeys,
  readerQueries,
  setReaderConversationPinned,
  updateReaderComment,
  updateReaderHighlight,
} from "./api/queries";
import {
  PdfPage,
  type ReaderFitMode,
  type ReaderSelection,
} from "./components/pdf-page";
import { PdfThumbnail } from "./components/pdf-thumbnail";
import {
  useDesktopReaderPanel,
  useDocumentNavigationRail,
} from "./hooks/use-reader-layout";
import { ReaderContextPanel } from "./components/reader-context-panel";
import {
  ReaderDocumentNavigation,
  ReaderOutline,
} from "./components/reader-document-navigation";
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
import {
  parsePositiveInteger,
  readReaderPanel,
  readSourcePage,
} from "./reader-routing";
import type {
  ReaderContextPanel as ReaderContextPanelName,
  ReaderNavigationMode,
} from "./reader-types";

function ReaderDocumentWorkspace({
  actor,
  documentId,
}: {
  actor: Actor;
  documentId: string;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const t = useTranslations("Reader");
  const toast = useToast();
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
  const [navigationMode, setNavigationMode] =
    React.useState<ReaderNavigationMode>("thumbnails");
  const [mobileOutlineOpen, setMobileOutlineOpen] = React.useState(false);
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState("");
  const [searchState, setSearchState] = React.useState<{
    query: string;
    results: Awaited<ReturnType<PdfDocumentAdapter["search"]>>;
  }>();
  const [searchIndex, setSearchIndex] = React.useState(-1);
  const [activeTextSelection, setActiveTextSelection] =
    React.useState<ReaderSelection>();
  const [pendingTurnContext, setPendingTurnContext] =
    React.useState<ReaderSelection>();
  const [annotationSelection, setAnnotationSelection] =
    React.useState<ReaderSelection>();
  const [selectedAnnotationId, setSelectedAnnotationId] =
    React.useState<string>();
  const lastContextPanelRef = React.useRef<"ask" | "annotations" | "details">(
    "ask",
  );
  const [reasoningLevel, setReasoningLevel] =
    React.useState<ReasoningLevel>("standard");
  const documentQuery = useQuery(readerQueries.document(documentId));
  const annotationsQuery = useQuery(readerQueries.annotations(documentId));
  const conversationsQuery = useQuery(
    conversationQueries.list({ scopeId: documentId, scopeType: "paper" }),
  );

  const rawPage = parsePositiveInteger(searchParams.get("page"));
  const pageNumber = Math.min(rawPage, pageCount);
  const panel = readReaderPanel(searchParams.get("panel"));
  const conversationId = searchParams.get("conversation") ?? undefined;
  const selectedAnnotation = annotationsQuery.data?.items.find(
    (item) => item.id === selectedAnnotationId,
  );
  const updateLocation = React.useCallback(
    (patch: {
      page?: number;
      panel?: ReaderContextPanelName | null;
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
  const conversationSession = useConversationSession({
    context: {
      kind: "selection",
      document_ids: [documentId],
      project_ids: [],
    },
    conversationId,
    getTurnContexts: () => {
      if (pendingTurnContext) {
        return [{ ...pendingTurnContext, document_id: documentId }];
      }
      if (selectedAnnotationId) {
        return [{ kind: "highlight_thread", thread_id: selectedAnnotationId }];
      }
      return undefined;
    },
    onConversationCreated: (nextConversationId) =>
      updateLocation({ conversation: nextConversationId, panel: "ask" }),
    onTurnStarted: () => {
      setPendingTurnContext(undefined);
      setSelectedAnnotationId(undefined);
    },
    reasoningLevel,
    scopeId: documentId,
    scopeType: "paper",
  });
  const adapter =
    adapterState?.documentId === documentId ? adapterState.adapter : undefined;
  const adapterError =
    adapterErrorState?.documentId === documentId
      ? adapterErrorState.error
      : undefined;

  async function refreshAnnotations() {
    await queryClient.invalidateQueries({
      queryKey: readerKeys.annotations(documentId),
    });
  }

  async function createHighlight(
    targetSelection: ReaderSelection | undefined,
    color = "yellow",
    comment?: string,
  ) {
    if (!targetSelection) return;
    const item = await createReaderHighlight(documentId, {
      color,
      position: targetSelection.anchor,
      quote_text: targetSelection.selected_text,
      shared: false,
    });
    if (comment?.trim()) await createReaderComment(item.id, comment.trim());
    await refreshAnnotations();
    setSelectedAnnotationId(item.id);
    setActiveTextSelection(undefined);
    setAnnotationSelection(undefined);
    window.getSelection()?.removeAllRanges();
  }

  const handleActiveTextSelectionChange = React.useCallback(
    (nextSelection: ReaderSelection | undefined) => {
      setSelectedAnnotationId(undefined);
      setActiveTextSelection(
        nextSelection
          ? { ...nextSelection, document_id: documentId }
          : undefined,
      );
    },
    [documentId],
  );

  function notifyActionError() {
    toast.notify({
      description: t("actions.failedDescription"),
      title: t("actions.failedTitle"),
    });
  }

  async function openAnnotation(annotationId: string) {
    setSelectedAnnotationId(annotationId);
    const annotation = annotationsQuery.data?.items.find(
      (item) => item.id === annotationId,
    );
    const position = annotation?.highlight_thread?.position;
    if (position?.page_number)
      updateLocation({ page: position.page_number, panel: "annotations" });
    else updateLocation({ panel: "annotations" });
  }

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
      if (target) updateLocation({ page: target });
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
    try {
      window.open(await refreshFileUrl(), "_blank", "noopener,noreferrer");
    } catch {
      notifyActionError();
    }
  }

  const toolbarLabels = React.useMemo<ReaderToolbarLabels>(
    () => ({
      download: t("toolbar.download"),
      closeSearch: t("search.close"),
      fit: t("toolbar.fit"),
      fitPage: t("toolbar.fitPage"),
      fitWidth: t("toolbar.fitWidth"),
      nextPage: t("toolbar.nextPage"),
      nextSearchResult: t("search.next"),
      noSearchResults: t("search.empty"),
      openPanel: t("toolbar.openPanel"),
      outline: t("toolbar.outline"),
      page: t("toolbar.page"),
      previousPage: t("toolbar.previousPage"),
      previousSearchResult: t("search.previous"),
      returnLibrary: t("returnLibrary"),
      search: t("toolbar.search"),
      zoomIn: t("toolbar.zoomIn"),
      zoomOut: t("toolbar.zoomOut"),
    }),
    [t],
  );

  const document = documentQuery.data;
  const title = document?.title ?? document?.original_filename ?? t("untitled");
  const documentMetadata = [
    document?.authors?.[0],
    document?.doi ?? document?.original_filename,
  ]
    .filter(Boolean)
    .join(" · ");
  const desktopPanelOpen =
    panel === "ask" || panel === "annotations" || panel === "details";
  const useDesktopPanel = useDesktopReaderPanel();
  const showDocumentNavigation = useDocumentNavigationRail();

  const closeSearch = React.useCallback(() => {
    setSearchOpen(false);
    setSearchQuery("");
    setSearchState(undefined);
    setSearchIndex(-1);
  }, []);

  React.useEffect(() => {
    const rawPanel = searchParams.get("panel");
    if (rawPanel && !panel) updateLocation({ panel: null });
  }, [panel, searchParams, updateLocation]);

  React.useEffect(() => {
    if (panel === "ask" || panel === "annotations" || panel === "details") {
      lastContextPanelRef.current = panel;
    }
  }, [panel]);

  return (
    <WorkspaceShell
      activeConversationId={conversationId}
      activeDestination="library"
      actor={actor}
      collapsed={collapsed}
      conversations={conversationsQuery.data?.items ?? []}
      conversationHref={(id) =>
        `/reader/${documentId}?panel=ask&conversation=${id}`
      }
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
          <div className="flex min-h-0 flex-1">
            <section className="flex min-w-0 flex-1 flex-col">
              <ReaderToolbar
                fitMode={fitMode}
                labels={toolbarLabels}
                metadata={documentMetadata}
                onDownload={() => void handleDownload()}
                onFitModeChange={setFitMode}
                onOpenOutline={() => {
                  if (showDocumentNavigation) setNavigationMode("outline");
                  else setMobileOutlineOpen(true);
                }}
                onOpenPanel={() =>
                  updateLocation({ panel: lastContextPanelRef.current })
                }
                onOpenSearch={() => setSearchOpen(true)}
                onPageChange={(page) => {
                  setActiveTextSelection(undefined);
                  updateLocation({
                    page: Math.min(Math.max(page, 1), pageCount),
                  });
                }}
                onReturn={() => router.push("/library")}
                onZoomChange={(nextZoom) => {
                  setZoom(nextZoom);
                  setFitMode("custom");
                }}
                pageCount={pageCount}
                pageNumber={pageNumber}
                panelOpen={desktopPanelOpen}
                search={
                  searchOpen
                    ? {
                        currentIndex: searchIndex,
                        matchCount: flatSearchResults.length,
                        onClose: closeSearch,
                        onMove: (direction) =>
                          setSearchIndex((current) =>
                            moveReaderSearchCursor(
                              current,
                              flatSearchResults.length,
                              direction,
                            ),
                          ),
                        onQueryChange: (query) => {
                          setSearchQuery(query);
                          setSearchIndex(-1);
                        },
                        query: searchQuery,
                      }
                    : undefined
                }
                title={title}
                zoom={zoom}
              />
              <div className="flex min-h-0 flex-1">
                {showDocumentNavigation && (
                  <ReaderDocumentNavigation
                    labels={{
                      emptyOutline: t("outline.empty"),
                      navigation: t("navigation.label"),
                      outline: t("navigation.outline"),
                      pages: t("navigation.pages"),
                    }}
                    mode={navigationMode}
                    onModeChange={setNavigationMode}
                    onOutlineSelect={(destination) =>
                      void resolveDestination(destination)
                    }
                    outline={outline}
                  >
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
                  </ReaderDocumentNavigation>
                )}
                <PdfPage
                  activeTextSelection={activeTextSelection}
                  adapter={adapter}
                  annotationLinkLabel={t("pdfLink")}
                  annotations={annotationsQuery.data?.items ?? []}
                  canvasLabel={t("documentCanvas")}
                  fitMode={fitMode}
                  loadingLabel={t("renderingPage")}
                  onActiveTextSelectionChange={handleActiveTextSelectionChange}
                  onAnnotationSelect={(id) => void openAnnotation(id)}
                  onAskSelection={(selection) => {
                    setPendingTurnContext({
                      ...selection,
                      document_id: documentId,
                    });
                    setActiveTextSelection(undefined);
                    window.getSelection()?.removeAllRanges();
                    updateLocation({ panel: "ask" });
                  }}
                  onCommentSelection={(selection) => {
                    setAnnotationSelection({
                      ...selection,
                      document_id: documentId,
                    });
                    setActiveTextSelection(undefined);
                    setSelectedAnnotationId(undefined);
                    window.getSelection()?.removeAllRanges();
                    updateLocation({ panel: "annotations" });
                  }}
                  onHighlightSelection={(selection, color) => {
                    void createHighlight(
                      { ...selection, document_id: documentId },
                      color,
                    ).catch(notifyActionError);
                  }}
                  onInternalDestination={(destination) =>
                    void resolveDestination(destination)
                  }
                  pageNumber={pageNumber}
                  searchQuery={searchQuery}
                  selectedAnnotationId={selectedAnnotationId}
                  selectionLabels={{
                    ask: t("selection.ask"),
                    colors: {
                      blue: t("annotations.colors.blue"),
                      green: t("annotations.colors.green"),
                      neutral: t("annotations.colors.neutral"),
                      yellow: t("annotations.colors.yellow"),
                    },
                    comment: t("selection.comment"),
                    copy: t("selection.copy"),
                    copied: t("selection.copied"),
                    copying: t("selection.copying"),
                    copyFailed: t("selection.copyFailed"),
                    highlight: t("selection.highlight"),
                  }}
                  zoom={zoom}
                />
              </div>
            </section>
            {useDesktopPanel && desktopPanelOpen && (
              <ReaderContextPanel
                annotationSelection={annotationSelection}
                annotations={annotationsQuery.data?.items ?? []}
                annotationsError={annotationsQuery.isError}
                className="flex"
                conversationId={conversationSession.activeConversationId}
                conversationSession={conversationSession}
                conversations={conversationsQuery.data?.items ?? []}
                conversationsLoading={conversationsQuery.isPending}
                document={document}
                onActionError={notifyActionError}
                onAnnotationDelete={async (id) => {
                  await deleteReaderHighlight(id);
                  setSelectedAnnotationId(undefined);
                  await refreshAnnotations();
                }}
                onAnnotationSelect={(id) => void openAnnotation(id)}
                onClose={() => updateLocation({ panel: null })}
                onCommentCreate={async (id, content) => {
                  await createReaderComment(id, content);
                  await refreshAnnotations();
                }}
                onCommentDelete={async (id) => {
                  await deleteReaderComment(id);
                  await refreshAnnotations();
                }}
                onCommentUpdate={async (id, content) => {
                  await updateReaderComment(id, content);
                  await refreshAnnotations();
                }}
                onConversationChange={(id) =>
                  updateLocation({ conversation: id, panel: "ask" })
                }
                onConversationNew={() =>
                  updateLocation({ conversation: null, panel: "ask" })
                }
                onConversationPin={async (id, pinned) => {
                  await setReaderConversationPinned(id, pinned);
                  await queryClient.invalidateQueries({
                    queryKey: conversationKeys.lists(),
                  });
                }}
                onHighlightCreate={(comment) =>
                  createHighlight(annotationSelection, "yellow", comment)
                }
                onHighlightUpdate={async (id, color) => {
                  await updateReaderHighlight(id, { color });
                  await refreshAnnotations();
                }}
                onPanelChange={(nextPanel) =>
                  updateLocation({ panel: nextPanel })
                }
                onSourceOpen={(source) => {
                  const page = readSourcePage(source.locator);
                  if (source.document_id === documentId) {
                    updateLocation({ page, panel: "ask" });
                  } else {
                    router.push(
                      `/reader/${source.document_id}${page ? `?page=${page}` : ""}` as Route,
                    );
                  }
                }}
                onTurnContextClear={() => {
                  setPendingTurnContext(undefined);
                  setSelectedAnnotationId(undefined);
                }}
                panel={panel ?? "ask"}
                pendingTurnContext={pendingTurnContext}
                reasoningLevel={reasoningLevel}
                selectedAnnotation={selectedAnnotation}
                setReasoningLevel={setReasoningLevel}
                title={title}
              />
            )}
          </div>
        )}
      </div>

      <Sheet
        onOpenChange={setMobileOutlineOpen}
        open={!showDocumentNavigation && mobileOutlineOpen}
      >
        <SheetContent
          className="inset-0 h-dvh w-full max-w-none rounded-none border-0 p-0"
          closeLabel={t("closePanel")}
        >
          <div className="flex h-full flex-col px-5 pt-[max(1.25rem,env(safe-area-inset-top))] pb-[max(1.25rem,env(safe-area-inset-bottom))]">
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
                  onSelect={(destination) => {
                    setMobileOutlineOpen(false);
                    void resolveDestination(destination);
                  }}
                />
              ) : (
                <p className="text-muted py-12 text-center text-sm">
                  {t("outline.empty")}
                </p>
              )}
            </div>
          </div>
        </SheetContent>
      </Sheet>

      <Sheet
        onOpenChange={(open) => {
          if (!open) updateLocation({ panel: null });
        }}
        open={!useDesktopPanel && desktopPanelOpen}
      >
        <SheetContent
          className="inset-0 h-dvh w-full max-w-none rounded-none border-0 p-0"
          closeLabel={t("closePanel")}
          showCloseButton={false}
        >
          <SheetTitle className="sr-only">{t("contextPanel")}</SheetTitle>
          <ReaderContextPanel
            annotationSelection={annotationSelection}
            annotations={annotationsQuery.data?.items ?? []}
            annotationsError={annotationsQuery.isError}
            conversationId={conversationSession.activeConversationId}
            conversationSession={conversationSession}
            conversations={conversationsQuery.data?.items ?? []}
            conversationsLoading={conversationsQuery.isPending}
            document={document}
            onActionError={notifyActionError}
            onAnnotationDelete={async (id) => {
              await deleteReaderHighlight(id);
              setSelectedAnnotationId(undefined);
              await refreshAnnotations();
            }}
            onAnnotationSelect={(id) => void openAnnotation(id)}
            onCommentCreate={async (id, content) => {
              await createReaderComment(id, content);
              await refreshAnnotations();
            }}
            onCommentDelete={async (id) => {
              await deleteReaderComment(id);
              await refreshAnnotations();
            }}
            onCommentUpdate={async (id, content) => {
              await updateReaderComment(id, content);
              await refreshAnnotations();
            }}
            onClose={() => updateLocation({ panel: null })}
            onConversationChange={(id) =>
              updateLocation({ conversation: id, panel: "ask" })
            }
            onConversationNew={() =>
              updateLocation({ conversation: null, panel: "ask" })
            }
            onConversationPin={async (id, pinned) => {
              await setReaderConversationPinned(id, pinned);
              await queryClient.invalidateQueries({
                queryKey: conversationKeys.lists(),
              });
            }}
            onHighlightCreate={(comment) =>
              createHighlight(annotationSelection, "yellow", comment)
            }
            onHighlightUpdate={async (id, color) => {
              await updateReaderHighlight(id, { color });
              await refreshAnnotations();
            }}
            onPanelChange={(nextPanel) => updateLocation({ panel: nextPanel })}
            onSourceOpen={(source) => {
              const page = readSourcePage(source.locator);
              if (source.document_id === documentId) {
                updateLocation({ page, panel: "ask" });
              } else {
                router.push(
                  `/reader/${source.document_id}${page ? `?page=${page}` : ""}` as Route,
                );
              }
            }}
            onTurnContextClear={() => {
              setPendingTurnContext(undefined);
              setSelectedAnnotationId(undefined);
            }}
            panel={panel ?? "ask"}
            pendingTurnContext={pendingTurnContext}
            reasoningLevel={reasoningLevel}
            selectedAnnotation={selectedAnnotation}
            setReasoningLevel={setReasoningLevel}
            title={title}
          />
        </SheetContent>
      </Sheet>
    </WorkspaceShell>
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
