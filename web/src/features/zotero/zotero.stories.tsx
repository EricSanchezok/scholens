import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { delay, http, HttpResponse } from "msw";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ZoteroLibraryDialog } from "./zotero-library-dialog";
import { ZoteroOperationStatus } from "./zotero-operation-status";

const api = "http://127.0.0.1:7301/api/v1/integrations/zotero";
const status = {
  active_operation_id: null,
  active_operation_kind: null,
  auto_import_enabled: false,
  auto_import_state: "off",
  automatic_annotation_sync: "active",
  automatic_sync_eligible: true,
  connected_at: "2026-08-01T08:00:00Z",
  connection_state: "connected",
  last_error_code: null,
  last_successful_sync_at: "2026-08-15T09:30:00Z",
};
const items = [
  {
    authors: ["Ada Lovelace", "Alan Turing"],
    collection_keys: ["RECENT"],
    date: "2026-07-12",
    date_added: "2026-08-10T08:00:00Z",
    import_state: "available",
    item_type: "journalArticle",
    source_availability: "stored_pdf",
    tags: ["reasoning"],
    title: "Reliable long-context reasoning for scholarly evidence",
    venue: "Journal of Research Systems",
    zotero_item_key: "A1B2C3D4",
  },
  {
    authors: ["Grace Hopper"],
    collection_keys: [],
    date: "2025",
    date_added: "2026-08-09T08:00:00Z",
    import_state: "imported",
    item_type: "conferencePaper",
    source_availability: "stored_pdf",
    tags: [],
    title: "A paper already in Scholens",
    venue: "Systems Conference",
    zotero_item_key: "IMPORTED1",
  },
  {
    authors: [],
    collection_keys: [],
    date: null,
    date_added: "2026-08-08T08:00:00Z",
    import_state: "available",
    item_type: "preprint",
    source_availability: "unavailable",
    tags: [],
    title: "Metadata without an accessible source",
    venue: null,
    zotero_item_key: "NOPDF001",
  },
];

const connectedHandlers = [
  http.get(`${api}/status`, () => HttpResponse.json(status)),
  http.get(`${api}/collections`, () =>
    HttpResponse.json({
      items: [{ key: "RECENT", name: "Current reading" }],
      next_cursor: null,
      previous_cursor: null,
      total_count: 1,
    }),
  ),
  http.get(`${api}/library-items`, () =>
    HttpResponse.json({
      items,
      max_batch_size: 50,
      next_cursor: "next-page",
      previous_cursor: null,
      remaining_slots: 12,
      total_count: 38,
    }),
  ),
  http.post(`${api}/imports`, () =>
    HttpResponse.json(
      {
        completed_at: null,
        counts: { failed: 0, skipped: 0, succeeded: 0, total: 1 },
        created_at: "2026-08-16T08:00:00Z",
        error_code: null,
        id: "51000000-0000-4000-8000-000000000099",
        items: [],
        kind: "import",
        progress_code: null,
        started_at: null,
        status: "queued",
      },
      { status: 202 },
    ),
  ),
];

const meta = {
  title: "Features/Zotero/Library",
  component: ZoteroLibraryDialog,
  args: {
    onImportAccepted: fn(),
    onOpenChange: fn(),
    open: true,
  },
  loaders: [
    async () => {
      window.history.replaceState({}, "", "/library");
      return {};
    },
  ],
  parameters: {
    msw: { handlers: connectedHandlers },
    nextjs: { appDirectory: true },
  },
} satisfies Meta<typeof ZoteroLibraryDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Populated: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "Import from Zotero" }),
    ).toBeVisible();
    const paper = await body.findByText(
      "Reliable long-context reasoning for scholarly evidence",
    );
    const row = paper.closest("label");
    await expect(row).not.toBeNull();
    if (!row) return;
    await userEvent.click(within(row).getByRole("checkbox"));
    await expect(
      body.getByRole("button", { name: "Import 1 paper" }),
    ).toBeEnabled();
    await userEvent.click(body.getByRole("button", { name: "Import 1 paper" }));
    await waitFor(() => expect(args.onImportAccepted).toHaveBeenCalled());
  },
};

export const ManyCollections: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/collections`, ({ request }) => {
          const cursor = new URL(request.url).searchParams.get("cursor");
          if (cursor === "collections-page-2") {
            return HttpResponse.json({
              items: [{ key: "C0000101", name: "Collection 101" }],
              next_cursor: null,
              previous_cursor: "collections-page-1",
              total_count: 101,
            });
          }
          return HttpResponse.json({
            items: Array.from({ length: 100 }, (_, index) => ({
              key: `C${String(index + 1).padStart(7, "0")}`,
              name: `Collection ${index + 1}`,
            })),
            next_cursor: "collections-page-2",
            previous_cursor: null,
            total_count: 101,
          });
        }),
        ...connectedHandlers,
      ],
    },
  },
  play: async () => {
    const body = within(document.body);
    await userEvent.click(
      await body.findByRole("button", { name: "Load more collections" }),
    );
    await waitFor(() =>
      expect(
        body.queryByRole("button", { name: "Load more collections" }),
      ).not.toBeInTheDocument(),
    );
    await userEvent.click(body.getByRole("combobox", { name: "Collection" }));
    await expect(
      await body.findByRole("option", { name: "Collection 101" }),
    ).toBeVisible();
    await userEvent.keyboard("{Escape}");
  },
};

export const Empty: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/library-items`, () =>
          HttpResponse.json({
            items: [],
            max_batch_size: 50,
            next_cursor: null,
            previous_cursor: null,
            remaining_slots: 12,
            total_count: 0,
          }),
        ),
        ...connectedHandlers,
      ],
    },
  },
};

export const Slow: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/library-items`, async () => {
          await delay("infinite");
          return HttpResponse.json({ items: [] });
        }),
        ...connectedHandlers,
      ],
    },
  },
};

export const RateLimited: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/library-items`, () =>
          HttpResponse.json({ code: "zotero_rate_limited" }, { status: 503 }),
        ),
        ...connectedHandlers,
      ],
    },
  },
};

export const Disconnected: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/status`, () =>
          HttpResponse.json({
            ...status,
            automatic_annotation_sync: "off",
            automatic_sync_eligible: false,
            connected_at: null,
            connection_state: "disconnected",
            last_successful_sync_at: null,
          }),
        ),
        ...connectedHandlers,
      ],
    },
  },
};

export const ZeroQuota: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/library-items`, () =>
          HttpResponse.json({
            items,
            max_batch_size: 50,
            next_cursor: null,
            previous_cursor: null,
            remaining_slots: 0,
            total_count: 3,
          }),
        ),
        ...connectedHandlers,
      ],
    },
  },
  play: async () => {
    const body = within(document.body);
    const paper = await body.findByText(
      "Reliable long-context reasoning for scholarly evidence",
    );
    const row = paper.closest("label");
    await expect(row).not.toBeNull();
    if (!row) return;
    await expect(within(row).getByRole("checkbox")).toBeDisabled();
    await expect(
      body.getByRole("button", { name: "Import 0 papers" }),
    ).toBeDisabled();
  },
};

export const PaginationKeepsSelection: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/library-items`, ({ request }) => {
          const cursor = new URL(request.url).searchParams.get("cursor");
          return HttpResponse.json({
            items: cursor
              ? [
                  {
                    ...items[0],
                    title: "Paper on the second Zotero page",
                    zotero_item_key: "PAGE0002",
                  },
                ]
              : [items[0]],
            max_batch_size: 50,
            next_cursor: cursor ? null : "next-page",
            previous_cursor: cursor ? "previous-page" : null,
            remaining_slots: 12,
            total_count: 2,
          });
        }),
        ...connectedHandlers,
      ],
    },
  },
  play: async () => {
    const body = within(document.body);
    const first = await body.findByText(
      "Reliable long-context reasoning for scholarly evidence",
    );
    const row = first.closest("label");
    if (!row) throw new Error("Zotero row was not rendered");
    const checkbox = within(row).getByRole("checkbox");
    checkbox.focus();
    await userEvent.keyboard(" ");
    await expect(checkbox).toBeChecked();
    await userEvent.click(body.getByRole("button", { name: "Next" }));
    await expect(
      await body.findByText("Paper on the second Zotero page"),
    ).toBeVisible();
    await expect(
      body.getByRole("button", { name: "Import 1 paper" }),
    ).toBeEnabled();
  },
};

export const Offline: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/library-items`, () => HttpResponse.error()),
        ...connectedHandlers,
      ],
    },
  },
};

export const InvalidPermission: Story = {
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/library-items`, () =>
          HttpResponse.json(
            { code: "zotero_permissions_insufficient" },
            { status: 403 },
          ),
        ),
        ...connectedHandlers,
      ],
    },
  },
};

export const Mobile390: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const Mobile320: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
};

export const DarkChinese: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
};

export const PartialSuccess: Story = {
  render: () => (
    <ZoteroOperationStatus
      initialOperation={{
        completed_at: "2026-08-16T08:02:00Z",
        counts: { failed: 1, skipped: 0, succeeded: 2, total: 3 },
        created_at: "2026-08-16T08:00:00Z",
        error_code: null,
        id: "51000000-0000-4000-8000-000000000099",
        items: [
          {
            error_code: "zotero_pdf_unavailable",
            status: "failed",
            title: "Unavailable source",
            zotero_item_key: "NOPDF001",
          },
        ],
        kind: "import",
        started_at: "2026-08-16T08:00:10Z",
        status: "partial",
      }}
      operationId="51000000-0000-4000-8000-000000000099"
      onComplete={fn()}
      onDismiss={fn()}
    />
  ),
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/imports/:operationId`, () =>
          HttpResponse.json({
            completed_at: "2026-08-16T08:02:00Z",
            counts: { failed: 1, skipped: 0, succeeded: 2, total: 3 },
            created_at: "2026-08-16T08:00:00Z",
            error_code: null,
            id: "51000000-0000-4000-8000-000000000099",
            items: [],
            kind: "import",
            started_at: "2026-08-16T08:00:10Z",
            status: "partial",
          }),
        ),
      ],
    },
  },
};

export const FailedCallbackTimeout: Story = {
  render: () => (
    <ZoteroOperationStatus
      initialOperation={{
        completed_at: "2026-08-16T08:12:00Z",
        counts: { failed: 0, skipped: 0, succeeded: 0, total: 2 },
        created_at: "2026-08-16T08:00:00Z",
        error_code: "zotero_callback_processing_timeout",
        id: "51000000-0000-4000-8000-000000000102",
        items: [],
        kind: "import",
        started_at: "2026-08-16T08:00:10Z",
        status: "failed",
      }}
      operationId="51000000-0000-4000-8000-000000000102"
      onComplete={fn()}
      onDismiss={fn()}
    />
  ),
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/imports/:operationId`, () =>
          HttpResponse.json({
            completed_at: "2026-08-16T08:12:00Z",
            counts: { failed: 0, skipped: 0, succeeded: 0, total: 2 },
            created_at: "2026-08-16T08:00:00Z",
            error_code: "zotero_callback_processing_timeout",
            id: "51000000-0000-4000-8000-000000000102",
            items: [],
            kind: "import",
            started_at: "2026-08-16T08:00:10Z",
            status: "failed",
          }),
        ),
      ],
    },
  },
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByText(
        "Scholens took too long to finish this Zotero batch. Try the import or sync again.",
      ),
    ).toBeVisible();
  },
};

export const RecoveredRunningImport: Story = {
  render: () => (
    <ZoteroOperationStatus
      operationId="51000000-0000-4000-8000-000000000100"
      onComplete={fn()}
      onDismiss={fn()}
    />
  ),
  parameters: {
    msw: {
      handlers: [
        http.get(`${api}/imports/:operationId`, () =>
          HttpResponse.json({
            completed_at: null,
            counts: { failed: 0, skipped: 0, succeeded: 0, total: 2 },
            created_at: "2026-08-16T08:00:00Z",
            error_code: null,
            id: "51000000-0000-4000-8000-000000000100",
            items: [
              { status: "running", zotero_item_key: "ITEM1" },
              { status: "running", zotero_item_key: "ITEM2" },
            ],
            kind: "import",
            progress_code: "importing_papers",
            started_at: "2026-08-16T08:00:10Z",
            status: "running",
          }),
        ),
      ],
    },
  },
  play: async () => {
    const body = within(document.body);
    await expect(
      await body.findByText("Preparing selected papers"),
    ).toBeVisible();
    await expect(body.getByText("0 of 2 accepted · 0 failed")).toBeVisible();
    await expect(body.queryByRole("progressbar")).not.toBeInTheDocument();
  },
};
