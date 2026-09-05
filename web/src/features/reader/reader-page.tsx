"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BackIcon } from "@/design-system/icons/semantic-icons";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";
import {
  reportPdfRenderError,
  reportReaderAnnotationMetric,
  usePrimaryContentReady,
} from "@/lib/observability/web-performance";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHandle,
  DialogHeader,
  DialogTitle,
  IconButton,
  Sheet,
  SheetContent,
  SheetTitle,
  useToast,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  AnimatePresence,
  m,
  motionTransitions,
  motionVariants,
  useMotionPreference,
} from "@/design-system/motion";
import { ApiError } from "@/lib/api";
import { useAuthSession, type Actor } from "@/features/authentication";
import { useInstallExperience } from "@/features/install-experience";
import {
  PaperInsightsContainer,
  ReadingActivityTracker,
} from "@/features/research-activity";
import {
  conversationKeys,
  conversationQueries,
  setConversationPinned,
  useConversationSession,
  type ReasoningLevel,
  type ResearchContext,
} from "@/features/conversation";
import { WorkspaceShell } from "@/features/workspace-shell";
import {
  currentAppLocation,
  useNavigationRestorer,
  useWorkspaceNavigation,
  type NavigationOriginKind,
  type NavigationSnapshot,
} from "@/features/workspace-navigation";
import {
  createReaderComment,
  createReaderAnnotationThread,
  deleteReaderComment,
  deleteReaderAnnotationThread,
  getReaderDownloadUrl,
  readerKeys,
  readerQueries,
  updateReaderComment,
  updateReaderAnnotationThread,
} from "./api/queries";
import {
  PdfPage,
  type ReaderEffectiveZoom,
  type ReaderFitMode,
  type ReaderPdfSourceTarget,
} from "./components/pdf-page";
import {
  readerSelectionKey,
  readerSelectionTurnContext,
  type ReaderSelection,
} from "./reader-selection";
import { PdfThumbnail } from "./components/pdf-thumbnail";
import {
  ReaderMobileReflowNudge,
  useReaderMobileReflowNudge,
} from "./components/reader-mobile-reflow-nudge";
import {
  useDesktopReaderPanel,
  useDocumentNavigationRail,
} from "./hooks/use-reader-layout";
import {
  ReaderContextPanel,
  type ReaderContextPanelProps,
} from "./components/reader-context-panel";
import { ReaderDocumentNavigation } from "./components/reader-document-navigation";
import {
  ReaderToolbar,
  type ReaderToolbarLabels,
} from "./components/reader-toolbar";
import {
  PdfDocumentAdapter,
  PdfJsAssetsUnavailableError,
} from "./pdf-document-adapter";
import { moveReaderSearchCursor } from "./reader-search";
import { compareReaderAnnotationsBySource } from "./reader-annotations";
import { readerScrollTopForTarget } from "./reader-scroll";
import type { ReaderHighlightColor } from "./reader-highlight-colors";
import {
  conversationBelongsToReaderContext,
  parsePositiveInteger,
  readReaderPanel,
  readReaderView,
  readSourcePage,
  shouldFallbackFromReaderProjectContext,
} from "./reader-routing";
import {
  ReaderTranslationPanel,
  useReaderTranslation,
  type FullTranslationStatus,
} from "./translation";
import {
  ReaderReflowOutline,
  ReaderReflowSurface,
  type ReaderReflowOutlineItem,
} from "./reflow";
import type {
  ReaderAnnotationAudience,
  ReaderAnnotationAudienceFilter,
  ReaderAnnotationMode,
  ReaderAnnotationStatus,
  ReaderContextPanel as ReaderContextPanelName,
} from "./reader-types";

function pdfDecoderForError(
  error: unknown,
): "jbig2" | "openjpeg" | "qcms" | "unknown" {
  const message = error instanceof Error ? error.message : String(error);
  if (/jbig2/i.test(message)) return "jbig2";
  if (/openjpeg|jpx/i.test(message)) return "openjpeg";
  if (/qcms|icc/i.test(message)) return "qcms";
  return "unknown";
}

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
  const pendingPanelHistoryRef = React.useRef(false);
  const t = useTranslations("Reader");
  const conversationT = useTranslations("Home.conversation");
  const { resolved: resolvedMotion } = useMotionPreference();
  const toast = useToast();
  const { signOut } = useAuthSession();
  const { recordCoreAction } = useInstallExperience();
  const navigation = useWorkspaceNavigation();
  const updateContextRoute = navigation.updateContextRoute;
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
  const [customZoomPercent, setCustomZoomPercent] = React.useState(100);
  const [effectiveZoom, setEffectiveZoom] = React.useState<
    ReaderEffectiveZoom & { documentId: string }
  >();
  const [reflowOutlineOpen, setReflowOutlineOpen] = React.useState(false);
  const [mobileReflowOutlineOpen, setMobileReflowOutlineOpen] =
    React.useState(false);
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState("");
  const [searchState, setSearchState] = React.useState<{
    query: string;
    results: Awaited<ReturnType<PdfDocumentAdapter["search"]>>;
  }>();
  const [searchIndex, setSearchIndex] = React.useState(-1);
  const [activeTextSelection, setActiveTextSelection] =
    React.useState<ReaderSelection>();
  const activeTextSelectionRef = React.useRef<ReaderSelection | undefined>(
    undefined,
  );
  const [pendingTurnContext, setPendingTurnContext] =
    React.useState<ReaderSelection>();
  const [annotationSelection, setAnnotationSelection] =
    React.useState<ReaderSelection>();
  const [annotationInitialComment, setAnnotationInitialComment] =
    React.useState<string>();
  const [selectedAnnotationId, setSelectedAnnotationId] =
    React.useState<string>();
  const [annotationNavigation, setAnnotationNavigation] = React.useState<{
    id: string;
    request: number;
  }>();
  const annotationNavigationRequestRef = React.useRef(0);
  const [previewAnnotationId, setPreviewAnnotationId] =
    React.useState<string>();
  const [annotationAudienceFilter, setAnnotationAudienceFilter] =
    React.useState<ReaderAnnotationAudienceFilter>("all");
  const [annotationStatusFilter, setAnnotationStatusFilter] =
    React.useState<ReaderAnnotationStatus>("open");
  const [annotationModeFilter, setAnnotationModeFilter] =
    React.useState<ReaderAnnotationMode>("all");
  const lastContextPanelRef = React.useRef<ReaderContextPanelName>("ask");
  const [contextOverrides, setContextOverrides] = React.useState<
    Record<string, ResearchContext>
  >({});
  const reflowScrollContainerRef = React.useRef<HTMLDivElement>(null);
  const pdfScrollContainerRef = React.useRef<HTMLDivElement>(null);
  const [reasoningLevel, setReasoningLevel] =
    React.useState<ReasoningLevel>("standard");
  const [fullTranslationStatus, setFullTranslationStatus] =
    React.useState<FullTranslationStatus>("idle");
  const [reflowOutline, setReflowOutline] = React.useState<
    ReaderReflowOutlineItem[]
  >([]);
  const [reflowSourceTarget, setReflowSourceTarget] =
    React.useState<ReaderPdfSourceTarget>();

  React.useEffect(() => {
    activeTextSelectionRef.current = activeTextSelection;
  }, [activeTextSelection]);
  const projectId = searchParams.get("project") ?? undefined;
  const documentQuery = useQuery(readerQueries.document(documentId));
  usePrimaryContentReady(documentQuery.isSuccess);
  const projectsQuery = useQuery(readerQueries.projects(documentId, projectId));
  const translation = useReaderTranslation({
    documentId,
    selection: activeTextSelection,
  });
  const readerView = readReaderView(searchParams.get("view"));
  const fallbackReturnHref = projectId
    ? `/projects/${projectId}?view=papers`
    : "/library";
  const returnKind: NavigationOriginKind =
    navigation.context?.originKind ?? (projectId ? "project" : "library");
  const returnLabel = t(`return.${returnKind}`);
  const handleReturn = () => navigation.returnFromContext(fallbackReturnHref);
  useNavigationRestorer("reader-document", {
    capture: () => ({
      scrollTop:
        (readerView === "pdf"
          ? pdfScrollContainerRef.current
          : reflowScrollContainerRef.current
        )?.scrollTop ?? 0,
      view: readerView,
    }),
    restore: (snapshot: NavigationSnapshot) => {
      const scrollTop =
        typeof snapshot.scrollTop === "number" ? snapshot.scrollTop : 0;
      let attempts = 0;
      const restore = () => {
        const container =
          snapshot.view === "reflow"
            ? reflowScrollContainerRef.current
            : pdfScrollContainerRef.current;
        if (container) {
          container.scrollTop = scrollTop;
          return;
        }
        attempts += 1;
        if (attempts < 12) window.requestAnimationFrame(restore);
      };
      window.requestAnimationFrame(restore);
    },
  });
  const fullTranslationEnabled = searchParams.get("translate") === "full";
  const translationCacheVersion = translation.effectivePreferences
    ? JSON.stringify({
        customInstructions:
          translation.effectivePreferences.custom_instructions ?? null,
        sourceLanguage: translation.effectivePreferences.source_language,
        targetLanguage: translation.effectivePreferences.target_language,
        translateReferences:
          translation.effectivePreferences.translate_references,
      })
    : undefined;

  const activeProject = projectsQuery.data?.items.find(
    (project) => project.id === projectId,
  );
  const shouldFallbackFromProjectContext =
    shouldFallbackFromReaderProjectContext({
      hasActiveProject: Boolean(activeProject),
      isFetchedAfterMount: projectsQuery.isFetchedAfterMount,
      isFetching: projectsQuery.isFetching,
      isRefetchError: projectsQuery.isRefetchError,
      isSuccess: projectsQuery.isSuccess,
      projectId,
      verifiedProjectId: projectsQuery.data?.verifiedProjectId,
    });
  const annotationsQuery = useQuery(
    readerQueries.annotations(
      documentId,
      {
        audience:
          annotationAudienceFilter === "all"
            ? undefined
            : annotationAudienceFilter,
        mode: annotationModeFilter === "all" ? undefined : annotationModeFilter,
        projectId,
        status: annotationStatusFilter,
      },
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
  const zoomPercent =
    fitMode === "custom"
      ? customZoomPercent
      : effectiveZoom?.documentId === documentId &&
          effectiveZoom.fitMode === fitMode &&
          effectiveZoom.pageNumber === pageNumber
        ? effectiveZoom.zoomPercent
        : undefined;
  const panel = readReaderPanel(searchParams.get("panel"));
  const conversationId = searchParams.get("conversation") ?? undefined;
  const filteredAnnotations = React.useMemo(() => {
    const items = annotationsQuery.data?.items ?? [];
    return [...items].sort(compareReaderAnnotationsBySource);
  }, [annotationsQuery.data?.items]);
  const updateLocation = React.useCallback(
    (patch: {
      page?: number;
      panel?: ReaderContextPanelName | null;
      conversation?: string | null;
      project?: string | null;
      translate?: boolean;
      view?: "pdf" | "reflow";
    }) => {
      const next = new URLSearchParams(locationParamsRef.current.toString());
      const previousPanel = readReaderPanel(next.get("panel"));
      if (patch.page !== undefined) next.set("page", String(patch.page));
      if (patch.panel === null) next.delete("panel");
      else if (patch.panel) next.set("panel", patch.panel);
      if (patch.conversation === null) next.delete("conversation");
      else if (patch.conversation) next.set("conversation", patch.conversation);
      if (patch.project === null) next.delete("project");
      else if (patch.project) next.set("project", patch.project);
      if (patch.translate === false) next.delete("translate");
      else if (patch.translate) next.set("translate", "full");
      if (patch.view === "pdf") next.delete("view");
      else if (patch.view) next.set("view", patch.view);
      const nextPanel = readReaderPanel(next.get("panel"));
      const query = next.toString();
      locationParamsRef.current = next;
      const href = `/reader/${documentId}${query ? `?${query}` : ""}` as Route;
      if (!previousPanel && nextPanel) {
        pendingPanelHistoryRef.current = true;
        updateContextRoute(href, { history: "push" });
      } else if (
        previousPanel &&
        !nextPanel &&
        window.history.state?.__scholensHistoryLayer === "reader-panel"
      ) {
        router.back();
      } else {
        updateContextRoute(href);
      }
    },
    [documentId, router, updateContextRoute],
  );

  React.useEffect(() => {
    locationParamsRef.current = new URLSearchParams(searchParams.toString());
    if (!panel || !pendingPanelHistoryRef.current) return;
    pendingPanelHistoryRef.current = false;
    window.history.replaceState(
      { ...window.history.state, __scholensHistoryLayer: "reader-panel" },
      "",
    );
  }, [panel, searchParams]);
  const defaultContext: ResearchContext = {
    kind: "selection",
    document_ids: [documentId],
    project_ids: projectId ? [projectId] : [],
  };
  const requestedContext = contextOverrides[conversationId ?? "new"];
  const conversationSession = useConversationSession({
    actorId: actor.id,
    context: requestedContext,
    defaultContext,
    conversationId,
    draftScope: `reader:${documentId}`,
    getTurnContexts: () => {
      if (pendingTurnContext) {
        return [
          readerSelectionTurnContext({
            ...pendingTurnContext,
            document_id: documentId,
          }),
        ];
      }
      if (selectedAnnotationId) {
        return [{ kind: "annotation_thread", thread_id: selectedAnnotationId }];
      }
      return undefined;
    },
    onConversationCreated: (nextConversationId) => {
      setContextOverrides((current) => ({
        ...current,
        [nextConversationId]: requestedContext ?? defaultContext,
      }));
      updateLocation({ conversation: nextConversationId, panel: "ask" });
    },
    onSubmissionError: () =>
      toast.notify({
        title: conversationT("error"),
        description: conversationT("retryHint"),
      }),
    onDraftRestored: (draft) => {
      setReasoningLevel(draft.reasoningLevel);
      setContextOverrides((current) => ({
        ...current,
        [conversationId ?? "new"]: draft.context,
      }));
    },
    onTurnStarted: () => {
      setPendingTurnContext(undefined);
      setSelectedAnnotationId(undefined);
      recordCoreAction();
    },
    reasoningLevel,
    scopeId: projectId ?? documentId,
    scopeType: projectId ? "project" : "paper",
    updateExistingContext: true,
  });
  const contextKey = conversationSession.activeConversationId ?? "new";
  const resolvedContext =
    contextOverrides[contextKey] ??
    conversationSession.conversationQuery.data?.paper_context ??
    defaultContext;

  function handleContextChange(nextContext: ResearchContext) {
    setContextOverrides((current) => ({
      ...current,
      [contextKey]: nextContext,
    }));
  }
  const adapter =
    adapterState?.documentId === documentId ? adapterState.adapter : undefined;
  const adapterError =
    adapterErrorState?.documentId === documentId
      ? adapterErrorState.error
      : undefined;

  async function refreshAnnotations() {
    reportReaderAnnotationMetric("reader_annotation_mutation");
    await queryClient.invalidateQueries({
      queryKey: readerKeys.annotationLists(documentId),
      refetchType: "active",
    });
  }

  async function createHighlight(
    targetSelection: ReaderSelection | undefined,
    color: ReaderHighlightColor = "yellow",
    comment?: string,
    audience: ReaderAnnotationAudience = "personal",
  ) {
    if (!targetSelection) return;
    const submittedSelectionKey = readerSelectionKey(targetSelection);
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
    await refreshAnnotations();
    const selectionStillActive =
      readerSelectionKey(activeTextSelectionRef.current) ===
      submittedSelectionKey;
    if (selectionStillActive) {
      setSelectedAnnotationId(item.id);
      activeTextSelectionRef.current = undefined;
      setActiveTextSelection(undefined);
      window.getSelection()?.removeAllRanges();
    }
    setAnnotationNavigation(undefined);
    setAnnotationSelection(undefined);
    setAnnotationInitialComment(undefined);
  }

  const handleActiveTextSelectionChange = React.useCallback(
    (nextSelection: ReaderSelection | undefined) => {
      setSelectedAnnotationId(undefined);
      const nextSelectionWithDocument = nextSelection
        ? { ...nextSelection, document_id: documentId }
        : undefined;
      activeTextSelectionRef.current = nextSelectionWithDocument;
      setActiveTextSelection(nextSelectionWithDocument);
    },
    [documentId],
  );

  const handleVisiblePageChange = React.useCallback(
    (nextPage: number) => {
      updateLocation({ page: nextPage });
    },
    [updateLocation],
  );

  const notifyActionError = React.useCallback(
    (error?: unknown) => {
      const code = error instanceof ApiError ? error.code : undefined;
      const feedback =
        code === "annotation_thread_resolved"
          ? {
              description: t("actions.threadResolvedDescription"),
              title: t("actions.threadResolvedTitle"),
            }
          : code === "annotation_thread_not_found"
            ? {
                description: t("actions.threadUnavailableDescription"),
                title: t("actions.threadUnavailableTitle"),
              }
            : code === "annotation_thread_has_other_replies"
              ? {
                  description: t("actions.threadHasRepliesDescription"),
                  title: t("actions.threadHasRepliesTitle"),
                }
              : code === "annotation_thread_resolution_denied" ||
                  code === "annotation_thread_has_no_discussion"
                ? {
                    description: t("actions.permissionDeniedDescription"),
                    title: t("actions.permissionDeniedTitle"),
                  }
                : {
                    description: t("actions.failedDescription"),
                    title: t("actions.failedTitle"),
                  };
      toast.notify({
        description: feedback.description,
        title: feedback.title,
      });
    },
    [t, toast],
  );

  React.useEffect(() => {
    if (!shouldFallbackFromProjectContext) return;
    updateLocation({ conversation: null, project: null });
    toast.notify({
      description: t("projects.unavailableDescription"),
      title: t("projects.unavailableTitle"),
    });
  }, [shouldFallbackFromProjectContext, t, toast, updateLocation]);

  const rejectedConversationRef = React.useRef<string | undefined>(undefined);
  React.useEffect(() => {
    if (!conversationId) {
      rejectedConversationRef.current = undefined;
      return;
    }

    const conversation = conversationSession.conversationQuery.data;
    const unavailable =
      conversationSession.conversationQuery.error instanceof ApiError &&
      conversationSession.conversationQuery.error.status === 404;
    const outsideContext =
      conversation !== undefined &&
      !conversationBelongsToReaderContext({
        conversation,
        documentId,
        projectId,
      });
    if (!unavailable && !outsideContext) return;
    if (rejectedConversationRef.current === conversationId) return;

    rejectedConversationRef.current = conversationId;
    updateLocation({ conversation: null });
    toast.notify({
      description: t("conversations.unavailableDescription"),
      title: t("conversations.unavailableTitle"),
    });
  }, [
    conversationId,
    conversationSession.conversationQuery.data,
    conversationSession.conversationQuery.error,
    documentId,
    projectId,
    t,
    toast,
    updateLocation,
  ]);

  function openAnnotation(annotationId: string) {
    setSelectedAnnotationId(annotationId);
    annotationNavigationRequestRef.current += 1;
    setAnnotationNavigation({
      id: annotationId,
      request: annotationNavigationRequestRef.current,
    });
    const annotation = annotationsQuery.data?.items.find(
      (item) => item.id === annotationId,
    );
    const position = annotation?.position;
    if (position?.page_number)
      updateLocation({ page: position.page_number, panel: "annotations" });
    else updateLocation({ panel: "annotations" });
  }

  function openAnnotationInPlace(annotationId: string) {
    setSelectedAnnotationId(annotationId);
    setAnnotationNavigation(undefined);
    updateLocation({ panel: "annotations" });
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
      })
      .catch((error: unknown) => {
        if (active) {
          reportPdfRenderError({
            decoder: pdfDecoderForError(error),
            error_kind:
              error instanceof PdfJsAssetsUnavailableError
                ? "asset_unavailable"
                : "document_open",
            surface: "document",
          });
          setAdapterErrorState({ documentId, error });
        }
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

  const scrollToReflowOutlineItem = React.useCallback(
    (id: string) => {
      const container = reflowScrollContainerRef.current;
      const target = Array.from(
        container?.querySelectorAll<HTMLElement>("[data-reflow-block]") ?? [],
      ).find((element) => element.dataset.reflowBlock === id);
      if (!container || !target) return;
      const containerRect = container.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      container.scrollTo({
        behavior: resolvedMotion === "reduced" ? "auto" : "smooth",
        top: readerScrollTopForTarget({
          alignment: "start",
          container: {
            clientHeight: container.clientHeight,
            scrollHeight: container.scrollHeight,
            scrollTop: container.scrollTop,
            top: containerRect.top,
          },
          // `scroll-mt-24` clearance on reflow blocks is preserved in the
          // scoped scroll so headings never sit under Reader chrome.
          startOffset: 96,
          target: { height: targetRect.height, top: targetRect.top },
        }),
      });
    },
    [resolvedMotion],
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

  const handleDownload = React.useCallback(async () => {
    try {
      window.open(await refreshFileUrl(), "_blank", "noopener,noreferrer");
    } catch {
      notifyActionError();
    }
  }, [notifyActionError, refreshFileUrl]);

  const handlePdfRenderError = React.useCallback(
    (_pageNumber: number, error: unknown) => {
      reportPdfRenderError({
        decoder: pdfDecoderForError(error),
        error_kind: "page_render",
        surface: "page",
      });
    },
    [],
  );

  const handleEffectiveZoomChange = React.useCallback(
    (nextZoom: ReaderEffectiveZoom) => {
      setEffectiveZoom((current) => {
        if (
          current?.documentId === documentId &&
          current.fitMode === nextZoom.fitMode &&
          current.pageNumber === nextZoom.pageNumber &&
          current.zoomPercent === nextZoom.zoomPercent
        ) {
          return current;
        }
        return { ...nextZoom, documentId };
      });
    },
    [documentId],
  );

  const handlePdfInternalDestination = React.useCallback(
    (destination: unknown) => void resolveDestination(destination),
    [resolveDestination],
  );

  const handleAnnotationPreviewChange = React.useCallback(
    (annotationId: string | undefined) => {
      if (annotationId) {
        reportReaderAnnotationMetric("reader_annotation_preview");
      }
      setPreviewAnnotationId(annotationId);
    },
    [],
  );

  const toolbarLabels = React.useMemo<ReaderToolbarLabels>(
    () => ({
      download: t("toolbar.download"),
      closeSearch: t("search.close"),
      closePanel: t("toolbar.closePanel"),
      fit: t("toolbar.fit"),
      fitPage: t("toolbar.fitPage"),
      fitWidth: t("toolbar.fitWidth"),
      hideOutline: t("toolbar.hideOutline"),
      nextPage: t("toolbar.nextPage"),
      nextSearchResult: t("search.next"),
      noSearchResults: t("search.empty"),
      openPanel: t("toolbar.openPanel"),
      page: t("toolbar.page"),
      previousPage: t("toolbar.previousPage"),
      previousSearchResult: t("search.previous"),
      projectContext: (context: string) => t("projects.selector", { context }),
      personalContext: t("projects.personal"),
      pdfView: t("toolbar.pdfView"),
      reflowView: t("toolbar.reflowView"),
      returnToOrigin: returnLabel,
      search: t("toolbar.search"),
      showOutline: t("toolbar.showOutline"),
      zoomIn: t("toolbar.zoomIn"),
      zoomLevel: t("toolbar.zoomLevel"),
      zoomOut: t("toolbar.zoomOut"),
    }),
    [returnLabel, t],
  );

  const document = documentQuery.data;
  const contextPapers = document
    ? [
        {
          document: {
            authors: document.authors,
            document_id: document.document_id,
            journal: document.journal,
            original_filename: document.original_filename,
            title: document.title,
          },
        },
      ]
    : [];
  const contextProjects = activeProject ? [activeProject] : [];
  const title = document?.title ?? document?.original_filename ?? t("untitled");
  const documentMetadata = [
    document?.authors?.[0],
    document?.doi ?? document?.original_filename,
  ]
    .filter(Boolean)
    .join(" · ");
  const desktopPanelOpen =
    panel === "ask" ||
    panel === "annotations" ||
    panel === "translation" ||
    panel === "insights" ||
    panel === "details";
  const useDesktopPanel = useDesktopReaderPanel();
  const showDocumentNavigation = useDocumentNavigationRail();
  const reflowNudge = useReaderMobileReflowNudge(
    document?.processing_status === "completed" &&
      readerView === "pdf" &&
      Boolean(adapter) &&
      !showDocumentNavigation,
  );

  React.useEffect(() => {
    if (document?.processing_status === "completed" && adapter) {
      recordCoreAction();
    }
  }, [adapter, document?.processing_status, recordCoreAction]);

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
    const rawView = searchParams.get("view");
    const rawTranslate = searchParams.get("translate");
    if (rawView && rawView !== "reflow") updateLocation({ view: "pdf" });
    if (rawTranslate && rawTranslate !== "full") {
      updateLocation({ translate: false });
    }
  }, [searchParams, updateLocation]);

  React.useEffect(() => {
    if (panel) {
      lastContextPanelRef.current = panel;
    }
  }, [panel]);

  React.useEffect(() => {
    if (
      translation.state.status !== "streaming" ||
      translation.state.trigger !== "auto" ||
      window.matchMedia("(min-width: 64rem)").matches
    ) {
      return;
    }
    updateLocation({ panel: "translation" });
  }, [translation.state.status, translation.state.trigger, updateLocation]);

  const contextPanelProps: ReaderContextPanelProps = {
    annotationSelection,
    annotationInitialComment,
    annotationAudienceFilter,
    annotationModeFilter,
    annotations: filteredAnnotations,
    annotationsError: annotationsQuery.isError,
    annotationStatusFilter,
    conversationId: conversationSession.activeConversationId,
    conversationSession,
    conversations: conversationsQuery.data?.items ?? [],
    conversationsLoading: conversationsQuery.isPending,
    document,
    context: resolvedContext,
    onContextChange: handleContextChange,
    papers: contextPapers,
    projects: contextProjects,
    onActionError: notifyActionError,
    onAnnotationAudienceFilterChange: (filter) => {
      setAnnotationAudienceFilter(filter);
      setSelectedAnnotationId(undefined);
    },
    onAnnotationModeFilterChange: (mode) => {
      setAnnotationModeFilter(mode);
      setSelectedAnnotationId(undefined);
    },
    onAnnotationDelete: async (id) => {
      await deleteReaderAnnotationThread(id);
      setSelectedAnnotationId(undefined);
      await refreshAnnotations();
    },
    onAnnotationSelect: openAnnotation,
    onAnnotationPreviewChange: handleAnnotationPreviewChange,
    onAnnotationStatusChange: async (id, status) => {
      await updateReaderAnnotationThread(id, { status });
      if (status !== annotationStatusFilter) setSelectedAnnotationId(undefined);
      await refreshAnnotations();
    },
    onAnnotationStatusFilterChange: (status) => {
      setAnnotationStatusFilter(status);
      setSelectedAnnotationId(undefined);
    },
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
      await setConversationPinned(id, pinned);
      await queryClient.invalidateQueries({
        queryKey: conversationKeys.lists(),
      });
    },
    onHighlightCreate: async (comment, color, audience) => {
      await createHighlight(annotationSelection, color, comment, audience);
      setAnnotationInitialComment(undefined);
    },
    onHighlightUpdate: async (id, color) => {
      await updateReaderAnnotationThread(id, { color });
      await refreshAnnotations();
    },
    onPanelChange: (nextPanel) => updateLocation({ panel: nextPanel }),
    onSourceOpen: (source) => {
      const sourcePage = readSourcePage(source.locator);
      if (source.document_id === documentId) {
        updateLocation({ page: sourcePage, panel: "ask" });
      } else {
        const next = new URLSearchParams(locationParamsRef.current.toString());
        next.delete("conversation");
        next.delete("nav");
        if (sourcePage) next.set("page", String(sourcePage));
        else next.delete("page");
        navigation.openContextualRoute({
          destination: `/reader/${source.document_id}${next.size ? `?${next}` : ""}`,
          originKind: "reader",
        });
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
    selectedAnnotationId,
    setReasoningLevel,
    title,
    insightsPanel: (
      <PaperInsightsContainer
        documentId={documentId}
        onPageSelect={(nextPage) =>
          updateLocation({ page: nextPage, view: "pdf" })
        }
        pageCount={pageCount}
        projectId={projectId}
      />
    ),
    translationPanel: (
      <ReaderTranslationPanel
        onAnnotate={(selection, translatedText) => {
          setAnnotationSelection(selection);
          setAnnotationInitialComment(translatedText);
          updateLocation({ panel: "annotations" });
        }}
        onPreferencesChange={translation.updatePreferences}
        onRetry={() => void translation.retry()}
        onTranslate={() => void translation.translate("manual")}
        preferences={translation.effectivePreferences}
        preferencesError={translation.preferencesError}
        preferencesLoading={translation.preferencesLoading}
        preferencesSaving={translation.preferencesSaving}
        state={translation.state}
      />
    ),
  };

  React.useEffect(() => {
    window.document.title = `${title} · Scholens`;
  }, [title]);

  return (
    <WorkspaceShell
      activeConversationId={conversationSession.activeConversationId}
      activeDestination={projectId ? "projects" : "library"}
      actor={actor}
      collapsed={collapsed}
      mobileHeaderCenter={
        <span className="block truncate text-sm font-medium">{title}</span>
      }
      mobileHeaderLeading={
        <IconButton label={returnLabel} onClick={handleReturn} variant="ghost">
          <Icon glyph={BackIcon} size={24} />
        </IconButton>
      }
      onCollapsedChange={setCollapsed}
      onSignOut={handleSignOut}
      showMobileBottomNavigation={false}
      signingOut={signingOut}
      suppressInstallPromotion={reflowNudge.visible}
    >
      <ReadingActivityTracker
        documentId={documentId}
        projectId={projectId}
        rootRef={
          readerView === "pdf"
            ? pdfScrollContainerRef
            : reflowScrollContainerRef
        }
        viewMode={readerView}
      />
      <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
        {document?.processing_status !== "completed" ? (
          <div className="absolute top-3 left-3 z-20 hidden lg:block">
            <IconButton
              label={returnLabel}
              onClick={handleReturn}
              variant="ghost"
            >
              <Icon glyph={BackIcon} size={20} />
            </IconButton>
          </div>
        ) : null}
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
          readerView === "pdf" &&
          !adapter &&
          !adapterError && (
            <div className="m-auto w-full max-w-sm p-6">
              <LoadingState label={t("loadingPdf")} />
            </div>
          )}
        {readerView === "pdf" && adapterError !== undefined && (
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

        {document?.processing_status === "completed" &&
          (readerView === "reflow" || adapter) && (
            <div className="flex min-h-0 flex-1">
              <section className="flex min-w-0 flex-1 flex-col">
                <ReaderToolbar
                  fitMode={fitMode}
                  labels={toolbarLabels}
                  metadata={documentMetadata}
                  onDownload={() => void handleDownload()}
                  onFitModeChange={setFitMode}
                  onToggleOutline={() => {
                    if (showDocumentNavigation) {
                      setReflowOutlineOpen((current) => !current);
                    } else setMobileReflowOutlineOpen(true);
                  }}
                  onOpenPanel={() =>
                    updateLocation({
                      panel: desktopPanelOpen
                        ? null
                        : lastContextPanelRef.current,
                    })
                  }
                  onOpenSearch={() => setSearchOpen(true)}
                  onPageChange={(page) => {
                    setActiveTextSelection(undefined);
                    updateLocation({
                      page: Math.min(Math.max(page, 1), pageCount),
                    });
                  }}
                  onReturn={handleReturn}
                  onViewChange={(nextView) => {
                    closeSearch();
                    setActiveTextSelection(undefined);
                    setMobileReflowOutlineOpen(false);
                    updateLocation({ view: nextView });
                  }}
                  onZoomChange={(nextZoomPercent) => {
                    setCustomZoomPercent(nextZoomPercent);
                    setFitMode("custom");
                  }}
                  pageCount={pageCount}
                  pageNumber={pageNumber}
                  panelOpen={desktopPanelOpen}
                  outlineAvailable={reflowOutline.length > 0}
                  outlineOpen={
                    showDocumentNavigation
                      ? reflowOutlineOpen
                      : mobileReflowOutlineOpen
                  }
                  projectContext={{
                    onChange: (nextProjectId) => {
                      setSelectedAnnotationId(undefined);
                      setActiveTextSelection(undefined);
                      setAnnotationAudienceFilter("all");
                      setAnnotationModeFilter("all");
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
                  translation={{
                    enabled: fullTranslationEnabled,
                    onEnabledChange: (enabled) =>
                      updateLocation({ translate: enabled }),
                    onPreferencesChange: translation.updatePreferences,
                    preferences: translation.effectivePreferences,
                    saving: translation.preferencesSaving,
                    status: fullTranslationStatus,
                  }}
                  view={readerView}
                  zoomPercent={zoomPercent}
                />
                {reflowNudge.visible ? (
                  <ReaderMobileReflowNudge
                    onDismiss={reflowNudge.dismiss}
                    onOpenReflow={() => {
                      reflowNudge.dismiss();
                      closeSearch();
                      setActiveTextSelection(undefined);
                      updateLocation({ view: "reflow" });
                    }}
                  />
                ) : null}
                <div className="flex min-h-0 flex-1">
                  {readerView === "pdf" &&
                    adapter &&
                    showDocumentNavigation && (
                      <ReaderDocumentNavigation label={t("navigation.label")}>
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
                  {readerView === "pdf" && adapter ? (
                    <PdfPage
                      activityScrollContainerRef={pdfScrollContainerRef}
                      activeTextSelection={activeTextSelection}
                      adapter={adapter}
                      annotationNavigation={annotationNavigation}
                      annotationCommentLabel={(count) =>
                        t("annotations.commentMarker", { count })
                      }
                      annotationLinkLabel={t("pdfLink")}
                      annotations={filteredAnnotations}
                      canvasLabel={t("documentCanvas")}
                      fitMode={fitMode}
                      loadingLabel={t("renderingPage")}
                      pageErrorDescription={t("pageErrorDescription")}
                      pageErrorTitle={t("pageErrorTitle")}
                      downloadLabel={t("downloadInstead")}
                      onDownload={handleDownload}
                      onEffectiveZoomChange={handleEffectiveZoomChange}
                      onRenderError={handlePdfRenderError}
                      onActiveTextSelectionChange={
                        handleActiveTextSelectionChange
                      }
                      onAnnotationSelect={openAnnotationInPlace}
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
                        setAnnotationInitialComment(undefined);
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
                      onOpenTranslation={() =>
                        updateLocation({ panel: "translation" })
                      }
                      onTranslateSelection={() => {
                        updateLocation({ panel: "translation" });
                        void translation.translate("manual");
                      }}
                      onInternalDestination={handlePdfInternalDestination}
                      onVisiblePageChange={handleVisiblePageChange}
                      pageCount={pageCount}
                      pageNumber={pageNumber}
                      searchMatches={searchResults}
                      activeSearchMatch={searchResults[searchIndex]}
                      searchQuery={searchQuery}
                      selectedAnnotationId={selectedAnnotationId}
                      previewAnnotationId={previewAnnotationId}
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
                        translate: t("selection.translate"),
                        translating: t("translation.status.translating"),
                        translationFailed: t("translation.errors.title"),
                        viewTranslation: t("panels.translation"),
                      }}
                      translationPreview={
                        activeTextSelection &&
                        translation.state.selection?.selected_text ===
                          activeTextSelection.selected_text &&
                        translation.state.selection.page_number ===
                          activeTextSelection.page_number &&
                        (translation.state.status === "streaming" ||
                          translation.state.status === "completed" ||
                          translation.state.status === "error")
                          ? {
                              status: translation.state.status,
                              text: translation.state.translatedText,
                              errorCode: translation.state.errorCode,
                            }
                          : undefined
                      }
                      sourceTarget={reflowSourceTarget}
                      zoom={customZoomPercent / 100}
                    />
                  ) : null}
                  <AnimatePresence initial={false}>
                    {readerView === "reflow" &&
                    showDocumentNavigation &&
                    reflowOutlineOpen &&
                    reflowOutline.length > 0 ? (
                      <m.aside
                        animate="animate"
                        className="border-line bg-canvas w-64 shrink-0 overflow-y-auto border-r"
                        exit="exit"
                        initial="initial"
                        key="reflow-outline"
                        layout="position"
                        transition={motionTransitions.layout}
                        variants={motionVariants.panel}
                      >
                        <ReaderReflowOutline
                          entries={reflowOutline}
                          label={t("outline.title")}
                          onSelect={scrollToReflowOutlineItem}
                        />
                      </m.aside>
                    ) : null}
                  </AnimatePresence>
                  {readerView === "reflow" ? (
                    <ReaderReflowSurface
                      documentId={documentId}
                      fullTranslationEnabled={fullTranslationEnabled}
                      onOutlineChange={setReflowOutline}
                      scrollContainerRef={reflowScrollContainerRef}
                      onOpenPdfSource={(source) => {
                        setReflowSourceTarget(source);
                        updateLocation({
                          page: source.page_number,
                          view: "pdf",
                        });
                      }}
                      onTranslationStatusChange={setFullTranslationStatus}
                      preferences={translation.effectivePreferences}
                      targetLanguage={
                        translation.effectivePreferences?.target_language ??
                        "zh-CN"
                      }
                      translationCacheVersion={translationCacheVersion}
                    />
                  ) : null}
                </div>
              </section>
              <AnimatePresence initial={false}>
                {useDesktopPanel && desktopPanelOpen && (
                  <m.div
                    animate="animate"
                    className="h-full shrink-0"
                    exit="exit"
                    initial="initial"
                    key="reader-context-panel"
                    layout="position"
                    transition={motionTransitions.layout}
                    variants={motionVariants.panel}
                  >
                    <ReaderContextPanel
                      {...contextPanelProps}
                      className="flex"
                    />
                  </m.div>
                )}
              </AnimatePresence>
            </div>
          )}
      </div>

      <Dialog
        onOpenChange={setMobileReflowOutlineOpen}
        open={
          readerView === "reflow" &&
          !showDocumentNavigation &&
          mobileReflowOutlineOpen
        }
      >
        <DialogContent
          aria-describedby="reader-reflow-outline-description"
          aria-label={t("outline.title")}
          closeLabel={t("closePanel")}
          placement="responsive-bottom"
        >
          <DialogHandle />
          <DialogHeader>
            <DialogTitle>{t("outline.title")}</DialogTitle>
            <DialogDescription id="reader-reflow-outline-description">
              {t("outline.description")}
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="p-0 pb-[max(0.5rem,env(safe-area-inset-bottom))] lg:p-0">
            <ReaderReflowOutline
              entries={reflowOutline}
              label={t("outline.title")}
              onSelect={(id) => {
                setMobileReflowOutlineOpen(false);
                window.requestAnimationFrame(() =>
                  scrollToReflowOutlineItem(id),
                );
              }}
            />
          </DialogBody>
        </DialogContent>
      </Dialog>

      <Sheet
        onOpenChange={(open) => {
          if (!open) updateLocation({ panel: null });
        }}
        open={!useDesktopPanel && desktopPanelOpen}
      >
        <SheetContent
          closeLabel={t("closePanel")}
          placement="visual-full"
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
      const returnTo = currentAppLocation(`/reader/${documentId}`);
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
