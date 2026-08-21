import { delay, http, HttpResponse } from "msw";

const apiUrl = "http://127.0.0.1:7301/api/v1/foundation-check";
const zoteroStatusUrl =
  "http://127.0.0.1:7301/api/v1/integrations/zotero/status";
const zoteroCollectionsUrl =
  "http://127.0.0.1:7301/api/v1/integrations/zotero/collections";
const zoteroLibraryItemsUrl =
  "http://127.0.0.1:7301/api/v1/integrations/zotero/library-items";
const paperSearchUrl = "http://127.0.0.1:7301/api/v1/search/papers";
const conversationSearchUrl =
  "http://127.0.0.1:7301/api/v1/search/conversations";
const paperListPreferencesUrl =
  "http://127.0.0.1:7301/api/v1/me/paper-list-preferences";
const libraryTagsUrl = "http://127.0.0.1:7301/api/v1/library/tags";

export const paperListPreferencesHandlers = [
  http.get(paperListPreferencesUrl, () =>
    HttpResponse.json({
      column_widths: [
        { column: "paper", width: 360 },
        { column: "status", width: 96 },
        { column: "tags", width: 160 },
        { column: "authors", width: 176 },
        { column: "publication", width: 144 },
        { column: "last_opened", width: 120 },
        { column: "added_at", width: 120 },
        { column: "doi", width: 160 },
      ],
      preview_open: true,
      preview_width: 512,
      visible_columns: [
        "status",
        "tags",
        "authors",
        "publication",
        "last_opened",
      ],
    }),
  ),
  http.put(paperListPreferencesUrl, async ({ request }) =>
    HttpResponse.json(await request.json()),
  ),
];

export const libraryTagsHandler = http.get(libraryTagsUrl, () =>
  HttpResponse.json({ items: [] }),
);

export const webPerformanceHandler = http.post(
  "*/__telemetry/web-performance",
  () => new HttpResponse(null, { status: 204 }),
);

export const foundationHandler = http.get(apiUrl, async ({ request }) => {
  const scenario = new URL(request.url).searchParams.get("scenario") ?? "";
  const network = scenario.startsWith("slow")
    ? "slow"
    : scenario.startsWith("offline")
      ? "offline"
      : "instant";
  const data = scenario.endsWith("empty")
    ? "empty"
    : scenario.endsWith("error")
      ? "error"
      : "populated";
  if (network === "offline") return HttpResponse.error();
  if (network === "slow") await delay(1800);
  if (data === "error")
    return HttpResponse.json({ message: "Server error" }, { status: 500 });
  return HttpResponse.json({
    items: data === "empty" ? [] : [{ id: "1", title: "Foundation item" }],
  });
});

export const zoteroStatusHandler = http.get(zoteroStatusUrl, () =>
  HttpResponse.json({
    active_operation_id: null,
    active_operation_kind: null,
    auto_import_enabled: false,
    auto_import_state: "off",
    automatic_annotation_sync: "off",
    automatic_sync_eligible: false,
    connected_at: null,
    connection_state: "disconnected",
    last_error_code: null,
    last_successful_sync_at: null,
  }),
);

export const zoteroCollectionsHandler = http.get(zoteroCollectionsUrl, () =>
  HttpResponse.json({
    items: [],
    next_cursor: null,
    previous_cursor: null,
    total_count: 0,
  }),
);

export const zoteroLibraryItemsHandler = http.get(zoteroLibraryItemsUrl, () =>
  HttpResponse.json({
    items: [],
    max_batch_size: 50,
    next_cursor: null,
    previous_cursor: null,
    remaining_slots: 50,
    total_count: 0,
  }),
);

export const paperSearchHandler = http.post(paperSearchUrl, () =>
  HttpResponse.json({
    items: [
      {
        abstract:
          "The model learns program semantics from execution traces and uses them to improve code reasoning.",
        authors: ["Jade Copet", "Quentin Carbonneaux"],
        created_at: "2026-08-20T08:00:00Z",
        document_id: "00000000-0000-4000-8000-000000000001",
        last_accessed_at: "2026-08-20T08:00:00Z",
        matched_fields: ["title", "abstract"],
        preview_url: null,
        publish_date: "2026-08-20T08:00:00Z",
        retrieval_modes: ["exact", "semantic"],
        snippets: [
          {
            text: "Execution traces provide grounded supervision for a learned code world model.",
          },
        ],
        status: "completed",
        summary: null,
        title: "CWM: An Open-Weights LLM for Code Generation with World Models",
      },
    ],
    next_cursor: null,
    search_mode: "hybrid",
    semantic_index_coverage: 1,
    total: 1,
  }),
);

export const conversationSearchHandler = http.post(conversationSearchUrl, () =>
  HttpResponse.json({
    items: [
      {
        conversation: {
          archived_at: null,
          capabilities: {
            archive: true,
            delete: true,
            detach: false,
            move: true,
            pin: true,
            rename: true,
            send: true,
            share: false,
          },
          id: "76000000-0000-4000-8000-000000000001",
          pinned_at: null,
          read_only: false,
          read_only_reason: null,
          scope_access: "active",
          scope_id: null,
          scope_label: "Memory systems",
          scope_type: "global",
          title: "Comparing memory retrieval strategies",
          updated_at: "2026-08-20T08:00:00Z",
        },
        matched_field: "assistant_response",
        snippet:
          "The selected answer compares retrieval strategies across long-running memory systems.",
      },
    ],
    next_cursor: null,
    total: 1,
  }),
);

export const successHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json({ items: [{ id: "1", title: "Foundation item" }] }),
  ),
];
export const slowHandlers = [
  http.get(apiUrl, async () => {
    await delay(1800);
    return HttpResponse.json({ items: [{ id: "1", title: "Delayed item" }] });
  }),
];
export const emptyHandlers = [
  http.get(apiUrl, () => HttpResponse.json({ items: [] })),
];
export const businessErrorHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json(
      { code: "LIMIT_REACHED", message: "The operation is not available." },
      { status: 409 },
    ),
  ),
];
export const serverErrorHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json({ message: "Server error" }, { status: 500 }),
  ),
];
export const unauthorizedHandlers = [
  http.get(apiUrl, () =>
    HttpResponse.json({ message: "Unauthorized" }, { status: 401 }),
  ),
];
export const offlineHandlers = [http.get(apiUrl, () => HttpResponse.error())];
