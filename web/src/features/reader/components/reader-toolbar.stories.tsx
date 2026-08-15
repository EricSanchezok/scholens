import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, within } from "storybook/test";

import { ReaderToolbar } from "./reader-toolbar";

const labels = {
  closePanel: "Close context panel",
  download: "Download PDF",
  closeSearch: "Close PDF search",
  fit: "Fit",
  fitPage: "Fit page",
  fitWidth: "Fit width",
  hideOutline: "Hide document outline",
  nextPage: "Next page",
  nextSearchResult: "Next match",
  noSearchResults: "No matches",
  openPanel: "Open context panel",
  page: "Page",
  previousPage: "Previous page",
  previousSearchResult: "Previous match",
  returnLibrary: "Return to library",
  projectContext: "Reader context",
  personalContext: "Personal reading",
  pdfView: "PDF",
  reflowView: "AI reflow",
  search: "Search PDF",
  showOutline: "Show document outline",
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
    onToggleOutline: fn(),
    onOpenPanel: fn(),
    onOpenSearch: fn(),
    onPageChange: fn(),
    onReturn: fn(),
    onViewChange: fn(),
    onZoomChange: fn(),
    pageCount: 18,
    pageNumber: 4,
    panelOpen: false,
    outlineAvailable: false,
    outlineOpen: false,
    title: "Retrieval-Augmented Generation: Foundations and Open Questions",
    translation: {
      enabled: false,
      onEnabledChange: fn(),
      onPreferencesChange: fn(async () => undefined),
      preferences: {
        auto_translate_selection: true,
        custom_instructions: null,
        full_translation_display: "bilingual",
        show_translation_marker: true,
        source_language: "auto",
        target_language: "zh-CN",
        translate_references: false,
      },
      saving: false,
      status: "idle",
    },
    metadata: "A. Researcher · 10.1000/rag.2026",
    zoom: 1,
    view: "pdf",
  },
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof ReaderToolbar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Desktop: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toolbar = canvas.getByRole("toolbar", { name: labels.page });
    const panelToggle = canvas.getByRole("button", {
      name: labels.openPanel,
    });
    const toolbarBounds = toolbar.getBoundingClientRect();
    const toggleBounds = panelToggle.getBoundingClientRect();

    await expect(
      canvas.queryByRole("button", { name: /Full translation/ }),
    ).not.toBeInTheDocument();
    await expect(toolbarBounds.right - toggleBounds.right).toBeLessThanOrEqual(
      16,
    );
  },
};

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

export const Reflow: Story = {
  args: { outlineAvailable: true, view: "reflow" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: /Full translation/ }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: labels.showOutline }),
    ).toBeVisible();
  },
};

export const ReflowOutlineOpen: Story = {
  args: { outlineAvailable: true, outlineOpen: true, view: "reflow" },
};

export const ReflowSmallMobile: Story = {
  args: { outlineAvailable: true, view: "reflow" },
  globals: { viewport: { value: "smallMobile" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toolbar = canvas.getByRole("toolbar", { name: labels.page });

    await expect(
      canvas.getByRole("button", { name: labels.showOutline }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: labels.download }),
    ).toBeVisible();
    await expect(
      canvas.queryByRole("button", { name: "More actions" }),
    ).not.toBeInTheDocument();
    await expect(toolbar.scrollWidth).toBeLessThanOrEqual(toolbar.clientWidth);
  },
};

export const ProjectContext: Story = {
  args: {
    projectContext: {
      onChange: fn(),
      options: [
        { id: "project-1", title: "Agentic Web review" },
        { id: "project-2", title: "Dissertation methods" },
      ],
      projectId: "project-1",
    },
  },
};

export const FirstPage: Story = {
  args: { pageNumber: 1 },
};

export const LastPage: Story = {
  args: { pageNumber: 18 },
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
