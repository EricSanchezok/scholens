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
  IconButton,
  Input,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import type { ReaderFitMode } from "./pdf-page";

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
  returnLibrary: string;
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
  onZoomChange,
  pageCount,
  pageNumber,
  panelOpen,
  navigationMode,
  title,
  search,
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
  onZoomChange: (zoom: number) => void;
  pageCount: number;
  pageNumber: number;
  panelOpen: boolean;
  navigationMode: "outline" | "thumbnails";
  search?: {
    currentIndex: number;
    matchCount: number;
    onClose: () => void;
    onMove: (direction: -1 | 1) => void;
    onQueryChange: (query: string) => void;
    query: string;
  };
  title: string;
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
        <div className="hidden min-w-0 flex-1 items-center gap-1 lg:flex">
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
        </div>
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
          <div className="flex shrink-0 items-center gap-0.5">
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

          <div className="ml-auto flex shrink-0 items-center gap-0.5 lg:ml-0">
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
            <IconButton
              className="hidden sm:inline-flex"
              label={labels.download}
              onClick={onDownload}
              variant="ghost"
            >
              <Icon glyph={DownloadIcon} size={20} />
            </IconButton>
            {!panelOpen ? (
              <IconButton
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
