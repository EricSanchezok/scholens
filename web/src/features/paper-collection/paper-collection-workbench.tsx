"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Route } from "next";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  IconButton,
  keyboardFocusRing,
  useToast,
} from "@/components/ui";
import {
  ClosePanelIcon,
  OpenPanelIcon,
  OutlineIcon,
} from "@/design-system/icons/semantic-icons";
import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import {
  defaultPaperListPreferences,
  paperListPreferencesKey,
  paperListPreferencesQuery,
  updatePaperListPreferences,
  type PaperCollectionColumn,
  type PaperListPreferences,
  type PaperStatus,
} from "./api";

export type PaperCollectionTag = {
  id: string;
  name: string;
  color?: string | null;
};

export type PaperCollectionItem = {
  id: string;
  title: string;
  authors: string[];
  publication?: string;
  lastOpened?: string;
  addedAt?: string;
  doi?: string;
  status?: PaperStatus;
  tags: PaperCollectionTag[];
  inLibrary: boolean;
  previewUrl?: string;
  abstract?: string;
  summary?: string;
  keywords: string[];
  snippet?: string;
  href: Route;
};

const COLUMN_WIDTHS: Record<PaperCollectionColumn, string> = {
  status: "6rem",
  tags: "10rem",
  authors: "11rem",
  publication: "8.5rem",
  last_opened: "7rem",
  added_at: "7rem",
  doi: "10rem",
};

const ALL_COLUMNS = Object.keys(COLUMN_WIDTHS) as PaperCollectionColumn[];

function useElementWidth(ref: React.RefObject<HTMLElement | null>) {
  const [width, setWidth] = React.useState<number>();
  React.useEffect(() => {
    const node = ref.current;
    if (!node) return;
    setWidth(node.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

function PaperPreviewImage({
  className,
  previewUrl,
  variant,
}: {
  className: string;
  previewUrl?: string;
  variant: "detail" | "thumbnail";
}) {
  const [failedUrl, setFailedUrl] = React.useState<string>();
  const showImage = Boolean(previewUrl && previewUrl !== failedUrl);
  return (
    <span
      aria-hidden="true"
      className={cn(
        "border-line bg-subtle relative block shrink-0 overflow-hidden rounded-[var(--radius-sm)] border",
        className,
      )}
      data-paper-preview-image={variant}
      data-paper-thumbnail={variant === "thumbnail" ? "" : undefined}
    >
      {showImage ? (
        // Authenticated short-lived preview URL returned by the API.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt=""
          className="size-full object-cover object-top"
          onError={() => setFailedUrl(previewUrl)}
          src={previewUrl}
        />
      ) : (
        <span
          className="absolute inset-2 flex flex-col gap-1 pt-1"
          data-paper-image-fallback=""
        >
          <span className="border-line w-4/5 border-t" />
          <span className="border-line w-full border-t" />
          <span className="border-line w-3/4 border-t" />
          <span className="text-muted mt-auto text-[0.5625rem] font-semibold">
            PDF
          </span>
        </span>
      )}
    </span>
  );
}

function PaperThumbnail({ item }: { item: PaperCollectionItem }) {
  return (
    <PaperPreviewImage
      className="h-[52px] w-9"
      previewUrl={item.previewUrl}
      variant="thumbnail"
    />
  );
}

function StatusControl({
  item,
  onChange,
  personalLabels,
}: {
  item: PaperCollectionItem;
  onChange?: (item: PaperCollectionItem, status: PaperStatus) => void;
  personalLabels: boolean;
}) {
  const t = useTranslations("PaperCollection");
  if (!item.inLibrary || !item.status) {
    return (
      <span className="text-secondary text-xs">{t("status.notInLibrary")}</span>
    );
  }
  if (!onChange) {
    return (
      <span className="bg-subtle inline-flex h-7 items-center rounded-full px-2 text-xs">
        {t(`status.${item.status}`)}
      </span>
    );
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          aria-label={t(
            personalLabels
              ? "status.personalControlLabel"
              : "status.controlLabel",
            { title: item.title },
          )}
          className="h-7 min-h-7 rounded-full px-2 text-xs"
          variant="secondary"
        >
          {t(`status.${item.status}`)}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {(["todo", "reading", "completed"] as const).map((status) => (
          <DropdownMenuItem
            disabled={!onChange || status === item.status}
            key={status}
            onSelect={() => onChange?.(item, status)}
          >
            {t(`status.${status}`)}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function TagButtons({
  item,
  onTagClick,
}: {
  item: PaperCollectionItem;
  onTagClick?: (tag: PaperCollectionTag) => void;
}) {
  const t = useTranslations("PaperCollection");
  if (!item.inLibrary) return <span className="text-secondary text-xs">—</span>;
  return (
    <span className="flex min-w-0 items-center gap-1 overflow-hidden">
      {item.tags.slice(0, 2).map((tag) =>
        onTagClick ? (
          <button
            className={cn(
              "bg-subtle hover:bg-hover max-w-20 truncate rounded-[var(--radius-sm)] px-1.5 py-1 text-[0.6875rem] font-medium",
              keyboardFocusRing,
            )}
            key={tag.id}
            onClick={() => onTagClick(tag)}
            type="button"
          >
            {tag.name}
          </button>
        ) : (
          <span
            className="bg-subtle max-w-20 truncate rounded-[var(--radius-sm)] px-1.5 py-1 text-[0.6875rem] font-medium"
            key={tag.id}
          >
            {tag.name}
          </span>
        ),
      )}
      {item.tags.length > 2 ? (
        <span
          aria-label={t("moreTags", { count: item.tags.length - 2 })}
          className="text-secondary text-[0.6875rem]"
        >
          +{item.tags.length - 2}
        </span>
      ) : null}
    </span>
  );
}

function ColumnManager({
  preferences,
  update,
}: {
  preferences: PaperListPreferences;
  update: (
    updater: (current: PaperListPreferences) => PaperListPreferences,
  ) => void;
}) {
  const t = useTranslations("PaperCollection");
  function toggle(column: PaperCollectionColumn, checked: boolean) {
    update((current) => ({
      ...current,
      visible_columns: checked
        ? [...current.visible_columns, column]
        : current.visible_columns.filter((value) => value !== column),
    }));
  }
  function move(column: PaperCollectionColumn, delta: -1 | 1) {
    update((preferences) => {
      const current = [...preferences.visible_columns];
      const index = current.indexOf(column);
      const target = index + delta;
      if (index < 0 || target < 0 || target >= current.length)
        return preferences;
      const sourceValue = current[index];
      const targetValue = current[target];
      if (!sourceValue || !targetValue) return preferences;
      current[index] = targetValue;
      current[target] = sourceValue;
      return { ...preferences, visible_columns: current };
    });
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          aria-label={t("columnsMenu.label")}
          className="hidden sm:inline-flex"
          size="sm"
          variant="ghost"
        >
          <Icon glyph={OutlineIcon} size={20} />
          <span className="hidden xl:inline">{t("columnsMenu.label")}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>{t("columnsMenu.title")}</DropdownMenuLabel>
        {ALL_COLUMNS.map((column) => {
          const checked = preferences.visible_columns.includes(column);
          const visibleIndex = preferences.visible_columns.indexOf(column);
          const columnLabel = t(`columns.${column}`);
          return (
            <React.Fragment key={column}>
              <DropdownMenuCheckboxItem
                checked={checked}
                onCheckedChange={(value) => toggle(column, value === true)}
                onSelect={(event) => event.preventDefault()}
              >
                {columnLabel}
              </DropdownMenuCheckboxItem>
              {checked ? (
                <DropdownMenuGroup className="flex justify-end gap-1 px-2 pb-1">
                  <DropdownMenuItem
                    aria-label={t("columnsMenu.moveUpColumn", {
                      column: columnLabel,
                    })}
                    className="min-h-8 px-2 text-xs"
                    disabled={visibleIndex === 0}
                    onSelect={(event) => {
                      event.preventDefault();
                      move(column, -1);
                    }}
                  >
                    {t("columnsMenu.moveUp")}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    aria-label={t("columnsMenu.moveDownColumn", {
                      column: columnLabel,
                    })}
                    className="min-h-8 px-2 text-xs"
                    disabled={
                      visibleIndex === preferences.visible_columns.length - 1
                    }
                    onSelect={(event) => {
                      event.preventDefault();
                      move(column, 1);
                    }}
                  >
                    {t("columnsMenu.moveDown")}
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              ) : null}
            </React.Fragment>
          );
        })}
        <DropdownMenuSeparator />
        <DropdownMenuItem>{t("columnsMenu.done")}</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const previewMarkdownComponents: Components = {
  h1: ({ children }) => (
    <h4 className="text-foreground text-sm leading-5 font-semibold">
      {children}
    </h4>
  ),
  h2: ({ children }) => (
    <h4 className="text-foreground text-sm leading-5 font-semibold">
      {children}
    </h4>
  ),
  h3: ({ children }) => (
    <h4 className="text-foreground text-sm leading-5 font-semibold">
      {children}
    </h4>
  ),
  p: ({ children }) => <p className="text-pretty">{children}</p>,
  ul: ({ children }) => (
    <ul className="marker:text-muted list-disc space-y-1.5 pl-4">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="marker:text-muted list-decimal space-y-1.5 pl-4">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="pl-0.5">{children}</li>,
  strong: ({ children }) => (
    <strong className="text-foreground font-semibold">{children}</strong>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-line-strong border-l pl-3">
      {children}
    </blockquote>
  ),
  a: ({ children, href }) => (
    <a
      className="decoration-line-strong hover:decoration-foreground underline underline-offset-2"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="bg-surface rounded-[var(--radius-xs)] px-1 py-0.5 text-[0.9em] [overflow-wrap:anywhere]">
      {children}
    </code>
  ),
};

function Preview({
  item,
  onClose,
  onStatusChange,
  onTagClick,
  personalLabels,
}: {
  item: PaperCollectionItem;
  onClose: () => void;
  onStatusChange?: (item: PaperCollectionItem, status: PaperStatus) => void;
  onTagClick?: (tag: PaperCollectionTag) => void;
  personalLabels: boolean;
}) {
  const t = useTranslations("PaperCollection");
  return (
    <aside
      aria-label={t("preview.label")}
      className="border-line-subtle bg-subtle max-h-[min(42.5rem,calc(100dvh-12rem))] min-w-0 overflow-y-auto border-l px-5 pb-5"
      data-paper-collection-preview=""
    >
      <div className="flex h-10 items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t("preview.label")}</h2>
        <IconButton
          label={t("preview.close")}
          onClick={onClose}
          variant="ghost"
        >
          <Icon glyph={ClosePanelIcon} size={20} />
        </IconButton>
      </div>
      <PaperPreviewImage
        className="bg-surface mt-3 h-36 w-24"
        previewUrl={item.previewUrl}
        variant="detail"
      />
      <h3 className="mt-4 text-base leading-6 font-semibold [overflow-wrap:anywhere]">
        {item.title}
      </h3>
      <p className="text-secondary mt-2 text-xs leading-5">
        {item.authors.join(" · ") || t("preview.unknownAuthors")}
      </p>
      <p className="text-secondary mt-1 text-xs">
        {item.publication || t("unknown")}
      </p>
      {item.doi ? (
        <p className="text-secondary mt-2 text-xs [overflow-wrap:anywhere]">
          <span className="text-muted font-medium">{t("columns.doi")}</span>{" "}
          {item.doi}
        </p>
      ) : null}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-muted text-xs">
          {t(personalLabels ? "columns.personalStatus" : "columns.status")}
        </span>
        <StatusControl
          item={item}
          onChange={onStatusChange}
          personalLabels={personalLabels}
        />
      </div>
      <div className="mt-3 flex flex-wrap gap-1">
        <TagButtons item={item} onTagClick={onTagClick} />
      </div>
      <p className="text-secondary mt-5 text-xs font-medium">
        {t(item.summary ? "preview.summary" : "preview.abstract")}
      </p>
      <div
        className="text-secondary mt-2 text-sm leading-6 [overflow-wrap:anywhere] [&>*+*]:mt-3"
        data-paper-preview-markdown=""
      >
        <ReactMarkdown
          components={previewMarkdownComponents}
          remarkPlugins={[remarkGfm]}
          skipHtml
        >
          {item.summary || item.abstract || t("preview.noAbstract")}
        </ReactMarkdown>
      </div>
      {item.keywords.length ? (
        <p className="text-secondary mt-5 text-xs leading-5">
          <span className="font-medium">{t("preview.keywords")}</span>{" "}
          {item.keywords.join(" · ")}
        </p>
      ) : null}
    </aside>
  );
}

export function PaperCollectionWorkbench({
  actions,
  beforeTable,
  items,
  leading,
  onStatusChange,
  onTagClick,
  personalLabels = false,
  toolbar,
}: {
  actions?: (item: PaperCollectionItem) => React.ReactNode;
  beforeTable?: React.ReactNode;
  items: PaperCollectionItem[];
  leading?: (item: PaperCollectionItem) => React.ReactNode;
  onStatusChange?: (item: PaperCollectionItem, status: PaperStatus) => void;
  onTagClick?: (tag: PaperCollectionTag) => void;
  personalLabels?: boolean;
  toolbar?: React.ReactNode;
}) {
  const t = useTranslations("PaperCollection");
  const toast = useToast();
  const queryClient = useQueryClient();
  const preferencesQuery = useQuery(paperListPreferencesQuery());
  const preferences = preferencesQuery.data ?? defaultPaperListPreferences;
  const latestPreferencesRef = React.useRef(preferences);
  const confirmedPreferencesRef = React.useRef(preferencesQuery.data);
  const latestMutationSequenceRef = React.useRef(0);
  const mutation = useMutation({
    mutationFn: ({ next }: { next: PaperListPreferences; sequence: number }) =>
      updatePaperListPreferences(next),
    scope: { id: paperListPreferencesKey.join(":") },
    onMutate: async ({ next }) => {
      await queryClient.cancelQueries({ queryKey: paperListPreferencesKey });
      queryClient.setQueryData(paperListPreferencesKey, next);
    },
    onError: (_error, variables) => {
      if (variables.sequence === latestMutationSequenceRef.current) {
        const confirmed = confirmedPreferencesRef.current;
        if (confirmed) {
          latestPreferencesRef.current = confirmed;
          queryClient.setQueryData(paperListPreferencesKey, confirmed);
        } else {
          latestPreferencesRef.current = defaultPaperListPreferences;
          queryClient.setQueryData(
            paperListPreferencesKey,
            defaultPaperListPreferences,
          );
          void queryClient.invalidateQueries({
            exact: true,
            queryKey: paperListPreferencesKey,
          });
        }
      }
      toast.notify({ title: t("preferencesSaveFailed") });
    },
    onSuccess: (next, variables) => {
      confirmedPreferencesRef.current = next;
      if (variables.sequence === latestMutationSequenceRef.current) {
        latestPreferencesRef.current = next;
        queryClient.setQueryData(paperListPreferencesKey, next);
      }
    },
  });
  React.useEffect(() => {
    if (!mutation.isPending && preferencesQuery.data) {
      latestPreferencesRef.current = preferencesQuery.data;
      confirmedPreferencesRef.current = preferencesQuery.data;
    }
  }, [mutation.isPending, preferencesQuery.data]);
  const mutatePreferences = React.useCallback(
    (update: (current: PaperListPreferences) => PaperListPreferences) => {
      const current = latestPreferencesRef.current;
      const next = update(current);
      if (next === current) return;
      latestPreferencesRef.current = next;
      const sequence = latestMutationSequenceRef.current + 1;
      latestMutationSequenceRef.current = sequence;
      mutation.mutate({ next, sequence });
    },
    [mutation],
  );
  const rootRef = React.useRef<HTMLDivElement>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const width = useElementWidth(rootRef);
  const measuredWidth = width ?? 0;
  const [previewId, setPreviewId] = React.useState<string>();
  const [hoveredPreviewId, setHoveredPreviewId] = React.useState<string>();
  const preview =
    items.find((item) => item.id === hoveredPreviewId) ??
    items.find((item) => item.id === previewId) ??
    items[0];
  const previewVisible = Boolean(
    preview && preferences.preview_open && measuredWidth >= 1040,
  );
  const listWidth = Math.max(0, measuredWidth - (previewVisible ? 384 : 0));
  const effectiveColumns = React.useMemo(() => {
    if (listWidth >= 1200) return preferences.visible_columns;
    if (listWidth >= 1020)
      return preferences.visible_columns.filter(
        (column) => !["last_opened", "added_at", "doi"].includes(column),
      );
    if (listWidth >= 900)
      return preferences.visible_columns.filter((column) =>
        ["status", "tags", "publication"].includes(column),
      );
    if (listWidth >= 700)
      return preferences.visible_columns.filter((column) =>
        ["status", "tags"].includes(column),
      );
    return preferences.visible_columns.filter((column) => column === "status");
  }, [listWidth, preferences.visible_columns]);
  const compact = listWidth < 640;
  const columnCount = compact
    ? 2 + (actions ? 1 : 0)
    : 1 + effectiveColumns.length + (leading ? 1 : 0) + (actions ? 1 : 0);
  // TanStack Virtual owns a mutable scroll controller by design.
  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: items.length,
    estimateSize: () => 64,
    getScrollElement: () => scrollRef.current,
    overscan: 8,
  });
  const gridTemplateColumns = `${leading ? "3rem " : ""}minmax(18rem,1fr) ${effectiveColumns.map((column) => COLUMN_WIDTHS[column]).join(" ")} ${actions ? "2.75rem" : ""}`;
  const virtualItems = rowVirtualizer.getVirtualItems();
  const renderedVirtualItems = width === undefined ? [] : virtualItems;
  return (
    <div className="min-w-0" ref={rootRef}>
      <div
        className="mb-3 flex min-h-11 min-w-0 items-center gap-2"
        data-paper-collection-toolbar=""
      >
        {toolbar ? (
          <div className="min-w-0 flex-1">{toolbar}</div>
        ) : (
          <div className="flex-1" />
        )}
        <div className="hidden shrink-0 items-center gap-1 sm:flex">
          {!preferences.preview_open && measuredWidth >= 1040 ? (
            <Button
              aria-label={t("preview.open")}
              onClick={() =>
                mutatePreferences((current) => ({
                  ...current,
                  preview_open: true,
                }))
              }
              size="sm"
              variant="ghost"
            >
              <Icon glyph={OpenPanelIcon} size={20} />
              <span className="hidden xl:inline">{t("preview.open")}</span>
            </Button>
          ) : null}
          <ColumnManager preferences={preferences} update={mutatePreferences} />
        </div>
      </div>
      {beforeTable}
      <div
        className={cn(
          "border-line grid min-w-0 items-start border-t",
          previewVisible && "grid-cols-[minmax(0,1fr)_minmax(20rem,24rem)]",
        )}
        data-paper-collection-split=""
      >
        <div
          aria-busy={width === undefined}
          aria-colcount={width === undefined ? undefined : columnCount}
          aria-rowcount={width === undefined ? undefined : items.length + 1}
          className="min-w-0"
          role="table"
        >
          {width === undefined ? null : (
            <div role="rowgroup">
              {compact ? (
                <div aria-rowindex={1} className="sr-only" role="row">
                  <span role="columnheader">{t("columns.thumbnail")}</span>
                  <span role="columnheader">{t("columns.paper")}</span>
                  {actions ? (
                    <span role="columnheader">{t("columns.actions")}</span>
                  ) : null}
                </div>
              ) : (
                <div
                  className="bg-surface text-muted sticky top-0 z-10 grid h-10 items-center gap-3 border-b px-2 text-[0.6875rem] font-semibold"
                  aria-rowindex={1}
                  role="row"
                  style={{ gridTemplateColumns }}
                >
                  {leading ? (
                    <span role="columnheader">
                      <span className="sr-only">{t("columns.selection")}</span>
                    </span>
                  ) : null}
                  <span role="columnheader">{t("columns.paper")}</span>
                  {effectiveColumns.map((column) => (
                    <span key={column} role="columnheader">
                      {t(
                        column === "status" && personalLabels
                          ? "columns.personalStatus"
                          : column === "tags" && personalLabels
                            ? "columns.personalTags"
                            : `columns.${column}`,
                      )}
                    </span>
                  ))}
                  {actions ? (
                    <span role="columnheader">
                      <span className="sr-only">{t("columns.actions")}</span>
                    </span>
                  ) : null}
                </div>
              )}
            </div>
          )}
          <div
            className="max-h-[min(42rem,calc(100dvh-12rem))] overflow-auto"
            ref={scrollRef}
            role="rowgroup"
          >
            <div
              className="relative w-full min-w-0"
              style={{ height: rowVirtualizer.getTotalSize() }}
            >
              {renderedVirtualItems.map((virtualRow) => {
                const item = items[virtualRow.index];
                if (!item) return null;
                return (
                  <div
                    aria-rowindex={virtualRow.index + 2}
                    className="border-line-subtle hover:bg-hover focus-within:bg-hover data-[current=true]:bg-subtle absolute top-0 left-0 w-full border-b"
                    data-current={preview?.id === item.id}
                    data-index={virtualRow.index}
                    key={item.id}
                    onFocusCapture={() => setPreviewId(item.id)}
                    onMouseEnter={() => setHoveredPreviewId(item.id)}
                    onMouseLeave={() => setHoveredPreviewId(undefined)}
                    onPointerDownCapture={() => setPreviewId(item.id)}
                    ref={rowVirtualizer.measureElement}
                    role="row"
                    style={{ transform: `translateY(${virtualRow.start}px)` }}
                  >
                    {compact ? (
                      <div
                        className={cn(
                          "grid min-h-28 gap-3 px-3 py-3",
                          actions
                            ? "grid-cols-[2.25rem_minmax(0,1fr)_auto]"
                            : "grid-cols-[2.25rem_minmax(0,1fr)]",
                        )}
                      >
                        <div role="cell">
                          <PaperThumbnail item={item} />
                        </div>
                        <div className="min-w-0" role="cell">
                          <Link
                            className={cn(
                              "min-w-0 rounded-[var(--radius-sm)]",
                              keyboardFocusRing,
                            )}
                            href={item.href}
                          >
                            <span className="line-clamp-2 text-sm leading-5 font-semibold">
                              {item.title}
                            </span>
                            <span className="text-secondary mt-1 block truncate text-xs">
                              {item.authors.join(" · ") ||
                                t("preview.unknownAuthors")}
                            </span>
                          </Link>
                          <span className="mt-2 flex items-center gap-2">
                            <StatusControl
                              item={item}
                              onChange={onStatusChange}
                              personalLabels={personalLabels}
                            />
                            <TagButtons item={item} onTagClick={onTagClick} />
                          </span>
                        </div>
                        {actions ? (
                          <div role="cell">{actions(item)}</div>
                        ) : null}
                      </div>
                    ) : (
                      <div
                        className="grid h-16 items-center gap-3 px-2"
                        style={{ gridTemplateColumns }}
                      >
                        {leading ? (
                          <div role="cell">{leading(item)}</div>
                        ) : null}
                        <div className="min-w-0" role="cell">
                          <Link
                            className={cn(
                              "grid min-w-0 grid-cols-[2.25rem_minmax(0,1fr)] items-center gap-3 rounded-[var(--radius-sm)]",
                              keyboardFocusRing,
                            )}
                            href={item.href}
                          >
                            <PaperThumbnail item={item} />
                            <span className="min-w-0">
                              <span className="line-clamp-2 text-xs leading-4 font-semibold [overflow-wrap:anywhere]">
                                {item.title}
                              </span>
                              {item.snippet ? (
                                <span className="text-secondary mt-0.5 line-clamp-1 block text-[0.6875rem]">
                                  {item.snippet}
                                </span>
                              ) : null}
                            </span>
                          </Link>
                        </div>
                        {effectiveColumns.map((column) => (
                          <div
                            className="text-secondary min-w-0 truncate text-xs"
                            key={column}
                            role="cell"
                          >
                            {column === "status" ? (
                              <StatusControl
                                item={item}
                                onChange={onStatusChange}
                                personalLabels={personalLabels}
                              />
                            ) : column === "tags" ? (
                              <TagButtons item={item} onTagClick={onTagClick} />
                            ) : column === "authors" ? (
                              item.authors.join(" · ") ||
                              t("preview.unknownAuthors")
                            ) : column === "publication" ? (
                              item.publication || t("unknown")
                            ) : column === "last_opened" ? (
                              item.lastOpened || t("neverOpened")
                            ) : column === "added_at" ? (
                              item.addedAt || t("unknown")
                            ) : (
                              item.doi || "—"
                            )}
                          </div>
                        ))}
                        {actions ? (
                          <div role="cell">{actions(item)}</div>
                        ) : null}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
        {previewVisible && preview ? (
          <Preview
            item={preview}
            onClose={() =>
              mutatePreferences((current) => ({
                ...current,
                preview_open: false,
              }))
            }
            onStatusChange={onStatusChange}
            onTagClick={onTagClick}
            personalLabels={personalLabels}
          />
        ) : null}
      </div>
    </div>
  );
}
