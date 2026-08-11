"use client";

import {
  BookStack,
  Download,
  FilterList,
  Folder,
  Label,
  MoreHoriz,
  RefreshDouble,
  Trash,
  WarningTriangle,
} from "iconoir-react";
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
  Checkbox,
  CursorPagination,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  IconButton,
  Popover,
  PopoverContent,
  PopoverTrigger,
  RadioGroup,
  RadioItem,
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
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import type { PaperSort } from "../library-search";

type Paper = components["schemas"]["LibraryPaperResponse"];
type PaperList = components["schemas"]["LibraryPaperListResponse"];
type TagItem = components["schemas"]["LibraryTagResponse"];
type Project = components["schemas"]["ProjectResponse"];
type Job = components["schemas"]["JobResponse"];

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

function PaperDetails({ paper }: { paper: Paper }) {
  const metadata = paperMetadata(paper);
  const secondary = [
    ...metadata.authors.slice(0, 2),
    ...metadata.institutions.slice(0, 1),
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="min-w-0">
      <div className="truncate text-sm font-semibold">{metadata.title}</div>
      <div className="text-secondary mt-1 truncate text-xs">
        {secondary || paper.document.original_filename}
      </div>
      {paper.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {paper.tags.slice(0, 3).map((tag) => (
            <TagPill key={tag.id} name={tag.name} />
          ))}
        </div>
      )}
    </div>
  );
}

function PaperActions({
  onDownload,
  onProject,
  onRemove,
  onTags,
  paper,
}: {
  onDownload: () => void;
  onProject: () => void;
  onRemove: () => void;
  onTags: () => void;
  paper: Paper;
}) {
  const t = useTranslations("Library.papers.actions");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <IconButton
          label={t("open", { title: paperMetadata(paper).title })}
          variant="ghost"
        >
          <Icon glyph={MoreHoriz} size={20} tone="secondary" />
        </IconButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={onTags}>
          <Icon glyph={Label} size={16} tone="secondary" />
          {t("tags")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onProject}>
          <Icon glyph={Folder} size={16} tone="secondary" />
          {t("project")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onDownload}>
          <Icon glyph={Download} size={16} tone="secondary" />
          {t("download")}
        </DropdownMenuItem>
        <DropdownMenuItem destructive onSelect={onRemove}>
          <Icon glyph={Trash} size={16} tone="secondary" />
          {t("remove")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function IngestionRows({
  jobs,
  onRetry,
  retryingJobId,
}: {
  jobs: Job[];
  onRetry: (jobId: string) => void;
  retryingJobId?: string;
}) {
  const t = useTranslations("Library.papers.ingestion");
  const visible = jobs
    .filter((job) => ["pending", "running", "failed"].includes(job.status))
    .slice(0, 5);
  if (visible.length === 0) return null;
  return (
    <section aria-label={t("section")} className="mt-3 grid gap-2">
      {visible.map((job) => {
        const failed = job.status === "failed";
        return (
          <div
            className={cn(
              "flex min-h-16 items-center gap-3 rounded-[var(--radius-md)] border px-3 py-2",
              failed
                ? "bg-state-danger-bg border-[var(--color-danger-border)]"
                : "bg-state-info-bg border-[var(--color-info-border)]",
            )}
            key={job.id}
          >
            <Icon
              className={cn(
                !failed && "animate-spin motion-reduce:animate-none",
              )}
              glyph={failed ? WarningTriangle : RefreshDouble}
              size={20}
              tone="secondary"
            />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium">
                {failed ? t("failed") : t("processing")}
              </span>
              <span className="text-secondary block truncate text-xs">
                {failed ? t("failedDescription") : t("processingDescription")}
              </span>
            </span>
            {failed && (
              <Button
                loading={retryingJobId === job.id}
                onClick={() => onRetry(job.id)}
                size="sm"
                variant="secondary"
              >
                {t("retry")}
              </Button>
            )}
          </div>
        );
      })}
    </section>
  );
}

function ChoiceDialog({
  description,
  items,
  onOpenChange,
  onSubmit,
  open,
  pending,
  selectionMode = "multiple",
  submitLabel,
  title,
}: {
  description: string;
  items: { id: string; label: string }[];
  onOpenChange: (open: boolean) => void;
  onSubmit: (ids: string[]) => void;
  open: boolean;
  pending: boolean;
  selectionMode?: "single" | "multiple";
  submitLabel: string;
  title: string;
}) {
  const t = useTranslations("Library.common");
  const [selected, setSelected] = React.useState<string[]>([]);
  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) setSelected([]);
    onOpenChange(nextOpen);
  }
  return (
    <Dialog onOpenChange={handleOpenChange} open={open}>
      <DialogContent closeLabel={t("close")} placement="responsive-bottom">
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
        <div className="my-5 max-h-72 overflow-y-auto">
          {selectionMode === "single" ? (
            <RadioGroup
              className="grid gap-1"
              onValueChange={(value) => setSelected([value])}
              value={selected[0]}
            >
              {items.map((item) => (
                <label
                  className="hover:bg-hover flex min-h-11 items-center gap-3 rounded-[var(--radius-md)] px-2 text-sm"
                  key={item.id}
                >
                  <RadioItem value={item.id} />
                  {item.label}
                </label>
              ))}
            </RadioGroup>
          ) : (
            <div className="grid gap-1">
              {items.map((item) => (
                <label
                  className="hover:bg-hover flex min-h-11 items-center gap-3 rounded-[var(--radius-md)] px-2 text-sm"
                  key={item.id}
                >
                  <SelectionCheckbox
                    checked={selected.includes(item.id)}
                    label={item.label}
                    onCheckedChange={(checked) =>
                      setSelected((current) =>
                        checked
                          ? [...current, item.id]
                          : current.filter((id) => id !== item.id),
                      )
                    }
                  />
                  {item.label}
                </label>
              ))}
            </div>
          )}
          {items.length === 0 && (
            <p className="text-secondary py-8 text-center text-sm">
              {t("noOptions")}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={() => handleOpenChange(false)} variant="ghost">
            {t("cancel")}
          </Button>
          <Button
            disabled={selected.length === 0}
            loading={pending}
            onClick={() => onSubmit(selected)}
          >
            {submitLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TagFilter({
  active,
  onChange,
  tags,
}: {
  active: string[];
  onChange: (tagIds: string[]) => void;
  tags: TagItem[];
}) {
  const t = useTranslations("Library.papers.filters");
  const body = (
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
    </div>
  );
  return (
    <>
      <div className="hidden sm:block">
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="secondary">
              <Icon glyph={Label} size={20} tone="secondary" />
              {t("tags")}
              {active.length > 0 && (
                <Badge tone="neutral">{active.length}</Badge>
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent>{body}</PopoverContent>
        </Popover>
      </div>
      <div className="sm:hidden">
        <MobileTagFilter activeCount={active.length} title={t("tags")}>
          {body}
        </MobileTagFilter>
      </div>
    </>
  );
}

function MobileTagFilter({
  activeCount,
  children,
  title,
}: {
  activeCount: number;
  children: React.ReactNode;
  title: string;
}) {
  const t = useTranslations("Library.common");
  const [open, setOpen] = React.useState(false);
  return (
    <Sheet onOpenChange={setOpen} open={open}>
      <Button onClick={() => setOpen(true)} variant="secondary">
        <Icon glyph={FilterList} size={20} tone="secondary" />
        {title}
        {activeCount > 0 && <Badge tone="neutral">{activeCount}</Badge>}
      </Button>
      <SheetContent
        className="inset-x-0 top-auto bottom-0 h-auto max-h-[76dvh] w-full max-w-none rounded-t-[var(--radius-xl)] border-t border-l-0 p-5"
        closeLabel={t("close")}
      >
        <SheetTitle className="mb-4 text-lg font-semibold">{title}</SheetTitle>
        {children}
      </SheetContent>
    </Sheet>
  );
}

export function PapersView({
  data,
  error,
  jobs,
  loading,
  onAddToProject,
  onAssignTags,
  onDownload,
  onNext,
  onPrevious,
  onRemove,
  onRetry,
  onRetryLoad,
  onSortChange,
  onTagFilterChange,
  projects,
  retryingJobId,
  sort,
  tagIds,
  tags,
}: {
  data?: PaperList;
  error?: unknown;
  jobs: Job[];
  loading: boolean;
  onAddToProject: (documentIds: string[], projectId: string) => Promise<void>;
  onAssignTags: (documentIds: string[], tagIds: string[]) => Promise<void>;
  onDownload: (documentId: string) => void;
  onNext: (cursor: string) => void;
  onPrevious: (cursor: string) => void;
  onRemove: (documentIds: string[]) => Promise<void>;
  onRetry: (jobId: string) => void;
  onRetryLoad: () => void;
  onSortChange: (sort: PaperSort) => void;
  onTagFilterChange: (tagIds: string[]) => void;
  projects: Project[];
  retryingJobId?: string;
  sort: PaperSort;
  tagIds: string[];
  tags: TagItem[];
}) {
  const t = useTranslations("Library.papers");
  const format = useFormatter();
  const [selected, setSelected] = React.useState<string[]>([]);
  const [actionIds, setActionIds] = React.useState<string[]>([]);
  const [picker, setPicker] = React.useState<"tags" | "project" | null>(null);
  const [removeOpen, setRemoveOpen] = React.useState(false);
  const [actionPending, setActionPending] = React.useState(false);

  const papers = data?.items ?? [];
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

  function beginChoice(kind: "tags" | "project", ids: string[]) {
    setActionIds(ids);
    setPicker(kind);
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
      setPicker(null);
      setRemoveOpen(false);
    } finally {
      setActionPending(false);
    }
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <TagFilter active={tagIds} onChange={onTagFilterChange} tags={tags} />
        <Select
          onValueChange={(value) => onSortChange(value as PaperSort)}
          value={sort}
        >
          <SelectTrigger
            aria-label={t("sort.label")}
            className="w-auto min-w-44"
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
          <span className="text-secondary ml-auto text-sm">
            {t("count", { count: data.total_count })}
          </span>
        )}
      </div>

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
        {!loading && !error && data && papers.length === 0 && (
          <AsyncFeedback
            description={t("emptyDescription")}
            icon={BookStack}
            state="empty"
            title={t("emptyTitle")}
          />
        )}
        {!loading && !error && papers.length > 0 && (
          <>
            <div className="border-line bg-surface hidden overflow-hidden rounded-[var(--radius-lg)] border md:block">
              <table className="w-full table-fixed border-collapse text-left">
                <thead className="bg-subtle text-secondary text-xs font-medium">
                  <tr>
                    <th className="w-12 px-4 py-3">
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
                  {papers.map((paper) => {
                    const id = paper.document.document_id;
                    const metadata = paperMetadata(paper);
                    return (
                      <tr className="hover:bg-hover" key={id}>
                        <td className="px-4 py-4 align-top">
                          <SelectionCheckbox
                            checked={selected.includes(id)}
                            label={t("select", { title: metadata.title })}
                            onCheckedChange={(checked) =>
                              toggleOne(id, checked)
                            }
                          />
                        </td>
                        <td className="px-2 py-4">
                          <PaperDetails paper={paper} />
                        </td>
                        <td className="text-secondary px-3 py-4 align-top text-sm">
                          {format.dateTime(new Date(paper.created_at), {
                            dateStyle: "medium",
                          })}
                        </td>
                        <td className="text-secondary px-3 py-4 align-top text-sm">
                          {metadata.publishDate
                            ? format.dateTime(new Date(metadata.publishDate), {
                                year: "numeric",
                              })
                            : t("unknown")}
                        </td>
                        <td className="px-2 py-2 align-top">
                          <PaperActions
                            onDownload={() => onDownload(id)}
                            onProject={() => beginChoice("project", [id])}
                            onRemove={() => beginRemoval([id])}
                            onTags={() => beginChoice("tags", [id])}
                            paper={paper}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <ul className="grid gap-2 md:hidden">
              {papers.map((paper) => {
                const id = paper.document.document_id;
                const metadata = paperMetadata(paper);
                return (
                  <li
                    className="border-line bg-surface rounded-[var(--radius-lg)] border p-4"
                    key={id}
                  >
                    <div className="flex items-start gap-3">
                      <SelectionCheckbox
                        checked={selected.includes(id)}
                        label={t("select", { title: metadata.title })}
                        onCheckedChange={(checked) => toggleOne(id, checked)}
                      />
                      <div className="min-w-0 flex-1">
                        <PaperDetails paper={paper} />
                      </div>
                      <PaperActions
                        onDownload={() => onDownload(id)}
                        onProject={() => beginChoice("project", [id])}
                        onRemove={() => beginRemoval([id])}
                        onTags={() => beginChoice("tags", [id])}
                        paper={paper}
                      />
                    </div>
                    <div className="text-secondary mt-3 flex gap-3 pl-8 text-xs">
                      <span>
                        {format.dateTime(new Date(paper.created_at), {
                          dateStyle: "medium",
                        })}
                      </span>
                      <span>
                        {metadata.publishDate
                          ? new Date(metadata.publishDate).getUTCFullYear()
                          : t("unknown")}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        )}
        <IngestionRows
          jobs={jobs}
          onRetry={onRetry}
          retryingJobId={retryingJobId}
        />
      </div>

      {selected.length > 0 && (
        <div className="border-line bg-elevated shadow-overlay sticky bottom-3 z-10 mt-4 flex flex-wrap items-center gap-2 rounded-[var(--radius-lg)] border p-2 pl-4">
          <span className="mr-auto text-sm font-semibold">
            {t("selected", { count: selected.length })}
          </span>
          <Button
            onClick={() => beginChoice("tags", selected)}
            size="sm"
            variant="secondary"
          >
            {t("actions.tags")}
          </Button>
          <Button
            onClick={() => beginChoice("project", selected)}
            size="sm"
            variant="secondary"
          >
            {t("actions.project")}
          </Button>
          <Button
            onClick={() => beginRemoval(selected)}
            size="sm"
            variant="danger"
          >
            {t("actions.remove")}
          </Button>
        </div>
      )}

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

      <ChoiceDialog
        description={t("tagDialog.description", { count: actionIds.length })}
        items={tags.map((tag) => ({ id: tag.id, label: tag.name }))}
        onOpenChange={(open) => !open && setPicker(null)}
        onSubmit={(ids) => void perform(() => onAssignTags(actionIds, ids))}
        open={picker === "tags"}
        pending={actionPending}
        submitLabel={t("tagDialog.submit")}
        title={t("tagDialog.title")}
      />
      <ChoiceDialog
        description={t("projectDialog.description", {
          count: actionIds.length,
        })}
        items={projects.map((project) => ({
          id: project.id,
          label: project.title,
        }))}
        onOpenChange={(open) => !open && setPicker(null)}
        onSubmit={(ids) =>
          void perform(() => onAddToProject(actionIds, ids[0] ?? ""))
        }
        open={picker === "project"}
        pending={actionPending}
        selectionMode="single"
        submitLabel={t("projectDialog.submit")}
        title={t("projectDialog.title")}
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
