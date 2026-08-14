"use client";

import {
  BackIcon,
  DownloadIcon,
  FitIcon,
  OutlineIcon,
  PreviousIcon,
  NextIcon,
  DocumentIcon,
  SearchIcon,
  OpenPanelIcon,
  ClosePanelIcon,
  DismissIcon,
  MoreIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from "@/design-system/icons/semantic-icons";
import * as React from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  IconButton,
  Button,
  Input,
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
  showPages: string;
  download: string;
  openPanel: string;
  closePanel: string;
  moreActions: string;
  returnLibrary: string;
  projectContext: string;
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
  onToggleNavigation,
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
  navigationMode,
  title,
  view,
  search,
  translation,
  reflowOutline,
  zoom,
}: {
  className?: string;
  fitMode: ReaderFitMode;
  labels: ReaderToolbarLabels;
  metadata?: string;
  onDownload: () => void;
  onFitModeChange: (fit: ReaderFitMode) => void;
  onToggleNavigation: () => void;
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
  navigationMode: "outline" | "thumbnails";
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
  reflowOutline?: Array<{
    id: string;
    label: string;
    onSelect: () => void;
  }>;
  title: string;
  view: ReaderDocumentView;
  zoom: number;
}) {
  return (
    <div
      aria-label={labels.page}
      className={cn(
        "border-line bg-surface flex h-14 shrink-0 items-center gap-2 border-b px-2 sm:px-3",
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
                aria-label={labels.projectContext}
                className="ml-2 h-9 min-h-9 w-40"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="personal">
                  {labels.personalContext}
                </SelectItem>
                {projectContext.options.map((project) => (
                  <SelectItem key={project.id} value={project.id}>
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
            aria-label={labels.projectContext}
            className="hidden h-9 min-h-9 min-w-0 flex-1 sm:flex 2xl:hidden"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="personal">{labels.personalContext}</SelectItem>
            {projectContext.options.map((project) => (
              <SelectItem key={project.id} value={project.id}>
                {project.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}

      {search ? (
        <div className="flex min-w-0 flex-1 items-center gap-1">
          <div className="border-line bg-canvas flex h-9 min-w-0 flex-1 items-center rounded-[var(--radius-md)] border pl-2">
            <Icon glyph={SearchIcon} size={20} tone="secondary" />
            <Input
              aria-label={labels.search}
              autoFocus
              className="h-8 min-w-0 border-0 bg-transparent px-2 shadow-none"
              onChange={(event) =>
                search.onQueryChange(event.currentTarget.value)
              }
              onKeyDown={(event) => {
                if (event.key === "Escape") search.onClose();
                if (event.key === "Enter") {
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
              className="px-2.5 sm:h-8 sm:min-h-8"
              onClick={() => onViewChange("pdf")}
              size="sm"
              variant={view === "pdf" ? "secondary" : "ghost"}
            >
              {labels.pdfView}
            </Button>
            <Button
              aria-pressed={view === "reflow"}
              className="px-2.5 sm:h-8 sm:min-h-8"
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
              <label className="border-line bg-canvas flex h-9 items-center rounded-[var(--radius-md)] border px-2 text-sm">
                <span className="sr-only">{labels.page}</span>
                <input
                  aria-label={labels.page}
                  className="w-8 bg-transparent text-center tabular-nums outline-none"
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

          <div className="ml-auto flex shrink-0 items-center gap-0.5 lg:ml-0">
            {view === "pdf" ? (
              <>
                <IconButton
                  label={labels.search}
                  onClick={onOpenSearch}
                  variant="ghost"
                >
                  <Icon glyph={SearchIcon} size={20} />
                </IconButton>
                <IconButton
                  aria-pressed={navigationMode === "outline"}
                  label={
                    navigationMode === "outline"
                      ? labels.showPages
                      : labels.showOutline
                  }
                  onClick={onToggleNavigation}
                  variant="ghost"
                >
                  <Icon
                    glyph={
                      navigationMode === "outline" ? DocumentIcon : OutlineIcon
                    }
                    size={20}
                  />
                </IconButton>
              </>
            ) : null}
            {view === "reflow" && reflowOutline?.length ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <IconButton
                    className="hidden sm:inline-flex"
                    label={labels.showOutline}
                    variant="ghost"
                  >
                    <Icon glyph={OutlineIcon} size={20} />
                  </IconButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="end"
                  className="max-h-80 w-72 overflow-y-auto"
                >
                  {reflowOutline.map((item) => (
                    <DropdownMenuItem key={item.id} onSelect={item.onSelect}>
                      <span className="truncate">{item.label}</span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
            <ReaderFullTranslationControl
              enabled={translation.enabled}
              onEnabledChange={translation.onEnabledChange}
              onPreferencesChange={translation.onPreferencesChange}
              preferences={translation.preferences}
              saving={translation.saving}
              status={translation.status}
              view={view}
            />
            <IconButton
              className="hidden sm:inline-flex"
              label={labels.download}
              onClick={onDownload}
              variant="ghost"
            >
              <Icon glyph={DownloadIcon} size={20} />
            </IconButton>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <IconButton
                  className="inline-flex sm:hidden"
                  label={labels.moreActions}
                  variant="ghost"
                >
                  <Icon glyph={MoreIcon} size={20} />
                </IconButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {view === "pdf" ? (
                  <DropdownMenuItem onSelect={onOpenSearch}>
                    <Icon glyph={SearchIcon} size={20} />
                    {labels.search}
                  </DropdownMenuItem>
                ) : null}
                {view === "reflow" && reflowOutline?.length
                  ? reflowOutline.map((item) => (
                      <DropdownMenuItem key={item.id} onSelect={item.onSelect}>
                        <span className="max-w-56 truncate">{item.label}</span>
                      </DropdownMenuItem>
                    ))
                  : null}
                <DropdownMenuItem onSelect={onDownload}>
                  <Icon glyph={DownloadIcon} size={20} />
                  {labels.download}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <IconButton
              aria-pressed={panelOpen}
              label={panelOpen ? labels.closePanel : labels.openPanel}
              onClick={onOpenPanel}
              variant="ghost"
            >
              <Icon
                glyph={panelOpen ? ClosePanelIcon : OpenPanelIcon}
                size={20}
              />
            </IconButton>
          </div>
        </>
      )}
    </div>
  );
}
