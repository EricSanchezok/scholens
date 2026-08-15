import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import { authHandlers } from "../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import { resetRefreshForTests } from "@/lib/api";
import { PapersView } from "./components/papers-view";
import type { PaperIngestionRow } from "./use-paper-ingestions";

const createdAt = "2026-08-12T02:00:00Z";
const emptyList = {
  items: [],
  next_cursor: null,
  previous_cursor: null,
  total_count: 0,
};

function row(
  state: PaperIngestionRow["state"],
  stage: PaperIngestionRow["stage"],
  errorCode?: string,
): PaperIngestionRow {
  return {
    createdAt,
    displayName: `${stage.replaceAll("_", "-")}.pdf`,
    errorCode,
    id: `${state}-${stage}`,
    retryable: true,
    sourceKind: "upload",
    stage,
    state,
  };
}

const meta = {
  title: "Features/Library/Paper ingestion rows",
  component: PapersView,
  args: {
    attentionCount: 0,
    data: emptyList,
    ingestions: [row("processing", "parsing")],
    ingestionCount: 1,
    loading: false,
    onCreateTag: async (name: string) => ({ color: null, id: name, name }),
    onDeleteTag: async () => undefined,
    onCancelIngestion: () => undefined,
    onDownload: () => undefined,
    onNext: () => undefined,
    onOpenPaper: () => undefined,
    onPrevious: () => undefined,
    onRemove: async () => undefined,
    onRenameTag: async (id: string, name: string) => ({
      color: null,
      id,
      name,
    }),
    onReplaceTags: async () => undefined,
    onRetryIngestion: () => undefined,
    onRetryLoad: () => undefined,
    onSortChange: () => undefined,
    onTagFilterChange: () => undefined,
    search: <div />,
    sort: "added_desc",
    paperCount: 0,
    tagIds: [],
    tags: [],
  },
  decorators: [
    (Story) => (
      <Providers>
        <main className="bg-canvas min-h-screen p-6">
          <Story />
        </main>
      </Providers>
    ),
  ],
  loaders: [
    async () => {
      resetRefreshForTests();
      return {};
    },
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: authHandlers.success },
  },
} satisfies Meta<typeof PapersView>;

export default meta;
type Story = StoryObj<typeof meta>;

function expectedCopy(copy: string) {
  return async ({ canvasElement }: { canvasElement: HTMLElement }) => {
    const matches = await within(canvasElement).findAllByText(copy);
    await expect(
      matches.some((element) => element.getClientRects().length > 0),
    ).toBe(true);
  };
}

export const Uploading: Story = {
  args: { ingestions: [row("uploading", "uploading")] },
  play: expectedCopy("Uploading PDF"),
};

export const Queued: Story = {
  args: { ingestions: [row("queued", "queued")] },
  play: expectedCopy("Waiting to process"),
};

export const Downloading: Story = {
  args: { ingestions: [row("processing", "downloading")] },
  play: expectedCopy("Downloading PDF"),
};

export const Parsing: Story = {
  args: { ingestions: [row("processing", "parsing")] },
  play: expectedCopy("Reading PDF"),
};

export const ExtractingMetadata: Story = {
  args: { ingestions: [row("processing", "extracting_metadata")] },
  play: expectedCopy("Extracting metadata"),
};

export const Indexing: Story = {
  args: { ingestions: [row("processing", "indexing")] },
  play: expectedCopy("Building search index"),
};

export const Finalizing: Story = {
  args: { ingestions: [row("processing", "finalizing")] },
  play: expectedCopy("Finishing import"),
};

export const Retrying: Story = {
  args: { ingestions: [row("retrying", "queued")] },
  play: expectedCopy("Retrying import"),
};

export const Cancelling: Story = {
  args: { ingestions: [row("cancelling", "parsing")] },
  play: expectedCopy("Cancelling import"),
};

export const Failed: Story = {
  args: {
    attentionCount: 1,
    ingestions: [row("failed", "queued", "paper_source_pdf_unavailable")],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const errorCopies = await canvas.findAllByText(
      "The source PDF is no longer available.",
    );
    await expect(
      errorCopies.some((element) => element.getClientRects().length > 0),
    ).toBe(true);
    await expect(
      canvas.getAllByRole("button", { name: "Retry" })[0],
    ).toBeVisible();
    await expect(
      canvas.getAllByRole("button", { name: "Remove failed import" })[0],
    ).toBeVisible();
  },
};

export const MinerUClassifiedFailures: Story = {
  args: {
    attentionCount: 6,
    ingestions: [
      {
        ...row("failed", "parsing", "mineru_credential_required"),
        displayName: "credential-required.pdf",
        id: "mineru-credential-required",
        requiredIntegration: "mineru",
      },
      {
        ...row("failed", "parsing", "mineru_credential_invalid"),
        displayName: "credential-invalid.pdf",
        id: "mineru-credential-invalid",
        requiredIntegration: "mineru",
      },
      {
        ...row("failed", "parsing", "mineru_rate_limited"),
        displayName: "rate-limited.pdf",
        id: "mineru-rate-limited",
      },
      {
        ...row("failed", "parsing", "mineru_unavailable"),
        displayName: "unavailable.pdf",
        id: "mineru-unavailable",
      },
      {
        ...row("failed", "parsing", "mineru_content_insufficient"),
        displayName: "content-insufficient.pdf",
        id: "mineru-content-insufficient",
        retryable: false,
      },
      {
        ...row("failed", "parsing", "mineru_response_unsafe"),
        displayName: "unsafe-response.pdf",
        id: "mineru-response-unsafe",
        retryable: false,
      },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const copies = [
      "This scanned PDF needs your MinerU token before processing can continue.",
      "Your MinerU token is no longer valid. Replace it in Settings and retry.",
      "MinerU is rate limiting requests. Retry after a short wait.",
      "MinerU is temporarily unavailable. The source and checkpoint are preserved for retry.",
      "MinerU could not recover enough reliable content from this PDF.",
      "MinerU returned an unsafe or invalid archive. Processing stopped without using it.",
    ];
    for (const copy of copies) {
      const matches = await canvas.findAllByText(copy);
      await expect(
        matches.some((element) => element.getClientRects().length > 0),
      ).toBe(true);
    }
    await expect(
      canvas.getAllByRole("button", { name: "Connect MinerU" })[0],
    ).toBeVisible();
  },
};

export const Mobile390Lifecycle: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  args: {
    attentionCount: 1,
    ingestions: [
      row("uploading", "uploading"),
      row("processing", "extracting_metadata"),
      row("failed", "queued", "invalid_pdf"),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("table")).not.toBeInTheDocument();
    const copies = [
      "Uploading PDF",
      "Extracting metadata",
      "This file is not a readable PDF.",
    ];
    for (const copy of copies) {
      const matches = await canvas.findAllByText(copy);
      await expect(
        matches.some((element) => element.getClientRects().length > 0),
      ).toBe(true);
    }
  },
};
