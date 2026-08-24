"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Route } from "next";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";
import { createPortal } from "react-dom";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  Button,
  Checkbox,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  focusSurfaceVariants,
  IconButton,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
  useToast,
} from "@/components/ui";
import {
  MoveDownIcon,
  MoveUpIcon,
  OutlineIcon,
  PreviewHiddenIcon,
  PreviewVisibleIcon,
} from "@/design-system/icons/semantic-icons";
import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import {
  defaultPaperListPreferences,
  paperListPreferencesKey,
  paperListPreferencesQuery,
  updatePaperListPreferences,
  type PaperCollectionColumn,
  type PaperCollectionSizedColumn,
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
  activityTrail?: React.ReactNode;
  authors: string[];
  publication?: string;
  lastOpened?: string;
  readingTime?: React.ReactNode;
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

type PaperCollectionRenderedColumn = PaperCollectionColumn | "reading_time";
type PaperCollectionRenderedSizedColumn =
  PaperCollectionSizedColumn | "reading_time";

const COLUMN_WIDTH_LIMITS: Record<
  PaperCollectionRenderedSizedColumn,
  { default: number; max: number; min: number }
> = {
  paper: { default: 360, max: 1600, min: 160 },
  reading_time: { default: 112, max: 240, min: 96 },
  status: { default: 96, max: 960, min: 88 },
  tags: { default: 160, max: 400, min: 128 },
  authors: { default: 176, max: 520, min: 144 },
  publication: { default: 144, max: 400, min: 128 },
  last_opened: { default: 120, max: 280, min: 112 },
  added_at: { default: 120, max: 280, min: 112 },
  doi: { default: 160, max: 480, min: 144 },
};
const PREVIEW_COLUMN_MINIMUMS: Record<
  PaperCollectionRenderedSizedColumn,
  number
> = {
  paper: 200,
  reading_time: 80,
  status: 64,
  tags: 56,
  authors: 80,
  publication: 72,
  last_opened: 72,
  added_at: 72,
  doi: 96,
};

const RENDERED_COLUMNS = Object.keys(
  COLUMN_WIDTH_LIMITS,
) as PaperCollectionRenderedSizedColumn[];
const PERSISTED_COLUMNS = RENDERED_COLUMNS.filter(
  (column): column is PaperCollectionSizedColumn => column !== "reading_time",
);
const CONFIGURABLE_COLUMNS = PERSISTED_COLUMNS.filter(
  (column): column is PaperCollectionColumn => column !== "paper",
);
const DEFAULT_COLUMN_WIDTHS = Object.fromEntries(
  RENDERED_COLUMNS.map((column) => [
    column,
    COLUMN_WIDTH_LIMITS[column].default,
  ]),
) as Record<PaperCollectionRenderedSizedColumn, number>;
const MIN_PREVIEW_WIDTH = 400;
const MAX_PREVIEW_WIDTH = 720;
const MIN_LIST_WIDTH_WITH_PREVIEW = 640;

type PaperCollectionSidePanelState = {
  open: boolean;
  width: number;
};

type PaperCollectionSidePanelContextValue = {
  containerWidth?: number;
  panelElement: HTMLDivElement | null;
  panelWidth: number;
  setPanelState: React.Dispatch<
    React.SetStateAction<PaperCollectionSidePanelState>
  >;
};

const PaperCollectionSidePanelContext =
  React.createContext<PaperCollectionSidePanelContextValue | null>(null);

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, Math.round(value)));
}

function getColumnWidths(preferences: PaperListPreferences) {
  const widths = { ...DEFAULT_COLUMN_WIDTHS };
  preferences.column_widths.forEach(({ column, width }) => {
    widths[column] = width;
  });
  return widths;
}

function toColumnWidthPreferences(
  widths: Record<PaperCollectionRenderedSizedColumn, number>,
) {
  return PERSISTED_COLUMNS.map((column) => ({
    column,
    width: widths[column],
  }));
}

function resizeColumnPair({
  left,
  leftLimits,
  nextLeft,
  right,
  rightLimits,
}: {
  left: number;
  leftLimits: { max: number; min: number };
  nextLeft: number;
  right: number;
  rightLimits: { max: number; min: number };
}) {
  const total = left + right;
  const minimum = Math.max(leftLimits.min, total - rightLimits.max);
  const maximum = Math.min(leftLimits.max, total - rightLimits.min);
  const resolvedLeft = clamp(nextLeft, minimum, maximum);
  return {
    left: resolvedLeft,
    maximum,
    minimum,
    right: total - resolvedLeft,
  };
}

function ResizeHandle({
  className,
  direction = 1,
  label,
  max,
  min,
  onChange,
  onCommit,
  value,
}: {
  className?: string;
  direction?: -1 | 1;
  label: string;
  max: number;
  min: number;
  onChange: (value: number) => void;
  onCommit: (value: number) => void;
  value: number;
}) {
  const drag = React.useRef<{
    lastValue: number;
    pointerId: number;
    startValue: number;
    startX: number;
  } | null>(null);
  const valueRef = React.useRef(value);
  React.useEffect(() => {
    valueRef.current = value;
  }, [value]);

  function resize(nextValue: number) {
    const next = clamp(nextValue, min, max);
    valueRef.current = next;
    if (drag.current) drag.current.lastValue = next;
    onChange(next);
  }

  function finish(pointerId: number) {
    if (!drag.current || drag.current.pointerId !== pointerId) return;
    const next = drag.current.lastValue;
    drag.current = null;
    onCommit(next);
  }

  return (
    <div
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemax={max}
      aria-valuemin={min}
      aria-valuenow={value}
      className={cn(
        "group flex cursor-col-resize touch-none items-center justify-center select-none",
        focusSurfaceVariants({ intent: "neutral" }),
        className,
      )}
      data-paper-resize-handle=""
      onKeyDown={(event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        const screenDelta = event.key === "ArrowRight" ? 1 : -1;
        const step = event.shiftKey ? 32 : 8;
        const next = clamp(
          valueRef.current + screenDelta * direction * step,
          min,
          max,
        );
        resize(next);
        onCommit(next);
      }}
      onPointerCancel={(event) => finish(event.pointerId)}
      onPointerDown={(event) => {
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = {
          lastValue: valueRef.current,
          pointerId: event.pointerId,
          startValue: valueRef.current,
          startX: event.clientX,
        };
      }}
      onPointerMove={(event) => {
        const current = drag.current;
        if (!current || current.pointerId !== event.pointerId) return;
        resize(
          current.startValue + (event.clientX - current.startX) * direction,
        );
      }}
      onPointerUp={(event) => finish(event.pointerId)}
      role="separator"
      tabIndex={0}
    >
      <span className="bg-line-strong group-hover:bg-foreground group-focus-visible:bg-foreground h-5 w-px" />
    </div>
  );
}

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

export function PaperCollectionSidePanelLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const rootRef = React.useRef<HTMLDivElement>(null);
  const containerWidth = useElementWidth(rootRef);
  const [panelElement, setPanelElement] = React.useState<HTMLDivElement | null>(
    null,
  );
  const [panelState, setPanelState] =
    React.useState<PaperCollectionSidePanelState>({
      open: false,
      width: defaultPaperListPreferences.preview_width,
    });
  const context = React.useMemo(
    () => ({
      containerWidth,
      panelElement,
      panelWidth: panelState.open ? panelState.width : 0,
      setPanelState,
    }),
    [containerWidth, panelElement, panelState.open, panelState.width],
  );

  return (
    <PaperCollectionSidePanelContext.Provider value={context}>
      <div
        className="flex min-h-0 min-w-0 flex-1"
        data-paper-collection-page-layout=""
        ref={rootRef}
      >
        <div className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</div>
        <div
          className={cn(
            "relative h-full min-h-0 shrink-0",
            !panelState.open && "hidden",
          )}
          data-paper-collection-side-panel=""
          ref={setPanelElement}
          style={{ width: panelState.open ? panelState.width : 0 }}
        />
      </div>
    </PaperCollectionSidePanelContext.Provider>
  );
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
            aria-label={t("tagFilterLabel", {
              tag: tag.name,
              title: item.title,
            })}
            className={cn(
              "bg-subtle hover:bg-hover max-w-20 truncate rounded-[var(--radius-sm)] px-1.5 py-1 text-[0.6875rem] font-medium",
              focusSurfaceVariants({ intent: "neutral" }),
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
  onResetWidths,
  preferences,
  update,
}: {
  onResetWidths: () => void;
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
  const orderedColumns: PaperCollectionColumn[] = [
    ...preferences.visible_columns,
    ...CONFIGURABLE_COLUMNS.filter(
      (column) => !preferences.visible_columns.includes(column),
    ),
  ];
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          aria-label={t("columnsMenu.label")}
          className="hidden sm:inline-flex"
          size="sm"
          variant="ghost"
        >
          <Icon glyph={OutlineIcon} size={20} />
          <span className="hidden xl:inline">{t("columnsMenu.label")}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        aria-label={t("columnsMenu.title")}
        className="w-80 p-2"
      >
        <div className="px-2 pt-1 pb-2">
          <h3 className="text-sm font-semibold">{t("columnsMenu.title")}</h3>
          <p className="text-secondary mt-1 text-xs leading-5">
            {t("columnsMenu.description")}
          </p>
        </div>
        <div className="grid gap-0.5">
          {orderedColumns.map((column) => {
            const checked = preferences.visible_columns.includes(column);
            const visibleIndex = preferences.visible_columns.indexOf(column);
            const columnLabel = t(`columns.${column}`);
            return (
              <div
                className="hover:bg-hover grid min-h-10 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-[var(--radius-sm)] px-2"
                key={column}
              >
                <label className="flex min-w-0 cursor-pointer items-center gap-2 text-sm">
                  <Checkbox
                    checked={checked}
                    onCheckedChange={(value) => toggle(column, value === true)}
                  />
                  <span className="truncate">{columnLabel}</span>
                </label>
                {checked ? (
                  <span className="flex items-center gap-0.5">
                    <IconButton
                      className="size-8 min-h-8"
                      disabled={visibleIndex === 0}
                      label={t("columnsMenu.moveUpColumn", {
                        column: columnLabel,
                      })}
                      onClick={() => move(column, -1)}
                      variant="ghost"
                    >
                      <Icon glyph={MoveUpIcon} size={16} />
                    </IconButton>
                    <IconButton
                      className="size-8 min-h-8"
                      disabled={
                        visibleIndex === preferences.visible_columns.length - 1
                      }
                      label={t("columnsMenu.moveDownColumn", {
                        column: columnLabel,
                      })}
                      onClick={() => move(column, 1)}
                      variant="ghost"
                    >
                      <Icon glyph={MoveDownIcon} size={16} />
                    </IconButton>
                  </span>
                ) : null}
              </div>
            );
          })}
        </div>
        <div className="border-line-subtle mt-2 border-t px-1 pt-2">
          <Button
            className="w-full justify-start"
            onClick={onResetWidths}
            size="sm"
            variant="ghost"
          >
            {t("columnsMenu.resetWidths")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

const PreviewMarkdownHeading: NonNullable<Components["h1"]> = ({
  children,
}) => (
  <h4 className="text-foreground text-sm leading-5 font-semibold">
    {children}
  </h4>
);

const previewMarkdownComponents: Components = {
  h1: PreviewMarkdownHeading,
  h2: PreviewMarkdownHeading,
  h3: PreviewMarkdownHeading,
  h4: PreviewMarkdownHeading,
  h5: PreviewMarkdownHeading,
  h6: PreviewMarkdownHeading,
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
      className={cn(
        "decoration-line-strong hover:decoration-foreground rounded-[var(--radius-xs)] underline underline-offset-2",
        focusSurfaceVariants({ intent: "inline" }),
      )}
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
  onStatusChange,
  onTagClick,
  personalLabels,
}: {
  item: PaperCollectionItem;
  onStatusChange?: (item: PaperCollectionItem, status: PaperStatus) => void;
  onTagClick?: (tag: PaperCollectionTag) => void;
  personalLabels: boolean;
}) {
  const t = useTranslations("PaperCollection");
  return (
    <aside
      aria-label={t("preview.label")}
      className={cn(
        "border-line-subtle bg-subtle h-full min-w-0 overflow-y-auto border-l px-5 pb-5",
        focusSurfaceVariants({ intent: "scroll" }),
      )}
      data-paper-collection-preview=""
      tabIndex={0}
    >
      <div className="flex h-10 items-center">
        <h2 className="text-sm font-semibold">{t("preview.label")}</h2>
      </div>
      <div className="mt-3 grid grid-cols-[6rem_minmax(0,1fr)] items-start gap-4">
        <PaperPreviewImage
          className="bg-surface h-36 w-24"
          previewUrl={item.previewUrl}
          variant="detail"
        />
        <div className="min-w-0">
          <h3 className="text-base leading-6 font-semibold [overflow-wrap:anywhere]">
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
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-muted text-xs">
          {t(personalLabels ? "columns.personalStatus" : "columns.status")}
        </span>
        <StatusControl
          item={item}
          onChange={onStatusChange}
          personalLabels={personalLabels}
        />
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

export type PaperCollectionWorkbenchProps = {
  actions?: (item: PaperCollectionItem) => React.ReactNode;
  beforeTable?: React.ReactNode;
  /** Replaces the table body while defined; null intentionally renders no body. */
  contentState?: React.ReactNode;
  items: PaperCollectionItem[];
  leading?: (item: PaperCollectionItem) => React.ReactNode;
  onStatusChange?: (item: PaperCollectionItem, status: PaperStatus) => void;
  onTagClick?: (tag: PaperCollectionTag) => void;
  personalLabels?: boolean;
  scrollResetKey?: string;
  tableFooter?: React.ReactNode;
  toolbar?: React.ReactNode;
};

export function PaperCollectionWorkbench({
  actions,
  beforeTable,
  contentState,
  items,
  leading,
  onStatusChange,
  onTagClick,
  personalLabels = false,
  scrollResetKey,
  tableFooter,
  toolbar,
}: PaperCollectionWorkbenchProps) {
  const t = useTranslations("PaperCollection");
  const toast = useToast();
  const queryClient = useQueryClient();
  const sidePanelLayout = React.useContext(PaperCollectionSidePanelContext);
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
  const persistedColumnWidths = React.useMemo(
    () => getColumnWidths(preferences),
    [preferences],
  );
  const [columnWidths, setColumnWidths] = React.useState(persistedColumnWidths);
  const [previewWidth, setPreviewWidth] = React.useState(
    preferences.preview_width,
  );
  React.useEffect(() => {
    setColumnWidths(persistedColumnWidths);
    setPreviewWidth(preferences.preview_width);
  }, [persistedColumnWidths, preferences.preview_width]);
  const commitColumnWidths = React.useCallback(
    (updates: Partial<Record<PaperCollectionRenderedSizedColumn, number>>) => {
      setColumnWidths((current) => ({ ...current, ...updates }));
      mutatePreferences((current) => {
        const nextWidths = {
          ...getColumnWidths(current),
          ...updates,
        };
        return {
          ...current,
          column_widths: toColumnWidthPreferences(nextWidths),
        };
      });
    },
    [mutatePreferences],
  );
  const resetLayoutWidths = React.useCallback(() => {
    setColumnWidths(DEFAULT_COLUMN_WIDTHS);
    setPreviewWidth(defaultPaperListPreferences.preview_width);
    mutatePreferences((current) => ({
      ...current,
      column_widths: toColumnWidthPreferences(DEFAULT_COLUMN_WIDTHS),
      preview_width: defaultPaperListPreferences.preview_width,
    }));
  }, [mutatePreferences]);
  const rootRef = React.useRef<HTMLDivElement>(null);
  const sidePanelContentInsetRef = React.useRef(0);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const headerScrollRef = React.useRef<HTMLDivElement>(null);
  const width = useElementWidth(rootRef);
  const measuredWidth = width ?? 0;
  const availableWidth = sidePanelLayout?.containerWidth ?? measuredWidth;
  const [previewId, setPreviewId] = React.useState<string>();
  const preview = items.find((item) => item.id === previewId) ?? items[0];
  const previewVisible = Boolean(
    contentState === undefined &&
    preview &&
    preferences.preview_open &&
    measuredWidth > 0 &&
    availableWidth >= 1040,
  );
  if (
    sidePanelLayout &&
    sidePanelLayout.panelWidth === 0 &&
    availableWidth > 0 &&
    measuredWidth > 0
  ) {
    sidePanelContentInsetRef.current = Math.max(
      0,
      availableWidth - measuredWidth,
    );
  }
  const previewWidthMaximum = Math.max(
    MIN_PREVIEW_WIDTH,
    Math.min(
      MAX_PREVIEW_WIDTH,
      sidePanelLayout
        ? availableWidth -
            sidePanelContentInsetRef.current -
            MIN_LIST_WIDTH_WITH_PREVIEW
        : availableWidth - MIN_LIST_WIDTH_WITH_PREVIEW,
    ),
  );
  const resolvedPreviewWidth = clamp(
    previewWidth,
    MIN_PREVIEW_WIDTH,
    previewWidthMaximum,
  );
  const listWidth = Math.max(
    0,
    measuredWidth -
      (previewVisible && !sidePanelLayout ? resolvedPreviewWidth : 0),
  );
  const setSidePanelState = sidePanelLayout?.setPanelState;
  React.useLayoutEffect(() => {
    setSidePanelState?.({
      open: previewVisible,
      width: resolvedPreviewWidth,
    });
  }, [previewVisible, resolvedPreviewWidth, setSidePanelState]);
  React.useEffect(
    () => () => {
      setSidePanelState?.((current) => ({ ...current, open: false }));
    },
    [setSidePanelState],
  );
  const effectiveColumns = React.useMemo<PaperCollectionRenderedColumn[]>(
    () => ["reading_time", ...preferences.visible_columns],
    [preferences.visible_columns],
  );
  const compact = listWidth < 640;
  const columnCount = compact
    ? 2 + (actions ? 1 : 0)
    : 1 + effectiveColumns.length + (leading ? 1 : 0) + (actions ? 1 : 0);
  // TanStack Virtual owns a mutable scroll controller by design.
  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: items.length,
    enabled: contentState === undefined,
    estimateSize: () => 64,
    getScrollElement: () => scrollRef.current,
    overscan: 8,
  });
  React.useLayoutEffect(() => {
    if (contentState === undefined && scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [contentState, scrollResetKey]);
  const orderedColumns = React.useMemo<PaperCollectionRenderedSizedColumn[]>(
    () => ["paper", ...effectiveColumns],
    [effectiveColumns],
  );
  const renderedColumnWidths = React.useMemo(() => {
    const leadingWidth = previewVisible ? 40 : 48;
    const actionsWidth = previewVisible ? 36 : 44;
    const columnGap = previewVisible ? 8 : 12;
    const minimumFor = (column: PaperCollectionRenderedSizedColumn) =>
      previewVisible
        ? PREVIEW_COLUMN_MINIMUMS[column]
        : COLUMN_WIDTH_LIMITS[column].min;
    const fixedWidth =
      (leading ? leadingWidth : 0) +
      (actions ? actionsWidth : 0) +
      Math.max(0, columnCount - 1) * columnGap +
      16;
    const preferredTotal = orderedColumns.reduce(
      (total, column) => total + columnWidths[column],
      0,
    );
    const minimumTotal = orderedColumns.reduce(
      (total, column) => total + minimumFor(column),
      0,
    );
    const targetTotal = Math.max(
      minimumTotal,
      Math.min(preferredTotal, listWidth - fixedWidth),
    );
    const shortage = preferredTotal - targetTotal;
    const compressibleTotal = orderedColumns.reduce(
      (total, column) =>
        total + Math.max(0, columnWidths[column] - minimumFor(column)),
      0,
    );

    return Object.fromEntries(
      orderedColumns.map((column) => {
        const compressible = Math.max(
          0,
          columnWidths[column] - minimumFor(column),
        );
        const reduction = compressibleTotal
          ? (shortage * compressible) / compressibleTotal
          : 0;
        return [
          column,
          clamp(
            columnWidths[column] - reduction,
            minimumFor(column),
            columnWidths[column],
          ),
        ];
      }),
    ) as Partial<Record<PaperCollectionRenderedSizedColumn, number>>;
  }, [
    actions,
    columnCount,
    columnWidths,
    leading,
    listWidth,
    orderedColumns,
    previewVisible,
  ]);
  const leadingColumnWidth = previewVisible ? 40 : 48;
  const actionsColumnWidth = previewVisible ? 36 : 44;
  const tableColumnGap = previewVisible ? 8 : 12;
  const renderedPaperWidth = renderedColumnWidths.paper ?? columnWidths.paper;
  const gridTemplateColumns = [
    leading ? `${leadingColumnWidth}px` : undefined,
    `minmax(${renderedPaperWidth}px,1fr)`,
    ...effectiveColumns.map(
      (column) => `${renderedColumnWidths[column] ?? columnWidths[column]}px`,
    ),
    actions ? `${actionsColumnWidth}px` : undefined,
  ]
    .filter(Boolean)
    .join(" ");
  const tableMinimumWidth =
    (leading ? leadingColumnWidth : 0) +
    renderedPaperWidth +
    effectiveColumns.reduce(
      (total, column) =>
        total + (renderedColumnWidths[column] ?? columnWidths[column]),
      0,
    ) +
    (actions ? actionsColumnWidth : 0) +
    Math.max(0, columnCount - 1) * tableColumnGap +
    16;
  const columnLabel = (column: PaperCollectionRenderedSizedColumn) =>
    t(
      column === "paper"
        ? "columns.paper"
        : column === "status" && personalLabels
          ? "columns.personalStatus"
          : column === "tags" && personalLabels
            ? "columns.personalTags"
            : `columns.${column}`,
    );
  const virtualItems = rowVirtualizer.getVirtualItems();
  const renderedVirtualItems = width === undefined ? [] : virtualItems;
  const previewToggleLabel = previewVisible
    ? t("preview.close")
    : t("preview.open");
  return (
    <div
      className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden"
      ref={rootRef}
    >
      <div
        className="mb-3 flex min-h-11 min-w-0 shrink-0 items-center"
        data-paper-collection-toolbar=""
      >
        {toolbar ? (
          <div className="min-w-0 flex-1">{toolbar}</div>
        ) : (
          <div className="flex-1" />
        )}
        <div className="hidden shrink-0 items-center gap-1 sm:flex">
          {availableWidth >= 1040 ? (
            <TooltipProvider delayDuration={250}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <IconButton
                    aria-pressed={previewVisible}
                    data-paper-preview-toggle=""
                    label={previewToggleLabel}
                    onClick={() =>
                      mutatePreferences((current) => ({
                        ...current,
                        preview_open: !current.preview_open,
                      }))
                    }
                    variant="ghost"
                  >
                    <Icon
                      glyph={
                        previewVisible ? PreviewHiddenIcon : PreviewVisibleIcon
                      }
                      size={20}
                    />
                  </IconButton>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  {previewToggleLabel}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ) : null}
          <ColumnManager
            onResetWidths={resetLayoutWidths}
            preferences={preferences}
            update={mutatePreferences}
          />
        </div>
      </div>
      {beforeTable ? <div className="shrink-0">{beforeTable}</div> : null}
      {contentState !== undefined ? (
        <div className="border-line min-h-0 min-w-0 flex-1 overflow-auto border-t">
          {contentState}
        </div>
      ) : null}
      <div
        className={cn(
          "border-line min-h-0 min-w-0 flex-1 items-stretch overflow-hidden border-t",
          contentState === undefined ? "grid" : "hidden",
        )}
        data-paper-collection-split=""
        style={
          previewVisible && !sidePanelLayout
            ? {
                gridTemplateColumns: `minmax(0, 1fr) ${resolvedPreviewWidth}px`,
              }
            : undefined
        }
      >
        <div
          aria-busy={width === undefined}
          aria-colcount={width === undefined ? undefined : columnCount}
          aria-rowcount={
            width === undefined
              ? undefined
              : items.length + 1 + (tableFooter ? 1 : 0)
          }
          className="flex min-h-0 min-w-0 flex-col"
          role="table"
        >
          {width === undefined ? null : (
            <div
              className="overflow-hidden"
              ref={headerScrollRef}
              role="rowgroup"
            >
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
                  className={cn(
                    "bg-surface text-muted sticky top-0 z-10 grid h-10 items-center border-b px-2 text-[0.6875rem] font-semibold",
                    previewVisible ? "gap-2" : "gap-3",
                  )}
                  aria-rowindex={1}
                  role="row"
                  style={{
                    gridTemplateColumns,
                    minWidth: tableMinimumWidth,
                  }}
                >
                  {leading ? (
                    <span role="columnheader">
                      <span className="sr-only">{t("columns.selection")}</span>
                    </span>
                  ) : null}
                  {orderedColumns.map((column, index) => {
                    const label = columnLabel(column);
                    const nextColumn = orderedColumns[index + 1];
                    const nextLabel = nextColumn
                      ? columnLabel(nextColumn)
                      : undefined;
                    const resizePair =
                      nextColumn &&
                      column !== "reading_time" &&
                      nextColumn !== "reading_time"
                        ? (nextLeft: number) =>
                            resizeColumnPair({
                              left: columnWidths[column],
                              leftLimits: COLUMN_WIDTH_LIMITS[column],
                              nextLeft,
                              right: columnWidths[nextColumn],
                              rightLimits: COLUMN_WIDTH_LIMITS[nextColumn],
                            })
                        : undefined;
                    const pair = resizePair?.(columnWidths[column]);
                    return (
                      <span
                        className="relative flex h-full items-center"
                        key={column}
                        role="columnheader"
                      >
                        {label}
                        {nextColumn && nextLabel && resizePair && pair ? (
                          <ResizeHandle
                            className="absolute top-0 -right-2 z-20 h-full w-4"
                            label={t("resize.boundary", {
                              left: label,
                              right: nextLabel,
                            })}
                            max={pair.maximum}
                            min={pair.minimum}
                            onChange={(next) => {
                              const resized = resizePair(next);
                              setColumnWidths((current) => ({
                                ...current,
                                [column]: resized.left,
                                [nextColumn]: resized.right,
                              }));
                            }}
                            onCommit={(next) => {
                              const resized = resizePair(next);
                              commitColumnWidths({
                                [column]: resized.left,
                                [nextColumn]: resized.right,
                              });
                            }}
                            value={columnWidths[column]}
                          />
                        ) : null}
                      </span>
                    );
                  })}
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
            className="min-h-0 flex-1 overflow-auto overscroll-contain"
            data-paper-collection-scroll=""
            onScroll={(event) => {
              if (headerScrollRef.current) {
                headerScrollRef.current.scrollLeft =
                  event.currentTarget.scrollLeft;
              }
            }}
            ref={scrollRef}
          >
            <div
              className="relative w-full"
              role="rowgroup"
              style={{
                height: rowVirtualizer.getTotalSize(),
                minWidth: compact ? undefined : tableMinimumWidth,
              }}
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
                    onMouseEnter={() => setPreviewId(item.id)}
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
                              focusSurfaceVariants({ intent: "selection" }),
                            )}
                            data-state={
                              preview?.id === item.id ? "active" : undefined
                            }
                            href={item.href}
                          >
                            <span className="line-clamp-2 text-sm leading-5 font-semibold">
                              {item.title}
                            </span>
                            <span className="text-secondary mt-1 block truncate text-xs">
                              {item.authors.join(" · ") ||
                                t("preview.unknownAuthors")}
                            </span>
                            {item.activityTrail || item.readingTime ? (
                              <span className="mt-2 flex min-w-0 items-center gap-3">
                                {item.activityTrail ? (
                                  <span className="min-w-0 flex-1">
                                    {item.activityTrail}
                                  </span>
                                ) : null}
                                {item.readingTime ? (
                                  <span className="shrink-0">
                                    {item.readingTime}
                                  </span>
                                ) : null}
                              </span>
                            ) : null}
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
                        className={cn(
                          "grid h-16 items-center px-2",
                          previewVisible ? "gap-2" : "gap-3",
                        )}
                        style={{
                          gridTemplateColumns,
                          minWidth: tableMinimumWidth,
                        }}
                      >
                        {leading ? (
                          <div role="cell">{leading(item)}</div>
                        ) : null}
                        <div className="min-w-0 overflow-hidden" role="cell">
                          <Link
                            className={cn(
                              "grid min-w-0 grid-cols-[2.25rem_minmax(0,1fr)] items-center gap-3 overflow-hidden rounded-[var(--radius-sm)]",
                              focusSurfaceVariants({ intent: "selection" }),
                            )}
                            data-state={
                              preview?.id === item.id ? "active" : undefined
                            }
                            href={item.href}
                          >
                            <PaperThumbnail item={item} />
                            <span
                              className="max-h-[52px] min-w-0 overflow-hidden"
                              data-paper-result-text=""
                            >
                              <span
                                className={cn(
                                  "text-xs leading-4 font-semibold [overflow-wrap:anywhere]",
                                  item.activityTrail
                                    ? "line-clamp-1"
                                    : "line-clamp-2",
                                )}
                              >
                                {item.title}
                              </span>
                              {item.snippet ? (
                                <span className="text-secondary mt-0.5 line-clamp-1 text-[0.6875rem]">
                                  {item.snippet}
                                </span>
                              ) : null}
                              {item.activityTrail ? (
                                <span className="mt-2 block">
                                  {item.activityTrail}
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
                            ) : column === "reading_time" ? (
                              item.readingTime || "—"
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
            {tableFooter ? (
              <div role="rowgroup">
                <div aria-rowindex={items.length + 2} role="row">
                  <div aria-colspan={columnCount} role="cell">
                    {tableFooter}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
        {previewVisible && preview && !sidePanelLayout ? (
          <div className="relative min-h-0 min-w-0">
            <ResizeHandle
              className="absolute inset-y-0 -left-2 z-20 w-4"
              direction={-1}
              label={t("resize.preview")}
              max={previewWidthMaximum}
              min={MIN_PREVIEW_WIDTH}
              onChange={setPreviewWidth}
              onCommit={(next) => {
                setPreviewWidth(next);
                mutatePreferences((current) => ({
                  ...current,
                  preview_width: next,
                }));
              }}
              value={resolvedPreviewWidth}
            />
            <Preview
              item={preview}
              onStatusChange={onStatusChange}
              onTagClick={onTagClick}
              personalLabels={personalLabels}
            />
          </div>
        ) : null}
      </div>
      {previewVisible && preview && sidePanelLayout?.panelElement
        ? createPortal(
            <div className="relative h-full min-h-0 min-w-0">
              <ResizeHandle
                className="absolute inset-y-0 -left-2 z-20 w-4"
                direction={-1}
                label={t("resize.preview")}
                max={previewWidthMaximum}
                min={MIN_PREVIEW_WIDTH}
                onChange={setPreviewWidth}
                onCommit={(next) => {
                  setPreviewWidth(next);
                  mutatePreferences((current) => ({
                    ...current,
                    preview_width: next,
                  }));
                }}
                value={resolvedPreviewWidth}
              />
              <Preview
                item={preview}
                onStatusChange={onStatusChange}
                onTagClick={onTagClick}
                personalLabels={personalLabels}
              />
            </div>,
            sidePanelLayout.panelElement,
          )
        : null}
    </div>
  );
}
