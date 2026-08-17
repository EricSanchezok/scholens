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
import Link from "next/link";
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
  CursorPagination,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  IconButton,
  keyboardFocusRing,
  OverflowMenuButton,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetTitle,
} from "@/components/ui";
import { Badge } from "@/components/ui/display";
import { Icon } from "@/design-system/icons/icon";
import {
  AnimatePresence,
  m,
  MotionPresence,
  motionStagger,
  motionTransitions,
  motionVariants,
} from "@/design-system/motion";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import type { PaperSort } from "../library-search";
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

function TagPill({ name }: { name: string }) {
  return (
    <span className="bg-subtle text-secondary inline-flex min-h-7 items-center rounded-full px-2.5 text-xs font-medium">
      {name}
    </span>
  );
}

function PaperThumbnail({ paper }: { paper: Paper }) {
  const [failedPreviewUrl, setFailedPreviewUrl] = React.useState<string | null>(
    null,
  );
  const showPreview =
    Boolean(paper.preview_url) && failedPreviewUrl !== paper.preview_url;

  return (
    <span
      aria-hidden="true"
      className="border-line bg-subtle relative block h-20 w-14 shrink-0 overflow-hidden rounded-[var(--radius-md)] border"
      data-paper-thumbnail
    >
      {showPreview ? (
        // The preview is a short-lived, authenticated object-store URL.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt=""
          className="size-full object-cover object-top"
          onError={() => setFailedPreviewUrl(paper.preview_url)}
          src={paper.preview_url ?? undefined}
        />
      ) : (
        <span className="absolute inset-2.5 flex flex-col gap-1.5 pt-1">
          <span className="border-line w-4/5 border-t" />
          <span className="border-line w-full border-t" />
          <span className="border-line w-3/4 border-t" />
          <span className="border-line mt-auto w-full border-t" />
          <span className="text-secondary text-[0.625rem] font-semibold">
            PDF
          </span>
        </span>
      )}
    </span>
  );
}

function IngestionThumbnail() {
  return (
    <span
      aria-hidden="true"
      className="border-line bg-subtle grid h-20 w-14 shrink-0 place-items-center rounded-[var(--radius-md)] border text-[0.6875rem] font-semibold"
      data-paper-thumbnail
    >
      PDF
    </span>
  );
}

function SelectablePaperThumbnail({
  checked,
  label,
  onCheckedChange,
  paper,
  selectionMode = false,
}: {
  checked: boolean;
  label: string;
  onCheckedChange: (checked: boolean) => void;
  paper: Paper;
  selectionMode?: boolean;
}) {
  return (
    <span className="relative block h-20 w-14 shrink-0">
      <PaperThumbnail paper={paper} />
      <span
        className={cn(
          "motion-control bg-surface absolute inset-0 grid place-items-center rounded-[var(--radius-md)]",
          checked || selectionMode
            ? "pointer-events-auto opacity-100"
            : "pointer-events-none opacity-0 md:pointer-events-auto md:group-focus-within/interactive-row:opacity-100 md:group-hover/interactive-row:opacity-100",
        )}
        data-selection-overlay
      >
        <SelectionCheckbox
          checked={checked}
          label={label}
          onCheckedChange={onCheckedChange}
        />
      </span>
    </span>
  );
}

function PaperDetails({ paper }: { paper: Paper }) {
  const metadata = paperMetadata(paper);
  const secondary = [
    ...metadata.authors.slice(0, 2),
    ...metadata.institutions.slice(0, 1),
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Link
      className={cn(
        "block min-w-0 rounded-[var(--radius-sm)]",
        keyboardFocusRing,
      )}
      href={`/reader/${paper.document.document_id}` as Route}
    >
      <span className="motion-control hover:text-secondary line-clamp-2 block text-left text-sm leading-5 font-semibold [overflow-wrap:anywhere] md:line-clamp-1">
        {metadata.title}
      </span>
      <span className="text-secondary mt-1 block truncate text-xs">
        {secondary || paper.document.original_filename}
      </span>
      {paper.tags.length > 0 && (
        <span className="mt-2 flex flex-wrap gap-1.5">
          {paper.tags.slice(0, 3).map((tag) => (
            <TagPill key={tag.id} name={tag.name} />
          ))}
        </span>
      )}
    </Link>
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

function BoundedMotionTableRow({
  children,
  withMotion,
}: {
  children: React.ReactNode;
  withMotion: boolean;
}) {
  if (!withMotion) return <tr>{children}</tr>;
  return (
    <m.tr
      animate="animate"
      data-motion-list-item
      exit="exit"
      initial="initial"
      layout="position"
      transition={motionTransitions.layout}
      variants={motionVariants.listItem}
    >
      {children}
    </m.tr>
  );
}

function BoundedMotionListItem({
  children,
  withMotion,
}: {
  children: React.ReactNode;
  withMotion: boolean;
}) {
  const className = "min-w-0 py-4";
  if (!withMotion) return <li className={className}>{children}</li>;
  return (
    <m.li
      animate="animate"
      className={className}
      data-motion-list-item
      exit="exit"
      initial="initial"
      layout="position"
      transition={motionTransitions.layout}
      variants={motionVariants.listItem}
    >
      {children}
    </m.li>
  );
}

function TagFilter({
  active,
  onChange,
  onManage,
  tags,
}: {
  active: string[];
  onChange: (tagIds: string[]) => void;
  onManage: () => void;
  tags: TagItem[];
}) {
  const t = useTranslations("Library.papers.filters");
  const renderBody = (manage: () => void) => (
    <div className="grid gap-1">
      {tags.map((tag) => (
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
      {tags.length === 0 && (
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
        <Popover>
          <PopoverTrigger asChild>
            <Button
              className="bg-subtle hover:border-line rounded-full border-transparent"
              variant="secondary"
            >
              <Icon glyph={TagIcon} size={20} tone="secondary" />
              {t("tags")}
              {active.length > 0 && (
                <Badge tone="neutral">{active.length}</Badge>
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent>{renderBody(onManage)}</PopoverContent>
        </Popover>
      </div>
      <div className="sm:hidden">
        <MobileTagFilter
          activeCount={active.length}
          onManage={onManage}
          renderBody={renderBody}
          title={t("tags")}
        />
      </div>
    </>
  );
}

function MobileTagFilter({
  activeCount,
  onManage,
  renderBody,
  title,
}: {
  activeCount: number;
  onManage: () => void;
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
      <Button onClick={() => setOpen(true)} variant="secondary">
        <Icon glyph={FilterIcon} size={20} tone="secondary" />
        {title}
        {activeCount > 0 && <Badge tone="neutral">{activeCount}</Badge>}
      </Button>
      <SheetContent
        className="inset-x-0 top-auto bottom-0 h-auto max-h-[76dvh] w-full max-w-none rounded-t-[var(--radius-xl)] border-t border-l-0 p-5"
        closeLabel={t("close")}
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
  onCreateTag,
  onDeleteTag,
  onDownload,
  onNext,
  onOpenDocument,
  onPrevious,
  onRemove,
  onRenameTag,
  onReplaceTags,
  onCancelIngestion,
  onRetryIngestion,
  onRetryLoad,
  onSortChange,
  onTagFilterChange,
  search,
  sort,
  paperCount,
  tagIds,
  tags,
}: {
  attentionCount: number;
  data?: PaperList;
  error?: unknown;
  ingestions: PaperIngestionRow[];
  ingestionCount: number;
  loading: boolean;
  onCreateTag: (name: string) => Promise<LibraryTag>;
  onDeleteTag: (tagId: string) => Promise<void>;
  onDownload: (documentId: string) => void;
  onOpenDocument: (documentId: string) => void;
  onNext: (cursor: string) => void;
  onPrevious: (cursor: string) => void;
  onRemove: (documentIds: string[]) => Promise<void>;
  onRenameTag: (tagId: string, name: string) => Promise<LibraryTag>;
  onReplaceTags: (documentIds: string[], tagIds: string[]) => Promise<void>;
  onCancelIngestion: (id: string) => void;
  onRetryIngestion: (id: string) => void;
  onRetryLoad: () => void;
  onSortChange: (sort: PaperSort) => void;
  onTagFilterChange: (tagIds: string[]) => void;
  search: React.ReactNode;
  sort: PaperSort;
  paperCount: number;
  tagIds: string[];
  tags: TagItem[];
}) {
  const t = useTranslations("Library.papers");
  const format = useFormatter();
  const [selected, setSelected] = React.useState<string[]>([]);
  const [actionIds, setActionIds] = React.useState<string[]>([]);
  const [initialTagIds, setInitialTagIds] = React.useState<string[]>([]);
  const [tagManagerOpen, setTagManagerOpen] = React.useState(false);
  const [removeOpen, setRemoveOpen] = React.useState(false);
  const [actionPending, setActionPending] = React.useState(false);

  const papers = (data?.items ?? []).flatMap((entry) =>
    entry.entry_type === "paper" ? [entry] : [],
  );
  const hasRows = papers.length > 0 || ingestions.length > 0;
  const allSelected =
    papers.length > 0 &&
    papers.every((paper) => selected.includes(paper.document.document_id));

  function toggleAll(checked: boolean) {
    setSelected(
      checked ? papers.map((paper) => paper.document.document_id) : [],
    );
  }

  function toggleOne(documentId: string, checked: boolean) {
    setSelected((current) =>
      checked
        ? [...current, documentId]
        : current.filter((id) => id !== documentId),
    );
  }

  function beginTagEditing(ids: string[]) {
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

  return (
    <>
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
            className="grid min-w-0 gap-2 md:grid-cols-[minmax(12rem,1fr)_auto_auto_auto] md:items-center"
            exit="exit"
            initial="initial"
            key="utility-toolbar"
            variants={motionVariants.swap}
          >
            <div className="min-w-0">{search}</div>
            <div className="flex min-w-0 items-center gap-2 md:contents">
              <TagFilter
                active={tagIds}
                onChange={onTagFilterChange}
                onManage={beginTagManagement}
                tags={tags}
              />
              <Select
                onValueChange={(value) => onSortChange(value as PaperSort)}
                value={sort}
              >
                <SelectTrigger
                  aria-label={t("sort.label")}
                  className="min-w-0 flex-1 md:w-auto md:min-w-44 md:flex-none"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PAPER_SORTS.map((option) => (
                    <SelectItem key={option} value={option}>
                      {t(`sort.${option}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {data && (
                <span className="text-secondary ml-auto shrink-0 text-right text-sm md:ml-2">
                  {t("count", { count: paperCount })}
                  {ingestionCount > 0 && (
                    <span className="block text-xs sm:inline">
                      {t("ingestionCount", {
                        attentionCount,
                        count: ingestionCount,
                      })}
                    </span>
                  )}
                </span>
              )}
            </div>
          </MotionPresence>
        )}
      </AnimatePresence>

      <div className="mt-4">
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
            <div className="border-line group/table hidden border-y md:block">
              <table className="w-full table-fixed border-collapse text-left">
                <thead className="text-muted text-xs font-medium">
                  <tr>
                    <th className="w-20 px-3 py-3">
                      <span
                        className={cn(
                          "motion-control grid w-14 place-items-center",
                          selected.length > 0
                            ? "opacity-100"
                            : "opacity-0 group-focus-within/table:opacity-100 group-hover/table:opacity-100",
                        )}
                      >
                        <SelectionCheckbox
                          checked={
                            allSelected
                              ? true
                              : selected.length > 0
                                ? "indeterminate"
                                : false
                          }
                          label={t("selectAll")}
                          onCheckedChange={toggleAll}
                        />
                      </span>
                    </th>
                    <th className="px-2 py-3 font-medium">
                      {t("columns.paper")}
                    </th>
                    <th className="w-36 px-3 py-3 font-medium">
                      {t("columns.added")}
                    </th>
                    <th className="w-32 px-3 py-3 font-medium">
                      {t("columns.published")}
                    </th>
                    <th className="w-14 px-2 py-3">
                      <span className="sr-only">{t("columns.actions")}</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-line divide-y">
                  <AnimatePresence initial={false}>
                    {ingestions.map((ingestion, index) => (
                      <BoundedMotionTableRow
                        key={ingestion.id}
                        withMotion={index < motionStagger.maximumChildren}
                      >
                        <td className="px-3 py-3 align-middle">
                          <IngestionThumbnail />
                        </td>
                        <td className="px-2 py-3 align-middle">
                          <IngestionDetails ingestion={ingestion} />
                        </td>
                        <td className="text-secondary px-3 py-4 align-top text-sm">
                          {format.dateTime(new Date(ingestion.createdAt), {
                            dateStyle: "medium",
                          })}
                        </td>
                        <td className="text-secondary px-3 py-4 align-top text-sm">
                          {t("ingestion.pending")}
                        </td>
                        <td className="px-2 py-2 align-top">
                          <IngestionActions
                            ingestion={ingestion}
                            onCancel={() => onCancelIngestion(ingestion.id)}
                            onRetry={() => onRetryIngestion(ingestion.id)}
                          />
                        </td>
                      </BoundedMotionTableRow>
                    ))}
                  </AnimatePresence>
                  {papers.map((paper) => {
                    const id = paper.document.document_id;
                    const metadata = paperMetadata(paper);
                    return (
                      <tr
                        className="motion-control group/interactive-row hover:bg-hover focus-within:bg-hover active:bg-pressed"
                        key={id}
                      >
                        <td className="px-3 py-3 align-middle">
                          <SelectablePaperThumbnail
                            checked={selected.includes(id)}
                            label={t("select", { title: metadata.title })}
                            onCheckedChange={(checked) =>
                              toggleOne(id, checked)
                            }
                            paper={paper}
                            selectionMode={selected.length > 0}
                          />
                        </td>
                        <td className="px-2 py-3 align-middle">
                          <PaperDetails paper={paper} />
                        </td>
                        <td
                          className="text-secondary cursor-pointer px-3 py-3 align-middle text-sm"
                          onClick={() => onOpenDocument(id)}
                        >
                          {format.dateTime(new Date(paper.created_at), {
                            dateStyle: "medium",
                          })}
                        </td>
                        <td
                          className="text-secondary cursor-pointer px-3 py-3 align-middle text-sm"
                          onClick={() => onOpenDocument(id)}
                        >
                          {metadata.publishDate
                            ? format.dateTime(new Date(metadata.publishDate), {
                                year: "numeric",
                              })
                            : t("unknown")}
                        </td>
                        <td className="px-2 py-2 align-middle">
                          <PaperActions
                            onDownload={() => onDownload(id)}
                            onRemove={() => beginRemoval([id])}
                            onTags={() => beginTagEditing([id])}
                            paper={paper}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <ul className="divide-line border-line min-w-0 divide-y border-y md:hidden">
              <AnimatePresence initial={false}>
                {ingestions.map((ingestion, index) => (
                  <BoundedMotionListItem
                    key={ingestion.id}
                    withMotion={index < motionStagger.maximumChildren}
                  >
                    <div className="flex items-start gap-3">
                      <IngestionThumbnail />
                      <div className="min-w-0 flex-1">
                        <IngestionDetails ingestion={ingestion} />
                      </div>
                      <IngestionActions
                        ingestion={ingestion}
                        onCancel={() => onCancelIngestion(ingestion.id)}
                        onRetry={() => onRetryIngestion(ingestion.id)}
                      />
                    </div>
                    <div className="text-secondary mt-3 flex gap-3 pl-[4.25rem] text-xs">
                      <span>
                        {format.dateTime(new Date(ingestion.createdAt), {
                          dateStyle: "medium",
                        })}
                      </span>
                      <span>{t("ingestion.pending")}</span>
                    </div>
                  </BoundedMotionListItem>
                ))}
              </AnimatePresence>
              {papers.map((paper) => {
                const id = paper.document.document_id;
                const metadata = paperMetadata(paper);
                return (
                  <li
                    className="motion-control group/interactive-row hover:bg-hover focus-within:bg-hover active:bg-pressed min-w-0 rounded-[var(--radius-lg)] px-2 py-4"
                    key={id}
                  >
                    <div className="grid min-w-0 grid-cols-[3.5rem_minmax(0,1fr)_auto] items-start gap-3">
                      <SelectablePaperThumbnail
                        checked={selected.includes(id)}
                        label={t("select", { title: metadata.title })}
                        onCheckedChange={(checked) => toggleOne(id, checked)}
                        paper={paper}
                        selectionMode={selected.length > 0}
                      />
                      <div className="min-w-0" data-paper-content>
                        <PaperDetails paper={paper} />
                        <div
                          className="text-secondary mt-2 flex min-w-0 flex-wrap items-center gap-2 text-xs"
                          data-paper-mobile-metadata
                        >
                          <span>
                            {format.dateTime(new Date(paper.created_at), {
                              dateStyle: "medium",
                            })}
                          </span>
                          <span aria-hidden="true">·</span>
                          <span>
                            {metadata.publishDate
                              ? new Date(metadata.publishDate).getUTCFullYear()
                              : t("unknown")}
                          </span>
                        </div>
                      </div>
                      <PaperActions
                        onDownload={() => onDownload(id)}
                        onRemove={() => beginRemoval([id])}
                        onSelect={() => toggleOne(id, !selected.includes(id))}
                        onTags={() => beginTagEditing([id])}
                        paper={paper}
                        selected={selected.includes(id)}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>

      {data && (data.previous_cursor || data.next_cursor) && (
        <div className="mt-6 flex justify-end">
          <CursorPagination
            nextDisabled={!data.next_cursor}
            nextLabel={t("next")}
            onNext={() => data.next_cursor && onNext(data.next_cursor)}
            onPrevious={() =>
              data.previous_cursor && onPrevious(data.previous_cursor)
            }
            previousDisabled={!data.previous_cursor}
            previousLabel={t("previous")}
          />
        </div>
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
    </>
  );
}
