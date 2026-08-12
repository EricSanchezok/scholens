import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { fn } from "storybook/test";

import { ReaderToolbar } from "./reader-toolbar";

const labels = {
  download: "Download PDF",
  fit: "Fit",
  fitPage: "Fit page",
  fitWidth: "Fit width",
  nextPage: "Next page",
  openPanel: "Open context panel",
  outline: "Document outline",
  page: "Page",
  previousPage: "Previous page",
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
    onZoomChange: fn(),
    pageCount: 18,
    pageNumber: 4,
    panelOpen: false,
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
  globals: { viewport: { value: "mobile1" } },
};

export const ContextPanelOpen: Story = {
  args: { panelOpen: true },
};
