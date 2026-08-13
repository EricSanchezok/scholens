"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BackIcon } from "@/design-system/icons/semantic-icons";
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
  createReaderAnnotationThread,
  deleteReaderComment,
  deleteReaderAnnotationThread,
  getReaderDownloadUrl,
  readerKeys,
  readerQueries,
  setReaderConversationPinned,
  updateReaderComment,
  updateReaderAnnotationThread,
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
import { moveReaderSearchCursor } from "./reader-search";
import type { ReaderHighlightColor } from "./reader-highlight-colors";
import {
  parsePositiveInteger,
  readReaderPanel,
  readSourcePage,
} from "./reader-routing";
import type {
  ReaderAnnotation,
  ReaderAnnotationAudience,
  ReaderAnnotationAudienceFilter,
  ReaderAnnotationStatus,
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
  const locationParamsRef = React.useRef(
    new URLSearchParams(searchParams.toString()),
  );
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
  const [selectedAnchorIds, setSelectedAnchorIds] = React.useState<string[]>(
    [],
  );
  const [annotationAudienceFilter, setAnnotationAudienceFilter] =
    React.useState<ReaderAnnotationAudienceFilter>("all");
  const [annotationStatusFilter, setAnnotationStatusFilter] =
    React.useState<ReaderAnnotationStatus>("open");
  const lastContextPanelRef = React.useRef<"ask" | "annotations" | "details">(
    "ask",
  );
  const [reasoningLevel, setReasoningLevel] =
    React.useState<ReasoningLevel>("standard");
  const documentQuery = useQuery(readerQueries.document(documentId));
  const projectsQuery = useQuery(readerQueries.projects(documentId));

  const projectId = searchParams.get("project") ?? undefined;
  const activeProject = projectsQuery.data?.items.find(
    (project) => project.id === projectId,
  );
  const annotationsQuery = useQuery(
    readerQueries.annotations(
      documentId,
      projectId,
      readReaderPanel(searchParams.get("panel")) === "annotations",
    ),
  );
  const conversationsQuery = useQuery(
    conversationQueries.list(
      projectId
        ? {
            contextDocumentId: documentId,
            scopeId: projectId,
            scopeType: "project",
          }
        : { scopeId: documentId, scopeType: "paper" },
    ),
  );

  const rawPage = parsePositiveInteger(searchParams.get("page"));
  const pageNumber = Math.min(rawPage, pageCount);
  const panel = readReaderPanel(searchParams.get("panel"));
  const conversationId = searchParams.get("conversation") ?? undefined;
  const selectedAnnotation = annotationsQuery.data?.items.find(
    (item) => item.id === selectedAnnotationId,
  );
  const filteredAnnotations = React.useMemo(() => {
    const items = (annotationsQuery.data?.items ?? []).filter((item) => {
      const thread = item.annotation_thread;
      if (!thread || thread.status !== annotationStatusFilter) return false;
      if (annotationAudienceFilter === "mine") {
        return item.audience.kind === "personal";
      }
      if (annotationAudienceFilter === "project") {
        return item.audience.kind === "project";
      }
      return true;
    });
    return [...items].sort((left, right) => {
      const leftFocused = selectedAnchorIds.includes(left.id);
      const rightFocused = selectedAnchorIds.includes(right.id);
      return Number(rightFocused) - Number(leftFocused);
    });
  }, [
    annotationAudienceFilter,
    annotationStatusFilter,
    annotationsQuery.data?.items,
    selectedAnchorIds,
  ]);
  const updateLocation = React.useCallback(
    (patch: {
      page?: number;
      panel?: ReaderContextPanelName | null;
      conversation?: string | null;
      project?: string | null;
    }) => {
      const next = new URLSearchParams(locationParamsRef.current?.toString());
      if (patch.page !== undefined) next.set("page", String(patch.page));
      if (patch.panel === null) next.delete("panel");
      else if (patch.panel) next.set("panel", patch.panel);
      if (patch.conversation === null) next.delete("conversation");
      else if (patch.conversation) next.set("conversation", patch.conversation);
      if (patch.project === null) next.delete("project");
      else if (patch.project) next.set("project", patch.project);
      const query = next.toString();
      locationParamsRef.current = next;
      router.replace(
        `/reader/${documentId}${query ? `?${query}` : ""}` as Route,
        { scroll: false },
      );
    },
    [documentId, router],
  );
  const conversationSession = useConversationSession({
    context: {
      kind: "selection",
      document_ids: [documentId],
      project_ids: projectId ? [projectId] : [],
    },
    conversationId,
    getTurnContexts: () => {
      if (pendingTurnContext) {
        return [{ ...pendingTurnContext, document_id: documentId }];
      }
      if (selectedAnnotationId) {
        return [{ kind: "annotation_thread", thread_id: selectedAnnotationId }];
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
    scopeId: projectId ?? documentId,
    scopeType: projectId ? "project" : "paper",
  });
  const adapter =
    adapterState?.documentId === documentId ? adapterState.adapter : undefined;
  const adapterError =
    adapterErrorState?.documentId === documentId
      ? adapterErrorState.error
      : undefined;

  async function refreshAnnotations() {
    await queryClient.invalidateQueries({
      queryKey: readerKeys.annotationLists(documentId),
    });
  }

  function cacheAnnotation(item: ReaderAnnotation) {
    queryClient.setQueryData<{
      items: ReaderAnnotation[];
      next_cursor?: string | null;
    }>(readerKeys.annotations(documentId, projectId), (current) => ({
      items: [
        item,
        ...(current?.items ?? []).filter(({ id }) => id !== item.id),
      ],
      next_cursor: current?.next_cursor ?? null,
    }));
  }

  async function createHighlight(
    targetSelection: ReaderSelection | undefined,
    color: ReaderHighlightColor = "yellow",
    comment?: string,
    audience: ReaderAnnotationAudience = "personal",
  ) {
    if (!targetSelection) return;
    const item = await createReaderAnnotationThread(documentId, {
      audience:
        audience === "project" && projectId
          ? { kind: "project", project_id: projectId }
          : { kind: "personal" },
      color,
      initial_comment: comment?.trim() || undefined,
      position: targetSelection.anchor,
      quote_text: targetSelection.selected_text,
    });
    cacheAnnotation(item);
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

  React.useEffect(() => {
    if (projectsQuery.isPending || !projectId || activeProject) return;
    updateLocation({ conversation: null, project: null });
    toast.notify({
      description: t("projects.unavailableDescription"),
      title: t("projects.unavailableTitle"),
    });
  }, [
    activeProject,
    projectId,
    projectsQuery.isPending,
    t,
    toast,
    updateLocation,
  ]);

  React.useEffect(() => {
    if (
      !conversationId ||
      conversationsQuery.isPending ||
      !conversationsQuery.data
    )
      return;
    if (
      conversationsQuery.data?.items.some(
        (conversation) => conversation.id === conversationId,
      )
    ) {
      return;
    }
    updateLocation({ conversation: null });
    toast.notify({ title: t("conversations.contextChanged") });
  }, [
    conversationId,
    conversationsQuery.data,
    conversationsQuery.isPending,
    t,
    toast,
    updateLocation,
  ]);

  async function openAnnotation(
    annotationId: string,
    anchorIds = [annotationId],
  ) {
    setSelectedAnnotationId(annotationId);
    setSelectedAnchorIds(anchorIds);
    const annotation = annotationsQuery.data?.items.find(
      (item) => item.id === annotationId,
    );
    const position = annotation?.annotation_thread?.position;
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

  const searchResults = React.useMemo(
    () => (searchState?.query === searchQuery ? searchState.results : []),
    [searchQuery, searchState],
  );

  React.useEffect(() => {
    const activeMatch = searchResults[searchIndex];
    if (activeMatch && activeMatch.pageNumber !== pageNumber) {
      updateLocation({ page: activeMatch.pageNumber });
    }
  }, [pageNumber, searchIndex, searchResults, updateLocation]);

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
      page: t("toolbar.page"),
      previousPage: t("toolbar.previousPage"),
      previousSearchResult: t("search.previous"),
      projectContext: t("projects.selector"),
      personalContext: t("projects.personal"),
      returnLibrary: t("returnLibrary"),
      search: t("toolbar.search"),
      showOutline: t("toolbar.showOutline"),
      showPages: t("toolbar.showPages"),
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

  const contextPanelProps: React.ComponentProps<typeof ReaderContextPanel> = {
    annotationSelection,
    annotationAudienceFilter,
    annotations: filteredAnnotations,
    annotationsError: annotationsQuery.isError,
    annotationStatusFilter,
    conversationId: conversationSession.activeConversationId,
    conversationSession,
    conversations: conversationsQuery.data?.items ?? [],
    conversationsLoading: conversationsQuery.isPending,
    document,
    onActionError: notifyActionError,
    onAnnotationAudienceFilterChange: setAnnotationAudienceFilter,
    onAnnotationDelete: async (id) => {
      await deleteReaderAnnotationThread(id);
      setSelectedAnnotationId(undefined);
      await refreshAnnotations();
    },
    onAnnotationSelect: (id) => void openAnnotation(id),
    onAnnotationStatusChange: async (id, status) => {
      cacheAnnotation(await updateReaderAnnotationThread(id, { status }));
      if (status !== annotationStatusFilter) setSelectedAnnotationId(undefined);
      await refreshAnnotations();
    },
    onAnnotationStatusFilterChange: setAnnotationStatusFilter,
    onClose: () => updateLocation({ panel: null }),
    onCommentCreate: async (id, content) => {
      await createReaderComment(id, content);
      await refreshAnnotations();
    },
    onCommentDelete: async (id) => {
      await deleteReaderComment(id);
      await refreshAnnotations();
    },
    onCommentUpdate: async (id, content) => {
      await updateReaderComment(id, content);
      await refreshAnnotations();
    },
    onConversationChange: (id) =>
      updateLocation({ conversation: id, panel: "ask" }),
    onConversationNew: () =>
      updateLocation({ conversation: null, panel: "ask" }),
    onConversationPin: async (id, pinned) => {
      await setReaderConversationPinned(id, pinned);
      await queryClient.invalidateQueries({
        queryKey: conversationKeys.lists(),
      });
    },
    onHighlightCreate: (comment, color, audience) =>
      createHighlight(annotationSelection, color, comment, audience),
    onHighlightUpdate: async (id, color) => {
      cacheAnnotation(await updateReaderAnnotationThread(id, { color }));
      await refreshAnnotations();
    },
    onPanelChange: (nextPanel) => updateLocation({ panel: nextPanel }),
    onSourceOpen: (source) => {
      const sourcePage = readSourcePage(source.locator);
      if (source.document_id === documentId) {
        updateLocation({ page: sourcePage, panel: "ask" });
      } else {
        router.push(
          `/reader/${source.document_id}${sourcePage ? `?page=${sourcePage}` : ""}` as Route,
        );
      }
    },
    onTurnContextClear: () => {
      setPendingTurnContext(undefined);
      setSelectedAnnotationId(undefined);
    },
    panel: panel ?? "ask",
    pendingTurnContext,
    projectContext: activeProject,
    reasoningLevel,
    selectedAnnotation,
    setReasoningLevel,
    title,
  };

  return (
    <WorkspaceShell
      activeConversationId={conversationId}
      activeDestination="library"
      actor={actor}
      collapsed={collapsed}
      conversations={conversationsQuery.data?.items ?? []}
      conversationHref={(id) =>
        `/reader/${documentId}?panel=ask&conversation=${id}${projectId ? `&project=${projectId}` : ""}`
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
          <Icon glyph={BackIcon} size={24} />
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
                navigationMode={navigationMode}
                onToggleNavigation={() => {
                  if (showDocumentNavigation) {
                    setNavigationMode((current) =>
                      current === "outline" ? "thumbnails" : "outline",
                    );
                  } else setMobileOutlineOpen(true);
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
                projectContext={{
                  onChange: (nextProjectId) => {
                    setSelectedAnnotationId(undefined);
                    setActiveTextSelection(undefined);
                    setAnnotationAudienceFilter("all");
                    setAnnotationStatusFilter("open");
                    updateLocation({
                      conversation: null,
                      project: nextProjectId ?? null,
                    });
                  },
                  options: projectsQuery.data?.items ?? [],
                  projectId,
                }}
                search={
                  searchOpen
                    ? {
                        currentIndex: searchIndex,
                        matchCount: searchResults.length,
                        onClose: closeSearch,
                        onMove: (direction) =>
                          setSearchIndex((current) =>
                            moveReaderSearchCursor(
                              current,
                              searchResults.length,
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
                    }}
                    mode={navigationMode}
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
                  annotations={filteredAnnotations}
                  canvasLabel={t("documentCanvas")}
                  fitMode={fitMode}
                  loadingLabel={t("renderingPage")}
                  onActiveTextSelectionChange={handleActiveTextSelectionChange}
                  onAnnotationSelect={(id, anchorIds) =>
                    void openAnnotation(id, anchorIds)
                  }
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
                  onHighlightSelection={(selection, color, audience) => {
                    void createHighlight(
                      { ...selection, document_id: documentId },
                      color,
                      undefined,
                      audience,
                    ).catch(notifyActionError);
                  }}
                  onInternalDestination={(destination) =>
                    void resolveDestination(destination)
                  }
                  onVisiblePageChange={(nextPage) => {
                    setActiveTextSelection(undefined);
                    updateLocation({ page: nextPage });
                  }}
                  pageCount={pageCount}
                  pageNumber={pageNumber}
                  searchMatches={searchResults}
                  activeSearchMatch={searchResults[searchIndex]}
                  searchQuery={searchQuery}
                  selectedAnnotationId={selectedAnnotationId}
                  projectContext={Boolean(activeProject)}
                  selectionLabels={{
                    ask: t("selection.ask"),
                    colors: {
                      blue: t("annotations.colors.blue"),
                      gray: t("annotations.colors.gray"),
                      green: t("annotations.colors.green"),
                      magenta: t("annotations.colors.magenta"),
                      orange: t("annotations.colors.orange"),
                      purple: t("annotations.colors.purple"),
                      red: t("annotations.colors.red"),
                      yellow: t("annotations.colors.yellow"),
                    },
                    comment: t("selection.comment"),
                    copy: t("selection.copy"),
                    copied: t("selection.copied"),
                    copying: t("selection.copying"),
                    copyFailed: t("selection.copyFailed"),
                    highlight: t("selection.highlight"),
                    personal: t("annotations.audience.personal"),
                    project: t("annotations.audience.project"),
                  }}
                  zoom={zoom}
                />
              </div>
            </section>
            {useDesktopPanel && desktopPanelOpen && (
              <ReaderContextPanel {...contextPanelProps} className="flex" />
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
          <ReaderContextPanel {...contextPanelProps} />
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
