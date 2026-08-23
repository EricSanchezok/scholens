"use client";

import {
  LibraryIcon,
  ConfirmIcon,
  DownloadIcon,
  FilterIcon,
  ProjectIcon,
  TagIcon,
  RetryIcon,
  DeleteIcon,
  WarningIcon,
  DismissIcon,
} from "@/design-system/icons/semantic-icons";
import { useFormatter, useTranslations } from "next-intl";
import type { Route } from "next";
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
  Checkbox,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  IconButton,
  OverflowMenuButton,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  SelectContent,
  SelectItem,
  Sheet,
  SheetContent,
  SheetTitle,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  AnimatePresence,
  MotionPresence,
  motionVariants,
} from "@/design-system/motion";
import type { components } from "@/lib/api/generated/schema";
import {
  CollectionToolbar,
  CollectionToolbarButton,
  CollectionToolbarSelectTrigger,
  PaperCollectionWorkbench,
  type PaperCollectionItem,
  type PaperStatus,
} from "@/features/paper-collection";
import { cn } from "@/lib/utilities/cn";
import type { PaperSort, PaperStatus as FilterStatus } from "../library-search";
import type { PaperIngestionRow } from "../use-paper-ingestions";
import { TagManagerDialog, type LibraryTag } from "./tag-manager-dialog";

type Paper = components["schemas"]["LibraryPaperListPaperEntry"];
type PaperList = components["schemas"]["LibraryPaperListResponse"];
type TagItem = LibraryTag;

const PAPER_SORTS: PaperSort[] = [
  "added_desc",
  "added_asc",
  "published_desc",
  "published_asc",
  "title_asc",
  "last_accessed_desc",
];

function paperMetadata(paper: Paper) {
  const overrides = paper.metadata_overrides;
  return {
    authors: overrides.authors ?? paper.document.authors ?? [],
    institutions: overrides.institutions ?? paper.document.institutions ?? [],
    publishDate: overrides.publish_date ?? paper.document.publish_date,
    title:
      overrides.title ??
      paper.document.title ??
      paper.document.original_filename,
  };
}

function SelectionCheckbox({
  checked,
  label,
  onCheckedChange,
}: {
  checked: boolean | "indeterminate";
  label: string;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <Checkbox
      aria-label={label}
      checked={checked}
      onCheckedChange={(value) => onCheckedChange(value === true)}
    />
  );
}

function IngestionThumbnail() {
  return (
    <span
      aria-hidden="true"
      className="border-line bg-subtle grid h-16 w-11 shrink-0 place-items-center rounded-[var(--radius-md)] border text-[0.6875rem] font-semibold"
      data-paper-thumbnail
    >
      PDF
    </span>
  );
}

function PaperActions({
  onDownload,
  onRemove,
  onSelect,
  onTags,
  paper,
  selected = false,
}: {
  onDownload: () => void;
  onRemove: () => void;
  onSelect?: () => void;
  onTags: () => void;
  paper: Paper;
  selected?: boolean;
}) {
  const t = useTranslations("Library.papers.actions");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <OverflowMenuButton
          label={t("open", { title: paperMetadata(paper).title })}
          visibility="contextual"
        />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {onSelect && (
          <DropdownMenuItem onSelect={onSelect}>
            <Icon glyph={ConfirmIcon} size={16} tone="secondary" />
            {selected ? t("deselect") : t("select")}
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={onTags}>
          <Icon glyph={TagIcon} size={16} tone="secondary" />
          {t("tags")}
        </DropdownMenuItem>
        <DropdownMenuItem disabled>
          <Icon glyph={ProjectIcon} size={16} tone="secondary" />
          {t("project")}
          <span className="ml-auto text-xs">{t("notAvailable")}</span>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onDownload}>
          <Icon glyph={DownloadIcon} size={16} tone="secondary" />
          {t("download")}
        </DropdownMenuItem>
        <DropdownMenuItem destructive onSelect={onRemove}>
          <Icon glyph={DeleteIcon} size={16} tone="secondary" />
          {t("remove")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function IngestionDetails({ ingestion }: { ingestion: PaperIngestionRow }) {
  const t = useTranslations("Library.papers.ingestion");
  const active = !["failed"].includes(ingestion.state);
  let description: string;
  if (ingestion.state === "failed") {
    switch (ingestion.errorCode) {
      case "connection_failed":
        description = t("errors.connection_failed");
        break;
      case "paper_upload_unavailable":
        description = t("errors.paper_upload_unavailable");
        break;
      case "invalid_pdf":
        description = t("errors.invalid_pdf");
        break;
      case "jobs_submission_failed":
        description = t("errors.jobs_submission_failed");
        break;
      case "paper_source_pdf_unavailable":
        description = t("errors.paper_source_pdf_unavailable");
        break;
      case "paper_source_unsafe_address":
        description = t("errors.paper_source_unsafe_address");
        break;
      case "document_already_in_library":
      case "document_already_in_project":
        description = t("errors.document_already_in_collection");
        break;
      case "document_upload_in_progress":
        description = t("errors.document_upload_in_progress");
        break;
      case "pdf_encrypted":
        description = t("errors.pdf_encrypted");
        break;
      case "pdf_content_insufficient":
        description = t("errors.pdf_content_insufficient");
        break;
      case "pdf_processing_timeout":
        description = t("errors.pdf_processing_timeout");
        break;
      case "mineru_credential_required":
        description = t("errors.mineru_credential_required");
        break;
      case "mineru_credential_invalid":
        description = t("errors.mineru_credential_invalid");
        break;
      case "mineru_rate_limited":
        description = t("errors.mineru_rate_limited");
        break;
      case "mineru_unavailable":
        description = t("errors.mineru_unavailable");
        break;
      case "mineru_content_insufficient":
        description = t("errors.mineru_content_insufficient");
        break;
      case "mineru_response_unsafe":
        description = t("errors.mineru_response_unsafe");
        break;
      case "paper_ingestion_downloading_failed":
        description = t("errors.paper_ingestion_downloading_failed");
        break;
      case "paper_ingestion_parsing_failed":
        description = t("errors.paper_ingestion_parsing_failed");
        break;
      case "paper_ingestion_metadata_failed":
        description = t("errors.paper_ingestion_metadata_failed");
        break;
      case "paper_ingestion_indexing_failed":
        description = t("errors.paper_ingestion_indexing_failed");
        break;
      case "paper_ingestion_finalizing_failed":
        description = t("errors.paper_ingestion_finalizing_failed");
        break;
      case "paper_ingestion_claim_failed":
        description = t("errors.paper_ingestion_claim_failed");
        break;
      case "service_unavailable":
        description = t("errors.service_unavailable");
        break;
      case "upload_quota_exceeded":
      case "paper_upload_quota_exceeded":
      case "paper_quota_exceeded":
      case "storage_quota_exceeded":
      case "project_owner_quota_exceeded":
      case "project_paper_quota_exceeded":
        description = t("errors.upload_quota_exceeded");
        break;
      case "upload_too_large":
        description = t("errors.upload_too_large");
        break;
      default:
        description = t("errors.unknown");
    }
  } else if (ingestion.state === "retrying") {
    description = t("status.retrying");
  } else if (ingestion.state === "cancelling") {
    description = t("status.cancelling");
  } else {
    description = t(`stage.${ingestion.stage}`);
  }
  return (
    <span className="min-w-0 flex-1">
      <span className="line-clamp-2 text-sm leading-5 font-semibold [overflow-wrap:anywhere] md:line-clamp-1">
        {ingestion.displayName}
      </span>
      <span
        aria-live="polite"
        className="text-secondary mt-1 flex items-center gap-1.5 text-xs"
        role="status"
      >
        {active && (
          <Icon
            className="motion-spinner"
            glyph={RetryIcon}
            size={16}
            tone="secondary"
          />
        )}
        {!active && <Icon glyph={WarningIcon} size={16} tone="danger" />}
        <span className={ingestion.state === "failed" ? "text-danger" : ""}>
          {ingestion.state === "failed"
            ? t("failedAt", { stage: t(`stage.${ingestion.stage}`) })
            : description}
        </span>
      </span>
      {ingestion.state === "failed" && (
        <span className="text-secondary mt-1 block text-xs leading-4">
          {description}
        </span>
      )}
    </span>
  );
}

function IngestionActions({
  ingestion,
  onCancel,
  onRetry,
}: {
  ingestion: PaperIngestionRow;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const t = useTranslations("Library.papers.ingestion");
  if (ingestion.state === "failed") {
    return (
      <div className="flex items-center justify-end gap-1">
        {ingestion.retryable ? (
          <Button onClick={onRetry} size="sm" variant="ghost">
            {ingestion.requiredIntegration === "mineru"
              ? t("connectMineru")
              : t("retry")}
          </Button>
        ) : null}
        <IconButton label={t("remove")} onClick={onCancel} variant="ghost">
          <Icon glyph={DeleteIcon} size={16} tone="secondary" />
        </IconButton>
      </div>
    );
  }
  return (
    <IconButton
      disabled={ingestion.state === "cancelling"}
      label={t("cancel")}
      onClick={onCancel}
      variant="ghost"
    >
      <Icon glyph={DismissIcon} size={16} tone="secondary" />
    </IconButton>
  );
}

function TagFilter({
  active,
  onChange,
  onManage,
  onNeedTags,
  tags,
  tagsLoading,
}: {
  active: string[];
  onChange: (tagIds: string[]) => void;
  onManage: () => void;
  onNeedTags: () => void;
  tags: TagItem[];
  tagsLoading: boolean;
}) {
  const t = useTranslations("Library.papers.filters");
  const renderBody = (manage: () => void) => (
    <div className="grid gap-1">
      {tagsLoading && <LoadingState presentation="inline" />}
      {!tagsLoading &&
        tags.map((tag) => (
          <label
            className="hover:bg-hover flex min-h-10 items-center gap-3 rounded-[var(--radius-md)] px-2 text-sm"
            key={tag.id}
          >
            <SelectionCheckbox
              checked={active.includes(tag.id)}
              label={tag.name}
              onCheckedChange={(checked) =>
                onChange(
                  checked
                    ? [...active, tag.id]
                    : active.filter((id) => id !== tag.id),
                )
              }
            />
            {tag.name}
          </label>
        ))}
      {!tagsLoading && tags.length === 0 && (
        <p className="text-secondary p-3 text-center text-sm">{t("noTags")}</p>
      )}
      <div className="border-line mt-1 border-t pt-1">
        <Button
          className="w-full justify-start"
          onClick={manage}
          variant="ghost"
        >
          <Icon glyph={TagIcon} size={20} tone="secondary" />
          {t("manage")}
        </Button>
      </div>
    </div>
  );
  return (
    <>
      <div className="hidden sm:block">
        <Popover onOpenChange={(open) => open && onNeedTags()}>
          <PopoverTrigger asChild>
            <CollectionToolbarButton
              count={active.length}
              glyph={TagIcon}
              label={t("tags")}
            />
          </PopoverTrigger>
          <PopoverContent>{renderBody(onManage)}</PopoverContent>
        </Popover>
      </div>
      <div className="sm:hidden">
        <MobileTagFilter
          activeCount={active.length}
          onManage={onManage}
          onNeedTags={onNeedTags}
          renderBody={renderBody}
          title={t("tags")}
        />
      </div>
    </>
  );
}

function StatusFilter({
  active,
  onChange,
}: {
  active: FilterStatus[];
  onChange: (statuses: FilterStatus[]) => void;
}) {
  const t = useTranslations("PaperCollection");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <CollectionToolbarButton
          count={active.length}
          glyph={FilterIcon}
          label={t("columns.status")}
        />
      </PopoverTrigger>
      <PopoverContent className="grid gap-1">
        {(["todo", "reading", "completed"] as const).map((status) => (
          <label
            className="hover:bg-hover flex min-h-10 items-center gap-3 rounded-[var(--radius-md)] px-2 text-sm"
            key={status}
          >
            <SelectionCheckbox
              checked={active.includes(status)}
              label={t(`status.${status}`)}
              onCheckedChange={(checked) =>
                onChange(
                  checked
                    ? [...active, status]
                    : active.filter((value) => value !== status),
                )
              }
            />
            {t(`status.${status}`)}
          </label>
        ))}
      </PopoverContent>
    </Popover>
  );
}

function MobileTagFilter({
  activeCount,
  onManage,
  onNeedTags,
  renderBody,
  title,
}: {
  activeCount: number;
  onManage: () => void;
  onNeedTags: () => void;
  renderBody: (onManage: () => void) => React.ReactNode;
  title: string;
}) {
  const t = useTranslations("Library.common");
  const [open, setOpen] = React.useState(false);
  function manageTags() {
    setOpen(false);
    window.setTimeout(onManage, 0);
  }
  return (
    <Sheet onOpenChange={setOpen} open={open}>
      <CollectionToolbarButton
        count={activeCount}
        glyph={TagIcon}
        label={title}
        onClick={() => {
          onNeedTags();
          setOpen(true);
        }}
      />
      <SheetContent
        className="h-auto max-h-[76dvh] rounded-t-[var(--radius-xl)] p-5"
        closeLabel={t("close")}
        side="bottom"
      >
        <SheetTitle className="mb-4 text-lg font-semibold">{title}</SheetTitle>
        {renderBody(manageTags)}
      </SheetContent>
    </Sheet>
  );
}

export function PapersView({
  attentionCount,
  data,
  error,
  ingestions,
  ingestionCount,
  loading,
  loadingMore = false,
  hasMore = false,
  onCreateTag,
  onDeleteTag,
  onDownload,
  onLoadMore = async () => undefined,
  onNeedTags = () => undefined,
  onRemove,
  onRenameTag,
  onReplaceTags,
  onCancelIngestion,
  onRetryIngestion,
  onRetryLoad,
  onSortChange,
  onStatusChange = () => undefined,
  onStatusFilterChange = () => undefined,
  onTagFilterChange,
  search,
  searchResults,
  sort,
  paperCount,
  tagIds,
  statuses = [],
  tags,
  tagsLoading = false,
}: {
  attentionCount: number;
  data?: PaperList;
  error?: unknown;
  ingestions: PaperIngestionRow[];
  ingestionCount: number;
  loading: boolean;
  loadingMore?: boolean;
  hasMore?: boolean;
  onCreateTag: (name: string) => Promise<LibraryTag>;
  onDeleteTag: (tagId: string) => Promise<void>;
  onDownload: (documentId: string) => void;
  onLoadMore?: () => Promise<void>;
  onNeedTags?: () => void;
  onRemove: (documentIds: string[]) => Promise<void>;
  onRenameTag: (tagId: string, name: string) => Promise<LibraryTag>;
  onReplaceTags: (documentIds: string[], tagIds: string[]) => Promise<void>;
  onCancelIngestion: (id: string) => void;
  onRetryIngestion: (id: string) => void;
  onRetryLoad: () => void;
  onSortChange: (sort: PaperSort) => void;
  onStatusChange?: (documentId: string, status: PaperStatus) => void;
  onStatusFilterChange?: (statuses: FilterStatus[]) => void;
  onTagFilterChange: (tagIds: string[]) => void;
  search: React.ReactNode;
  searchResults?: (toolbar: React.ReactNode) => React.ReactNode;
  sort: PaperSort;
  paperCount: number;
  tagIds: string[];
  statuses?: FilterStatus[];
  tags: TagItem[];
  tagsLoading?: boolean;
}) {
  const t = useTranslations("Library.papers");
  const format = useFormatter();
  const [selected, setSelected] = React.useState<string[]>([]);
  const [actionIds, setActionIds] = React.useState<string[]>([]);
  const [initialTagIds, setInitialTagIds] = React.useState<string[]>([]);
  const [tagManagerOpen, setTagManagerOpen] = React.useState(false);
  const [removeOpen, setRemoveOpen] = React.useState(false);
  const [actionPending, setActionPending] = React.useState(false);
  const loadMoreRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const target = loadMoreRef.current;
    if (!target || !hasMore || loadingMore) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void onLoadMore();
      },
      { rootMargin: "600px 0px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMore, loadingMore, onLoadMore]);

  const papers = (data?.items ?? []).flatMap((entry) =>
    entry.entry_type === "paper" ? [entry] : [],
  );
  const hasRows = papers.length > 0 || ingestions.length > 0;
  const paperById = new Map(
    papers.map((paper) => [paper.document.document_id, paper]),
  );
  const workbenchItems: PaperCollectionItem[] = papers.map((paper) => {
    const metadata = paperMetadata(paper);
    const publication = [
      paper.metadata_overrides.journal ?? paper.document.journal,
      paper.metadata_overrides.publisher ?? paper.document.publisher,
      metadata.publishDate
        ? new Date(metadata.publishDate).getUTCFullYear().toString()
        : undefined,
    ]
      .filter(Boolean)
      .join(" · ");
    return {
      abstract:
        paper.metadata_overrides.abstract ??
        paper.document.abstract ??
        undefined,
      addedAt: format.dateTime(new Date(paper.created_at), {
        dateStyle: "medium",
      }),
      authors: metadata.authors,
      doi: paper.metadata_overrides.doi ?? paper.document.doi ?? undefined,
      href: `/reader/${paper.document.document_id}` as Route,
      id: paper.document.document_id,
      inLibrary: true,
      keywords: paper.document.keywords ?? [],
      lastOpened: format.dateTime(new Date(paper.last_accessed_at), {
        dateStyle: "medium",
      }),
      previewUrl: paper.preview_url ?? undefined,
      publication,
      status: paper.status,
      summary: paper.document.summary ?? undefined,
      tags: paper.tags,
      title: metadata.title,
    };
  });

  function toggleOne(documentId: string, checked: boolean) {
    setSelected((current) =>
      checked
        ? [...current, documentId]
        : current.filter((id) => id !== documentId),
    );
  }

  function beginTagEditing(ids: string[]) {
    onNeedTags();
    setActionIds(ids);
    const matching = papers.filter((paper) =>
      ids.includes(paper.document.document_id),
    );
    setInitialTagIds(
      matching.reduce<string[]>(
        (common, paper, index) =>
          index === 0
            ? paper.tags.map((tag) => tag.id)
            : common.filter((id) => paper.tags.some((tag) => tag.id === id)),
        [],
      ),
    );
    setTagManagerOpen(true);
  }

  function beginTagManagement() {
    onNeedTags();
    setActionIds([]);
    setInitialTagIds([]);
    setTagManagerOpen(true);
  }

  function beginRemoval(ids: string[]) {
    setActionIds(ids);
    setRemoveOpen(true);
  }

  async function perform(action: () => Promise<void>) {
    setActionPending(true);
    try {
      await action();
      setSelected([]);
      setRemoveOpen(false);
    } finally {
      setActionPending(false);
    }
  }

  const collectionToolbar = (
    <AnimatePresence initial={false} mode="popLayout">
      {selected.length > 0 ? (
        <MotionPresence
          animate="animate"
          aria-label={t("selectionToolbar")}
          className="border-line bg-subtle flex min-w-0 flex-wrap items-center gap-2 rounded-[var(--radius-lg)] border p-2 sm:pl-4 md:h-11 md:flex-nowrap md:p-1 md:pl-4"
          exit="exit"
          initial="initial"
          key="selection-toolbar"
          role="toolbar"
          variants={motionVariants.swap}
        >
          <span className="mr-auto min-w-0 text-sm font-semibold">
            {t("selected", { count: selected.length })}
          </span>
          <Button
            className="md:h-8 md:min-h-8"
            onClick={() => setSelected([])}
            size="sm"
            variant="ghost"
          >
            {t("clearSelection")}
          </Button>
          <div className="hidden items-center gap-2 sm:flex">
            <Button
              className="md:h-8 md:min-h-8"
              onClick={() => beginTagEditing(selected)}
              size="sm"
              variant="secondary"
            >
              {t("actions.tags")}
            </Button>
            <Button
              className="md:h-8 md:min-h-8"
              disabled
              size="sm"
              title={t("actions.notAvailable")}
              variant="secondary"
            >
              {t("actions.projectUnavailable")}
            </Button>
            <Button
              className="md:h-8 md:min-h-8"
              onClick={() => beginRemoval(selected)}
              size="sm"
              variant="danger"
            >
              {t("actions.remove")}
            </Button>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button className="sm:hidden" size="sm" variant="secondary">
                {t("batchActions")}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => beginTagEditing(selected)}>
                <Icon glyph={TagIcon} size={16} tone="secondary" />
                {t("actions.tags")}
              </DropdownMenuItem>
              <DropdownMenuItem disabled>
                <Icon glyph={ProjectIcon} size={16} tone="secondary" />
                {t("actions.projectUnavailable")}
              </DropdownMenuItem>
              <DropdownMenuItem
                destructive
                onSelect={() => beginRemoval(selected)}
              >
                <Icon glyph={DeleteIcon} size={16} tone="secondary" />
                {t("actions.remove")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </MotionPresence>
      ) : (
        <MotionPresence
          animate="animate"
          className="min-w-0"
          exit="exit"
          initial="initial"
          key="utility-toolbar"
          variants={motionVariants.swap}
        >
          <CollectionToolbar
            controls={
              <>
                <StatusFilter
                  active={statuses}
                  onChange={onStatusFilterChange}
                />
                <TagFilter
                  active={tagIds}
                  onChange={onTagFilterChange}
                  onManage={beginTagManagement}
                  onNeedTags={onNeedTags}
                  tags={tags}
                  tagsLoading={tagsLoading}
                />
                <Select
                  onValueChange={(value) => onSortChange(value as PaperSort)}
                  value={sort}
                >
                  <CollectionToolbarSelectTrigger label={t("sort.label")} />
                  <SelectContent>
                    {PAPER_SORTS.map((option) => (
                      <SelectItem key={option} value={option}>
                        {t(`sort.${option}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </>
            }
            meta={
              data && !searchResults ? (
                <span className="grid justify-items-end text-right">
                  <span className="whitespace-nowrap">
                    {t("count", { count: paperCount })}
                  </span>
                  {ingestionCount > 0 && (
                    <span className="text-xs whitespace-nowrap">
                      {t("ingestionCount", {
                        attentionCount,
                        count: ingestionCount,
                      })}
                    </span>
                  )}
                </span>
              ) : undefined
            }
            search={search}
          />
        </MotionPresence>
      )}
    </AnimatePresence>
  );
  const ingestionList = ingestions.length ? (
    <div className="border-line mb-3 border-y">
      {ingestions.map((ingestion) => (
        <div
          className="border-line-subtle grid min-h-16 grid-cols-[2.75rem_minmax(0,1fr)_auto] items-center gap-3 border-b px-2 py-2 last:border-b-0"
          data-ingestion-row=""
          key={ingestion.id}
        >
          <IngestionThumbnail />
          <IngestionDetails ingestion={ingestion} />
          <IngestionActions
            ingestion={ingestion}
            onCancel={() => onCancelIngestion(ingestion.id)}
            onRetry={() => onRetryIngestion(ingestion.id)}
          />
        </div>
      ))}
    </div>
  ) : null;
  const workbenchVisible =
    !loading && !error && hasRows && workbenchItems.length > 0;
  const paginationControl =
    data && hasMore ? (
      <div className="flex justify-center py-6" ref={loadMoreRef}>
        <Button
          loading={loadingMore}
          onClick={() => void onLoadMore()}
          size="sm"
          variant="ghost"
        >
          {loadingMore ? t("loadingMore") : t("loadMore")}
        </Button>
      </div>
    ) : null;

  return (
    <div
      className={cn(
        "min-w-0",
        (searchResults || workbenchVisible) && "h-full min-h-0 overflow-hidden",
      )}
    >
      {searchResults ? (
        searchResults(collectionToolbar)
      ) : (
        <>
          {!workbenchVisible ? collectionToolbar : null}
          <div
            className={
              workbenchVisible ? "h-full min-h-0 overflow-hidden" : "mt-4"
            }
          >
            {loading && <LoadingState label={t("loading")} />}
            {Boolean(error) && !loading && (
              <AsyncFeedback
                action={{ label: t("tryAgain"), onClick: onRetryLoad }}
                description={t("errorDescription")}
                state="error"
                title={t("errorTitle")}
              />
            )}
            {!loading && !error && data && !hasRows && (
              <AsyncFeedback
                description={t("emptyDescription")}
                icon={LibraryIcon}
                state="empty"
                title={t("emptyTitle")}
              />
            )}
            {!loading && !error && hasRows && (
              <>
                {!workbenchItems.length ? ingestionList : null}
                {workbenchItems.length ? (
                  <PaperCollectionWorkbench
                    actions={(item) => {
                      const paper = paperById.get(item.id);
                      return paper ? (
                        <PaperActions
                          onDownload={() => onDownload(item.id)}
                          onRemove={() => beginRemoval([item.id])}
                          onSelect={() =>
                            toggleOne(item.id, !selected.includes(item.id))
                          }
                          onTags={() => beginTagEditing([item.id])}
                          paper={paper}
                          selected={selected.includes(item.id)}
                        />
                      ) : null;
                    }}
                    beforeTable={ingestionList}
                    items={workbenchItems}
                    leading={(item) => (
                      <SelectionCheckbox
                        checked={selected.includes(item.id)}
                        label={t("select", { title: item.title })}
                        onCheckedChange={(checked) =>
                          toggleOne(item.id, checked)
                        }
                      />
                    )}
                    onStatusChange={(item, status) =>
                      onStatusChange(item.id, status)
                    }
                    onTagClick={(tag) =>
                      onTagFilterChange(
                        tagIds.includes(tag.id) ? tagIds : [...tagIds, tag.id],
                      )
                    }
                    tableFooter={paginationControl}
                    toolbar={collectionToolbar}
                  />
                ) : null}
              </>
            )}
          </div>

          {!workbenchVisible ? paginationControl : null}
        </>
      )}

      <TagManagerDialog
        documentIds={actionIds}
        initialTagIds={initialTagIds}
        onCreate={onCreateTag}
        onDelete={onDeleteTag}
        onOpenChange={setTagManagerOpen}
        onRename={onRenameTag}
        onSave={async (documentIds, nextTagIds) => {
          await onReplaceTags(documentIds, nextTagIds);
          setSelected([]);
        }}
        open={tagManagerOpen}
        tags={tags}
      />
      <AlertDialog onOpenChange={setRemoveOpen} open={removeOpen}>
        <AlertDialogContent>
          <AlertDialogTitle>{t("removeDialog.title")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t("removeDialog.description", { count: actionIds.length })}
          </AlertDialogDescription>
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialogCancel asChild>
              <Button variant="ghost">{t("removeDialog.cancel")}</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                loading={actionPending}
                onClick={(event) => {
                  event.preventDefault();
                  void perform(() => onRemove(actionIds));
                }}
                variant="danger"
              >
                {t("removeDialog.confirm")}
              </Button>
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
