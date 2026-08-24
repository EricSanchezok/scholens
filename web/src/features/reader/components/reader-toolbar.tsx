"use client";

import {
  BackIcon,
  DownloadIcon,
  FitIcon,
  OutlineIcon,
  PreviousIcon,
  NextIcon,
  SearchIcon,
  OpenPanelIcon,
  DismissIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from "@/design-system/icons/semantic-icons";
import * as React from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  focusSurfaceVariants,
  IconButton,
  Button,
  Input,
  isImeComposing,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import type { ReaderFitMode } from "./pdf-page";
import type { ReaderDocumentView } from "../reader-types";
import {
  ReaderFullTranslationControl,
  type FullTranslationStatus,
  type TranslationPreferences,
} from "../translation";

export type ReaderToolbarLabels = {
  previousPage: string;
  nextPage: string;
  page: string;
  zoomOut: string;
  zoomIn: string;
  fit: string;
  fitWidth: string;
  fitPage: string;
  search: string;
  closeSearch: string;
  noSearchResults: string;
  previousSearchResult: string;
  nextSearchResult: string;
  showOutline: string;
  hideOutline: string;
  download: string;
  openPanel: string;
  closePanel: string;
  returnLibrary: string;
  projectContext: (context: string) => string;
  personalContext: string;
  pdfView: string;
  reflowView: string;
};

export function ReaderToolbar({
  className,
  fitMode,
  labels,
  metadata,
  onDownload,
  onFitModeChange,
  onToggleOutline,
  onOpenPanel,
  onOpenSearch,
  onPageChange,
  onReturn,
  onViewChange,
  onZoomChange,
  pageCount,
  pageNumber,
  panelOpen,
  projectContext,
  outlineAvailable,
  outlineOpen,
  title,
  view,
  search,
  translation,
  zoom,
}: {
  className?: string;
  fitMode: ReaderFitMode;
  labels: ReaderToolbarLabels;
  metadata?: string;
  onDownload: () => void;
  onFitModeChange: (fit: ReaderFitMode) => void;
  onToggleOutline: () => void;
  onOpenPanel: () => void;
  onOpenSearch: () => void;
  onPageChange: (page: number) => void;
  onReturn: () => void;
  onViewChange: (view: ReaderDocumentView) => void;
  onZoomChange: (zoom: number) => void;
  pageCount: number;
  pageNumber: number;
  panelOpen: boolean;
  projectContext?: {
    onChange: (projectId: string | undefined) => void;
    options: Array<{ id: string; title: string }>;
    projectId?: string;
  };
  outlineAvailable: boolean;
  outlineOpen: boolean;
  search?: {
    currentIndex: number;
    matchCount: number;
    onClose: () => void;
    onMove: (direction: -1 | 1) => void;
    onQueryChange: (query: string) => void;
    query: string;
  };
  translation: {
    enabled: boolean;
    onEnabledChange: (enabled: boolean) => void;
    onPreferencesChange: (
      patch: Partial<TranslationPreferences>,
    ) => Promise<unknown>;
    preferences?: TranslationPreferences;
    saving: boolean;
    status: FullTranslationStatus;
  };
  title: string;
  view: ReaderDocumentView;
  zoom: number;
}) {
  const selectedProjectContext = projectContext?.projectId
    ? (projectContext.options.find(
        (project) => project.id === projectContext.projectId,
      )?.title ?? labels.personalContext)
    : labels.personalContext;

  return (
    <div
      aria-label={labels.page}
      className={cn(
        "border-line bg-surface flex h-14 shrink-0 items-center gap-1 border-b px-2 sm:gap-2 sm:px-3",
        className,
      )}
      role="toolbar"
    >
      {!search ? (
        <div className="hidden min-w-0 flex-1 items-center gap-1 2xl:flex">
          <IconButton
            label={labels.returnLibrary}
            onClick={onReturn}
            variant="ghost"
          >
            <Icon glyph={BackIcon} size={20} />
          </IconButton>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{title}</p>
            {metadata ? (
              <p className="text-muted truncate text-xs">{metadata}</p>
            ) : null}
          </div>
          {projectContext && projectContext.options.length > 0 ? (
            <Select
              onValueChange={(value) =>
                projectContext.onChange(
                  value === "personal" ? undefined : value,
                )
              }
              value={projectContext.projectId ?? "personal"}
            >
              <SelectTrigger
                aria-label={labels.projectContext(selectedProjectContext)}
                className="ml-2 w-40 min-w-0 shrink"
                variant="compact"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-w-80">
                <SelectItem
                  className="max-w-80 [overflow-wrap:anywhere] whitespace-normal"
                  value="personal"
                >
                  {labels.personalContext}
                </SelectItem>
                {projectContext.options.map((project) => (
                  <SelectItem
                    className="max-w-80 [overflow-wrap:anywhere] whitespace-normal"
                    key={project.id}
                    value={project.id}
                  >
                    {project.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
        </div>
      ) : null}

      {!search && projectContext && projectContext.options.length > 0 ? (
        <Select
          onValueChange={(value) =>
            projectContext.onChange(value === "personal" ? undefined : value)
          }
          value={projectContext.projectId ?? "personal"}
        >
          <SelectTrigger
            aria-label={labels.projectContext(selectedProjectContext)}
            className="hidden w-40 max-w-[40vw] min-w-0 shrink sm:flex 2xl:hidden"
            variant="compact"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="max-w-80">
            <SelectItem
              className="max-w-80 [overflow-wrap:anywhere] whitespace-normal"
              value="personal"
            >
              {labels.personalContext}
            </SelectItem>
            {projectContext.options.map((project) => (
              <SelectItem
                className="max-w-80 [overflow-wrap:anywhere] whitespace-normal"
                key={project.id}
                value={project.id}
              >
                {project.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}

      {search ? (
        <div className="flex min-w-0 flex-1 items-center gap-1">
          <div
            className={cn(
              "border-line bg-canvas flex h-9 min-w-0 flex-1 items-center rounded-[var(--radius-md)] border pl-2",
              focusSurfaceVariants({ intent: "neutral" }),
            )}
            data-focus-surface
          >
            <Icon glyph={SearchIcon} size={20} tone="secondary" />
            <Input
              aria-label={labels.search}
              autoFocus
              className="h-8 min-w-0 border-0 bg-transparent px-2 shadow-none hover:bg-transparent"
              data-focus-delegate="surface"
              onChange={(event) =>
                search.onQueryChange(event.currentTarget.value)
              }
              onKeyDown={(event) => {
                if (event.key === "Escape") search.onClose();
                if (event.key === "Enter" && !isImeComposing(event)) {
                  event.preventDefault();
                  search.onMove(event.shiftKey ? -1 : 1);
                }
              }}
              placeholder={labels.search}
              type="text"
              value={search.query}
            />
          </div>
          <span
            aria-label={
              search.matchCount === 0 && search.query.trim()
                ? labels.noSearchResults
                : undefined
            }
            aria-live="polite"
            className="text-muted w-14 shrink-0 text-center text-xs tabular-nums"
          >
            {search.matchCount > 0
              ? `${search.currentIndex + 1} / ${search.matchCount}`
              : search.query.trim()
                ? "0 / 0"
                : "—"}
          </span>
          <IconButton
            disabled={search.matchCount === 0}
            label={labels.previousSearchResult}
            onClick={() => search.onMove(-1)}
            variant="ghost"
          >
            <Icon glyph={PreviousIcon} size={20} />
          </IconButton>
          <IconButton
            disabled={search.matchCount === 0}
            label={labels.nextSearchResult}
            onClick={() => search.onMove(1)}
            variant="ghost"
          >
            <Icon glyph={NextIcon} size={20} />
          </IconButton>
          <IconButton
            label={labels.closeSearch}
            onClick={search.onClose}
            variant="ghost"
          >
            <Icon glyph={DismissIcon} size={20} />
          </IconButton>
        </div>
      ) : (
        <>
          <div
            aria-label={`${labels.pdfView} / ${labels.reflowView}`}
            className="border-line bg-subtle flex shrink-0 rounded-[var(--radius-md)] border p-0.5"
            role="group"
          >
            <Button
              aria-pressed={view === "pdf"}
              className="px-2 sm:h-8 sm:min-h-8 sm:px-2.5"
              onClick={() => onViewChange("pdf")}
              size="sm"
              variant={view === "pdf" ? "secondary" : "ghost"}
            >
              {labels.pdfView}
            </Button>
            <Button
              aria-pressed={view === "reflow"}
              className="px-2 sm:h-8 sm:min-h-8 sm:px-2.5"
              onClick={() => onViewChange("reflow")}
              size="sm"
              variant={view === "reflow" ? "secondary" : "ghost"}
            >
              {labels.reflowView}
            </Button>
          </div>

          {view === "pdf" ? (
            <div className="hidden shrink-0 items-center gap-0.5 sm:flex">
              <IconButton
                disabled={pageNumber <= 1}
                label={labels.previousPage}
                onClick={() => onPageChange(pageNumber - 1)}
                variant="ghost"
              >
                <Icon glyph={PreviousIcon} size={20} />
              </IconButton>
              <label
                className={cn(
                  "border-line bg-canvas flex h-9 items-center rounded-[var(--radius-md)] border px-2 text-sm",
                  focusSurfaceVariants({ intent: "neutral" }),
                )}
                data-focus-surface
              >
                <span className="sr-only">{labels.page}</span>
                <Input
                  aria-label={labels.page}
                  className="h-8 w-8 border-0 bg-transparent p-0 text-center tabular-nums shadow-none hover:bg-transparent"
                  data-focus-delegate="surface"
                  inputMode="numeric"
                  max={pageCount}
                  min={1}
                  onChange={(event) => {
                    const value = Number(event.currentTarget.value);
                    if (Number.isInteger(value)) onPageChange(value);
                  }}
                  value={pageNumber}
                />
                <span className="text-muted tabular-nums">/ {pageCount}</span>
              </label>
              <IconButton
                disabled={pageNumber >= pageCount}
                label={labels.nextPage}
                onClick={() => onPageChange(pageNumber + 1)}
                variant="ghost"
              >
                <Icon glyph={NextIcon} size={20} />
              </IconButton>
            </div>
          ) : null}

          {view === "pdf" ? (
            <div className="hidden shrink-0 items-center gap-0.5 sm:flex">
              <IconButton
                label={labels.zoomOut}
                onClick={() => onZoomChange(Math.max(zoom - 0.1, 0.5))}
                variant="ghost"
              >
                <Icon glyph={ZoomOutIcon} size={20} />
              </IconButton>
              <span className="text-secondary w-12 text-center text-xs tabular-nums">
                {Math.round(zoom * 100)}%
              </span>
              <IconButton
                label={labels.zoomIn}
                onClick={() => onZoomChange(Math.min(zoom + 0.1, 3))}
                variant="ghost"
              >
                <Icon glyph={ZoomInIcon} size={20} />
              </IconButton>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <IconButton
                    label={`${labels.fit}: ${fitMode === "page" ? labels.fitPage : labels.fitWidth}`}
                    variant="ghost"
                  >
                    <Icon glyph={FitIcon} size={20} />
                  </IconButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="center">
                  <DropdownMenuItem onSelect={() => onFitModeChange("width")}>
                    {labels.fitWidth}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => onFitModeChange("page")}>
                    {labels.fitPage}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ) : null}

          <div className="ml-auto flex shrink-0 items-center gap-0.5">
            {view === "pdf" ? (
              <IconButton
                label={labels.search}
                onClick={onOpenSearch}
                variant="ghost"
              >
                <Icon glyph={SearchIcon} size={20} />
              </IconButton>
            ) : null}
            {view === "reflow" ? (
              <IconButton
                aria-pressed={outlineOpen}
                disabled={!outlineAvailable}
                label={outlineOpen ? labels.hideOutline : labels.showOutline}
                onClick={onToggleOutline}
                variant={outlineOpen ? "secondary" : "ghost"}
              >
                <Icon glyph={OutlineIcon} size={20} />
              </IconButton>
            ) : null}
            {view === "reflow" ? (
              <ReaderFullTranslationControl
                enabled={translation.enabled}
                onEnabledChange={translation.onEnabledChange}
                onPreferencesChange={translation.onPreferencesChange}
                preferences={translation.preferences}
                saving={translation.saving}
                status={translation.status}
              />
            ) : null}
            <IconButton
              label={labels.download}
              onClick={onDownload}
              variant="ghost"
            >
              <Icon glyph={DownloadIcon} size={20} />
            </IconButton>
            {!panelOpen ? (
              <IconButton
                aria-pressed={false}
                label={labels.openPanel}
                onClick={onOpenPanel}
                variant="ghost"
              >
                <Icon glyph={OpenPanelIcon} size={20} />
              </IconButton>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}
