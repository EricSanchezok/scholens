import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { fn } from "storybook/test";

import { ReaderToolbar } from "./reader-toolbar";

const labels = {
  download: "Download PDF",
  closeSearch: "Close PDF search",
  fit: "Fit",
  fitPage: "Fit page",
  fitWidth: "Fit width",
  nextPage: "Next page",
  nextSearchResult: "Next match",
  noSearchResults: "No matches",
  openPanel: "Open context panel",
  outline: "Document outline",
  page: "Page",
  previousPage: "Previous page",
  previousSearchResult: "Previous match",
  returnLibrary: "Return to library",
  search: "Search PDF",
  zoomIn: "Zoom in",
  zoomOut: "Zoom out",
};

const meta = {
  title: "Reader/ReaderToolbar",
  component: ReaderToolbar,
  args: {
    fitMode: "width",
    labels,
    onDownload: fn(),
    onFitModeChange: fn(),
    onOpenOutline: fn(),
    onOpenPanel: fn(),
    onOpenSearch: fn(),
    onPageChange: fn(),
    onReturn: fn(),
    onZoomChange: fn(),
    pageCount: 18,
    pageNumber: 4,
    panelOpen: false,
    title: "Retrieval-Augmented Generation: Foundations and Open Questions",
    metadata: "A. Researcher · 10.1000/rag.2026",
    zoom: 1,
  },
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof ReaderToolbar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Desktop: Story = {};

export const Narrow: Story = {
  globals: { viewport: { value: "mobile" } },
};

export const SmallMobile: Story = {
  globals: { viewport: { value: "smallMobile" } },
};

export const LargeMobile: Story = {
  globals: { viewport: { value: "largeMobile" } },
};

export const ContextPanelOpen: Story = {
  args: { panelOpen: true },
};

export const SearchOpen: Story = {
  args: {
    search: {
      currentIndex: 2,
      matchCount: 8,
      onClose: fn(),
      onMove: fn(),
      onQueryChange: fn(),
      query: "retrieval",
    },
  },
};
