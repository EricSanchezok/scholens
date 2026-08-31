import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { mockBillingUsage } from "./billing-fixture";
import { focusThroughTab } from "./focus";
import { mockVisualViewport, setVisualViewport } from "./visual-viewport";
import path from "node:path";

import { libraryPapers } from "../../src/features/library/api/fixtures";
import {
  projectFixtures,
  projectPaperFixtures,
} from "../../src/features/projects/api/fixtures";

const apiPattern = "**/api/v1";
const paperDocument = libraryPapers[0]!.document;
const readerProject = {
  ...projectFixtures[0]!,
  id: "50000000-0000-4000-8000-000000000001",
  num_papers: 1,
  title: "Agentic Web review",
};
const readerProjectPaper = {
  ...projectPaperFixtures[0]!,
  document_id: paperDocument.document_id,
  title: paperDocument.title,
};
const pdfPath = path.resolve(
  "../server/evals/seed_data/chain_of_thought_for_reasoning.pdf",
);
const actor = {
  id: 7,
  email: "eric@scholens.ai",
  email_verified: true,
  is_active: true,
  is_admin: false,
  is_blocked: false,
  status: "active",
  display_name: "Eric",
  locale: "en",
};

const reflowSourceSpan = (
  pageNumber: number,
  sourceText: string,
  sourceRect: { height: number; width: number; x: number; y: number },
) => ({
  page_number: pageNumber,
  source_rect: sourceRect,
  source_text: sourceText,
});

const reflowBlocks = [
  {
    asset_id: null,
    group_id: null,
    heading_level: 1,
    id: "reflow-title",
    index: 0,
    kind: "title",
    presentation_status: "verbatim",
    render_markdown: "# Evidence-driven academic reading",
    source_spans: [
      reflowSourceSpan(1, "Evidence-driven academic reading", {
        height: 0.08,
        width: 0.72,
        x: 0.14,
        y: 0.12,
      }),
    ],
  },
  {
    asset_id: null,
    group_id: "paper-information",
    heading_level: null,
    id: "reflow-authors",
    index: 1,
    kind: "authors",
    presentation_status: "repaired",
    render_markdown: "Ada Researcher<sup>1</sup> · Lin Scholar<sup>2</sup>",
    source_spans: [
      reflowSourceSpan(1, "Ada Researcher¹ · Lin Scholar²", {
        height: 0.05,
        width: 0.72,
        x: 0.14,
        y: 0.21,
      }),
    ],
  },
  {
    asset_id: null,
    group_id: null,
    heading_level: 2,
    id: "reflow-method",
    index: 2,
    kind: "heading",
    presentation_status: "verbatim",
    render_markdown: "## 1 Method",
    source_spans: [
      reflowSourceSpan(2, "1 Method", {
        height: 0.05,
        width: 0.72,
        x: 0.14,
        y: 0.12,
      }),
    ],
  },
  {
    asset_id: null,
    group_id: null,
    heading_level: null,
    id: "reflow-paragraph",
    index: 3,
    kind: "paragraph",
    presentation_status: "verbatim",
    render_markdown:
      "The reconstruction keeps every claim traceable to visible PDF evidence.",
    source_spans: [
      reflowSourceSpan(
        2,
        "The reconstruction keeps every claim traceable to visible PDF evidence.",
        { height: 0.12, width: 0.72, x: 0.14, y: 0.2 },
      ),
    ],
  },
  {
    asset_id: null,
    group_id: null,
    heading_level: null,
    id: "reflow-table",
    index: 4,
    kind: "table",
    presentation_status: "verbatim",
    render_markdown:
      "| Evidence source | Coverage | Confidence | Review state |\n| --- | ---: | ---: | --- |\n| PDF region | 100% | 0.98 | verified |",
    source_spans: [
      reflowSourceSpan(2, "Evidence source Coverage Confidence Review state", {
        height: 0.18,
        width: 0.72,
        x: 0.14,
        y: 0.36,
      }),
    ],
  },
];

function annotationFixture({
  audience = { kind: "personal" },
  comments = ["Compare this claim with the project benchmark."],
  id,
  position,
  status = "open",
}: {
  audience?: { kind: "personal" } | { kind: "project"; project_id: string };
  comments?: string[];
  id: string;
  position: {
    kind: "pdf_text";
    page_number: number;
    rects: Array<{ height: number; width: number; x: number; y: number }>;
  };
  status?: "open" | "resolved";
}) {
  return {
    id,
    kind: "annotation_thread",
    audience,
    target_document_id: paperDocument.document_id,
    created_at: "2026-08-13T12:00:00Z",
    updated_at: "2026-08-13T12:00:00Z",
    created_by: { id: actor.id, display_name: actor.display_name },
    capabilities: { delete: true, edit: true },
    annotation_thread: {
      capabilities: {
        delete: status === "open",
        recolor: true,
        reopen: status === "resolved",
        reply: status === "open",
        resolve: status === "open",
      },
      color: status === "resolved" ? "gray" : "yellow",
      comment_count: comments.length,
      last_activity_at: "2026-08-13T12:00:00Z",
      mode:
        comments.length === 0
          ? "highlight"
          : audience.kind === "project"
            ? "discussion"
            : "note",
      comments: comments.map((content, index) => ({
        id: `${id.slice(0, -1)}${index + 4}`,
        thread_id: id,
        content,
        role: "user",
        created_at: "2026-08-13T12:00:00Z",
        updated_at: "2026-08-13T12:00:00Z",
        created_by: { id: actor.id, display_name: actor.display_name },
        can_edit: true,
        can_delete: true,
      })),
      position,
      quote_text: "The NLP landscape has recently been revolutionized.",
      role: "note",
      status,
      resolved_at: status === "resolved" ? "2026-08-13T12:05:00Z" : null,
      resolved_by:
        status === "resolved"
          ? { id: actor.id, display_name: actor.display_name }
          : null,
    },
  };
}

function annotationSummary(item: ReturnType<typeof annotationFixture>) {
  const thread = item.annotation_thread;
  return {
    audience: item.audience,
    capabilities: thread.capabilities,
    color: thread.color,
    comment_count: thread.comment_count,
    comments: thread.comments,
    created_at: item.created_at,
    created_by: item.created_by,
    id: item.id,
    last_activity_at: thread.last_activity_at,
    mode: thread.mode,
    position: thread.position,
    quote_text: thread.quote_text,
    resolved_at: thread.resolved_at,
    resolved_by: thread.resolved_by,
    role: thread.role,
    status: thread.status,
    target_document_id: item.target_document_id,
  };
}

const createdAnnotationQuotes: string[] = [];
const createdAnnotationPositions: Array<Record<string, unknown>> = [];

async function mockReader(page: Page) {
  await mockBillingUsage(page);
  const annotations: Array<Record<string, unknown>> = [];
  let readingPreferences = {
    contribute_anonymous_project_aggregates: true,
    recording_enabled: false,
  };
  await page.route(`${apiPattern}/auth/bootstrap`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "playwright-access",
        actor,
        token_type: "bearer",
      }),
    }),
  );
  await page.route(`${apiPattern}/conversations**`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );
  await page.route(
    `${apiPattern}/me/reading-activity-preferences`,
    async (route) => {
      if (route.request().method() === "PUT") {
        readingPreferences = route
          .request()
          .postDataJSON() as typeof readingPreferences;
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(readingPreferences),
      });
    },
  );
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/insights**`,
    async (route) => {
      const url = new URL(route.request().url());
      const range = url.searchParams.get("range") ?? "30d";
      const allTime = range === "all";
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          activity_history_complete_since: "2026-01-01T00:00:00Z",
          document_id: paperDocument.document_id,
          metric_definition_version: "active-reading-v1",
          page_count: 4,
          pages: allTime
            ? [
                {
                  active_ms: 180_000,
                  annotation_count: 1,
                  page_number: 2,
                  vertical_segments_ms: [
                    0, 0, 0, 0, 0, 0, 0, 0, 0, 180_000, 0, 0, 0, 0, 0, 0, 0, 0,
                    0, 0,
                  ],
                  visible_ms: 240_000,
                  visit_count: 2,
                },
              ]
            : [],
          range,
          reading_data_since: "2026-08-01T00:00:00Z",
          summary: {
            active_days: 3,
            active_ms: 180_000,
            coverage_percent: allTime ? 25 : null,
            session_count: 2,
            substantive_pages: allTime ? 1 : null,
            visible_ms: 240_000,
          },
          time_zone: url.searchParams.get("time_zone") ?? "UTC",
          trend: allTime
            ? []
            : [
                {
                  active_ms: 180_000,
                  date: "2026-08-24",
                  session_count: 2,
                  visible_ms: 240_000,
                },
              ],
        }),
      });
    },
  );
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/reading-activity`,
    (route) => route.fulfill({ status: 204 }),
  );
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(paperDocument),
      }),
  );
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/projects`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: [readerProject],
          next_cursor: null,
          total_count: 1,
        }),
      }),
  );
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/download-url`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          expires_in_seconds: 300,
          file_url: "http://127.0.0.1:7300/reader-test.pdf",
        }),
      }),
  );
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/selection-translations`,
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      const body = route.request().postDataJSON() as { text: string };
      const prefix = body.text.slice(0, 24) || "selected text";
      await route.fulfill({
        contentType: "text/event-stream",
        headers: { "Cache-Control": "no-cache" },
        body: [
          `event: start\ndata: ${JSON.stringify({
            cache_hit: false,
            target_language: "zh-CN",
          })}\n\n`,
          `event: delta\ndata: ${JSON.stringify({ text: `译文：${prefix}。` })}\n\n`,
          `event: delta\ndata: ${JSON.stringify({
            text: "这是一段较长的增量内容，用来验证预览正文只向下增长并在达到上限后保持内部滚动。".repeat(
              8,
            ),
          })}\n\n`,
          `event: complete\ndata: ${JSON.stringify({ cache_hit: false })}\n\n`,
        ].join(""),
      });
    },
  );
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/annotation-threads**`,
    async (route) => {
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON() as {
          audience: { kind: "personal" | "project"; project_id?: string };
          color: string;
          initial_comment?: string;
          position: Record<string, unknown>;
          quote_text: string;
        };
        createdAnnotationQuotes.push(body.quote_text);
        createdAnnotationPositions.push(body.position);
        const item = {
          id: "20000000-0000-4000-8000-000000000001",
          kind: "annotation_thread",
          audience: body.audience,
          target_document_id: paperDocument.document_id,
          created_at: "2026-08-13T12:00:00Z",
          updated_at: "2026-08-13T12:00:00Z",
          created_by: { id: actor.id, display_name: actor.display_name },
          capabilities: { delete: true, edit: true },
          annotation_thread: {
            capabilities: {
              delete: true,
              recolor: true,
              reopen: false,
              reply: true,
              resolve:
                body.audience.kind === "project" &&
                Boolean(body.initial_comment),
            },
            color: body.color,
            comment_count: body.initial_comment ? 1 : 0,
            last_activity_at: "2026-08-13T12:00:00Z",
            mode: body.initial_comment
              ? body.audience.kind === "project"
                ? "discussion"
                : "note"
              : "highlight",
            comments: body.initial_comment
              ? [
                  {
                    id: "30000000-0000-4000-8000-000000000001",
                    thread_id: "20000000-0000-4000-8000-000000000001",
                    content: body.initial_comment,
                    role: "user",
                    created_at: "2026-08-13T12:00:00Z",
                    updated_at: "2026-08-13T12:00:00Z",
                    created_by: {
                      id: actor.id,
                      display_name: actor.display_name,
                    },
                    can_edit: true,
                    can_delete: true,
                  },
                ]
              : [],
            position: body.position,
            quote_text: body.quote_text,
            role: "note",
            status: "open",
            resolved_at: null,
            resolved_by: null,
          },
        };
        annotations.push(item);
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(item),
        });
        return;
      }
      const url = new URL(route.request().url());
      const status = url.searchParams.get("status") ?? "open";
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: annotations
            .map((item) => item as ReturnType<typeof annotationFixture>)
            .filter((item) => item.annotation_thread.status === status)
            .map((item) => annotationSummary(item)),
          next_cursor: null,
        }),
      });
    },
  );
  await page.route(`${apiPattern}/annotation-threads/*`, async (route) => {
    if (new URL(route.request().url()).pathname.endsWith("/comments")) {
      await route.fallback();
      return;
    }
    const id = route.request().url().split("/").at(-1);
    const item = annotations.find((annotation) => annotation.id === id) as
      ReturnType<typeof annotationFixture> | undefined;
    if (!item) {
      await route.fulfill({ status: 404 });
      return;
    }
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON() as {
        color?: string;
        status?: "open" | "resolved";
      };
      if (body.color) item.annotation_thread.color = body.color;
      if (body.status) {
        item.annotation_thread.status = body.status;
        item.annotation_thread.capabilities.resolve = body.status === "open";
        item.annotation_thread.capabilities.reopen = body.status === "resolved";
        item.annotation_thread.capabilities.reply = body.status === "open";
        item.annotation_thread.resolved_at =
          body.status === "resolved" ? "2026-08-13T12:05:00Z" : null;
        item.annotation_thread.resolved_by =
          body.status === "resolved"
            ? { id: actor.id, display_name: actor.display_name }
            : null;
      }
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(item),
    });
  });
  await page.route(
    `${apiPattern}/annotation-threads/*/comments`,
    async (route) => {
      const segments = new URL(route.request().url()).pathname.split("/");
      const threadId = segments.at(-2);
      if (!threadId) {
        await route.fulfill({ status: 404 });
        return;
      }
      const item = annotations.find(
        (annotation) => annotation.id === threadId,
      ) as ReturnType<typeof annotationFixture> | undefined;
      if (!item) {
        await route.fulfill({ status: 404 });
        return;
      }
      const content = (route.request().postDataJSON() as { content: string })
        .content;
      const comment = {
        id: `30000000-0000-4000-8000-${String(item.annotation_thread.comments.length + 2).padStart(12, "0")}`,
        thread_id: threadId,
        content,
        role: "user",
        created_at: "2026-08-13T12:06:00Z",
        updated_at: "2026-08-13T12:06:00Z",
        created_by: { id: actor.id, display_name: actor.display_name },
        can_edit: true,
        can_delete: true,
      };
      item.annotation_thread.comments.push(comment);
      item.annotation_thread.comment_count += 1;
      item.annotation_thread.last_activity_at = comment.created_at;
      item.annotation_thread.mode =
        item.audience.kind === "project" ? "discussion" : "note";
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(comment),
      });
    },
  );
  await page.route("**/reader-test.pdf", (route) =>
    route.fulfill({ contentType: "application/pdf", path: pdfPath }),
  );
}

async function mockReaderReflow(
  page: Page,
  options: { delayMs?: number } = {},
) {
  let preferences = {
    auto_translate_selection: true,
    custom_instructions: null as string | null,
    full_translation_display: "bilingual",
    show_translation_marker: true,
    source_language: "auto",
    target_language: "zh-CN",
    translate_references: false,
  };

  await page.route(
    `${apiPattern}/me/translation-preferences`,
    async (route) => {
      if (route.request().method() === "PUT") {
        preferences = {
          ...preferences,
          ...(route.request().postDataJSON() as Partial<typeof preferences>),
        };
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(preferences),
      });
    },
  );
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/reflow`,
    async (route) => {
      if (options.delayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.delayMs));
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          assets: [],
          blocks: reflowBlocks,
          document_id: paperDocument.document_id,
          error_code: null,
          job_id: "70000000-0000-4000-8000-000000000001",
          parser_revision: "mineru-content-list-v1",
          pipeline_revision: "mineru-continuous-ast-v1",
          status: "completed",
          updated_at: "2026-08-14T00:00:00Z",
          warnings: [],
        }),
      });
    },
  );
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/reflow/blocks/*/translations`,
    async (route) => {
      const blockId = new URL(route.request().url()).pathname.split("/").at(-2);
      const translations: Record<string, string> = {
        "reflow-method": "## 1 方法",
        "reflow-paragraph": "重建结果让每一项主张都可追溯到 PDF 中可见的证据。",
        "reflow-table":
          "| 证据来源 | 覆盖率 | 置信度 | 审核状态 |\n| --- | ---: | ---: | --- |\n| PDF 区域 | 100% | 0.98 | 已验证 |",
        "reflow-title": "# 基于证据的学术阅读",
      };
      const text = translations[blockId ?? ""] ?? "译文";
      await route.fulfill({
        contentType: "text/event-stream",
        body: [
          `event: start\ndata: ${JSON.stringify({ cache_hit: true, target_language: "zh-CN" })}\n\n`,
          `event: delta\ndata: ${JSON.stringify({ text })}\n\n`,
          `event: complete\ndata: ${JSON.stringify({ cache_hit: true })}\n\n`,
        ].join(""),
      });
    },
  );
}

async function mockReaderConversationCreation(page: Page) {
  let conversationId: string | undefined;
  const answer = "The paper presents a persistent agent runtime.";
  let persistedTurn: Record<string, unknown> | undefined;
  const detail = (id: string) => ({
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
    id,
    paper_context: {
      kind: "selection",
      document_ids: [paperDocument.document_id],
      project_ids: [],
    },
    pinned_at: null,
    read_only: false,
    read_only_reason: null,
    scope_access: "active",
    scope_id: paperDocument.document_id,
    scope_label: paperDocument.title,
    scope_type: "paper",
    title: "New conversation",
    tool_permissions: [],
    updated_at: "2026-08-14T00:00:00Z",
  });

  await page.unroute(`${apiPattern}/conversations**`);
  await page.route(`${apiPattern}/conversations**`, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const startMatch = pathname.match(/\/conversations\/([^/]+)\/start$/);
    if (startMatch && request.method() === "POST") {
      conversationId = startMatch[1]!;
      const body = request.postDataJSON() as {
        conversation: {
          paper_context: ReturnType<typeof detail>["paper_context"];
        };
        turn: {
          response_id: string;
          turn_id: string;
          user_query: string;
        };
      };
      const turnRequest = body.turn;
      const turn = {
        branch: { count: 1, index: 1 },
        contexts: [],
        depth: 1,
        id: turnRequest.turn_id,
        locale: "en",
        reasoning_level: "standard",
        responses: [
          {
            artifacts: null,
            content: answer,
            id: turnRequest.response_id,
            references: null,
            status: "completed",
            trace: null,
            variant_index: 0,
          },
        ],
        paper_context: body.conversation.paper_context,
        parent_turn_id: null,
        selected_response_id: turnRequest.response_id,
        suggestions: null,
        time_zone: "Asia/Shanghai",
        user_query: turnRequest.user_query,
      };
      persistedTurn = turn;
      const events = [
        {
          type: "start",
          conversation_id: conversationId,
          generation_kind: "initial",
          response_id: turnRequest.response_id,
          turn_id: turnRequest.turn_id,
          variant_index: 0,
        },
        {
          type: "assistant_item_start",
          item_id: "assistant-item-1",
          response_id: turnRequest.response_id,
          sequence: 1,
        },
        {
          type: "assistant_item_delta",
          delta: answer,
          item_id: "assistant-item-1",
          response_id: turnRequest.response_id,
        },
        { type: "response_ready", turn },
        {
          type: "complete",
          response_id: turnRequest.response_id,
          turn_id: turnRequest.turn_id,
        },
      ];
      await route.fulfill({
        contentType: "text/event-stream",
        body: events
          .map((event) => `data: ${JSON.stringify(event)}\n\n`)
          .join(""),
      });
      return;
    }
    if (
      conversationId &&
      pathname.endsWith(`/conversations/${conversationId}/turns`)
    ) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: persistedTurn ? [persistedTurn] : [],
          next_cursor: null,
          path_revision: persistedTurn ? 1 : 0,
        }),
      });
      return;
    }
    if (
      conversationId &&
      pathname.endsWith(`/conversations/${conversationId}`)
    ) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(detail(conversationId)),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    });
  });

  return { answer, getConversationId: () => conversationId };
}

async function selectPdfPassage(page: Page, pageNumber: number) {
  const textLayer = page.locator(
    `[data-pdf-page-number="${pageNumber}"] .pdf-text-layer`,
  );
  await expect(
    textLayer.locator("span").filter({ hasText: "The NLP landscape" }),
  ).toBeAttached({ timeout: 10_000 });
  await expect(async () => {
    await textLayer.evaluate((layer) => {
      const spans = [...layer.querySelectorAll("span")].filter((span) =>
        span.textContent?.trim(),
      );
      const firstSpan = spans.find((span) =>
        span.textContent?.includes("The NLP landscape"),
      );
      const firstSpanIndex = firstSpan ? spans.indexOf(firstSpan) : -1;
      const lastSpan = spans[firstSpanIndex + 5];
      if (!firstSpan?.firstChild || !lastSpan?.firstChild) return;
      const range = document.createRange();
      range.setStart(firstSpan.firstChild, 0);
      range.setEnd(lastSpan.firstChild, lastSpan.textContent?.length ?? 0);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      layer.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    });
    await expect(
      page.getByRole("button", { name: "Highlight selection" }),
    ).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 8_000 });
}

async function waitForPdfTextLayer(page: Page, pageNumber: number) {
  const textLayer = page.locator(
    `[data-pdf-page-number="${pageNumber}"] .pdf-text-layer`,
  );
  await expect(textLayer).toHaveAttribute("data-pdf-text-ready", "true", {
    timeout: 10_000,
  });
  await expect(
    textLayer.locator("span").filter({ hasText: /\S/ }).first(),
  ).toBeAttached();
  await expect(textLayer.locator(".endOfContent")).toBeAttached();
  return textLayer;
}

async function beginPdfSelectionGesture(page: Page, startPageNumber: number) {
  const startLayer = await waitForPdfTextLayer(page, startPageNumber);
  await startLayer.dispatchEvent("pointerdown");
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
}

async function finishPdfSelectionAcrossPages(
  page: Page,
  startPageNumber: number,
  endPageNumber: number,
) {
  const startLayer = await waitForPdfTextLayer(page, startPageNumber);
  const endLayer = await waitForPdfTextLayer(page, endPageNumber);

  const selectedText = await startLayer.evaluate((layer, endPage) => {
    const endLayer = document.querySelector<HTMLElement>(
      `[data-pdf-page-number="${endPage}"] .pdf-text-layer`,
    );
    const startSpans = [...layer.querySelectorAll("span")].filter((span) =>
      span.textContent?.trim(),
    );
    const endSpans = [...(endLayer?.querySelectorAll("span") ?? [])].filter(
      (span) => span.textContent?.trim(),
    );
    const selectableTextNode = (span: HTMLSpanElement) => {
      if (
        (span.textContent?.trim().length ?? 0) < 8 ||
        span.getClientRects().length === 0
      ) {
        return undefined;
      }
      return [...span.childNodes].find(
        (node): node is Text =>
          node instanceof Text && Boolean(node.data.trim()),
      );
    };
    const start = [...startSpans]
      .reverse()
      .map(selectableTextNode)
      .find((node): node is Text => Boolean(node));
    const end = endSpans
      .map(selectableTextNode)
      .find((node): node is Text => Boolean(node));
    if (!start || !end || !endLayer) throw new Error("PDF text was not ready");
    const range = document.createRange();
    range.setStart(start, Math.max(0, (start.textContent?.length ?? 0) - 8));
    range.setEnd(end, Math.min(8, end.textContent?.length ?? 0));
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    return (selection?.toString() ?? "").trim();
  }, endPageNumber);
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
  await endLayer.dispatchEvent("pointerup");
  return selectedText;
}

async function selectPdfAcrossPages(
  page: Page,
  startPageNumber: number,
  endPageNumber: number,
) {
  await beginPdfSelectionGesture(page, startPageNumber);
  return finishPdfSelectionAcrossPages(page, startPageNumber, endPageNumber);
}

async function pdfScrollTop(page: Page, pageNumber: number) {
  return page
    .locator(`[data-pdf-page-number="${pageNumber}"]`)
    .evaluate((surface) => {
      let ancestor = surface.parentElement;
      while (ancestor) {
        const overflowY = getComputedStyle(ancestor).overflowY;
        if (overflowY === "auto" || overflowY === "scroll") {
          return ancestor.scrollTop;
        }
        ancestor = ancestor.parentElement;
      }
      throw new Error("PDF scroll container was not found");
    });
}

test.beforeEach(async ({ page }) => {
  createdAnnotationQuotes.length = 0;
  createdAnnotationPositions.length = 0;
  await mockReader(page);
});

test("opens a Library paper in the desktop Reader and restores route state", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);

  await expect(page.getByRole("toolbar", { name: "Page" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("2");
  await expect(
    page.getByRole("button", { name: "Ask about selection" }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ask" })).toHaveCount(0);
  await expect(
    page.locator('[data-pdf-page-number="2"] > canvas'),
  ).toBeVisible();
  await expect(page.locator('[data-pdf-page-number="3"]')).toBeAttached();

  await page.locator('[data-pdf-page-number="3"]').scrollIntoViewIfNeeded();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("3");
  await expect(page).toHaveURL(/page=3/);

  await page.getByRole("button", { name: "Previous page" }).click();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("2");

  await expect(
    page.getByRole("button", { name: "Show document outline" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("complementary", { name: "Page thumbnails" }),
  ).toBeVisible();

  const pageDoesNotOwnViewportScroll = await page.evaluate(() => ({
    body: document.body.scrollHeight <= window.innerHeight,
    root:
      document.documentElement.scrollHeight <=
      document.documentElement.clientHeight,
  }));
  expect(pageDoesNotOwnViewportScroll).toEqual({ body: true, root: true });

  const selectableTextLayer = page.locator(
    '[data-pdf-page-number="2"] .pdf-text-layer',
  );
  await expect(
    selectableTextLayer.locator("span").filter({
      hasText: "The NLP landscape",
    }),
  ).toBeAttached();
  await selectPdfPassage(page, 2);
  const askAboutSelection = page.getByRole("button", {
    name: "Ask about selection",
  });
  await expect(askAboutSelection).toBeVisible();
  await expect(page.locator("[data-active-selection-overlay]")).toBeVisible();
  await expect(
    page.locator("[data-active-selection-overlay] canvas"),
  ).toHaveCount(1);
  const selectionColors = await page.evaluate(() => {
    const overlay = document.querySelector(
      "[data-active-selection-overlay] .pdf-selection-overlay",
    );
    const canvas = overlay instanceof HTMLCanvasElement ? overlay : undefined;
    const pixels = canvas
      ?.getContext("2d")
      ?.getImageData(0, 0, canvas.width, canvas.height).data;
    let maximumAlpha = 0;
    if (pixels) {
      for (let index = 3; index < pixels.length; index += 4) {
        maximumAlpha = Math.max(maximumAlpha, pixels[index] ?? 0);
      }
    }
    return {
      maximumAlpha,
      overlay: overlay ? getComputedStyle(overlay).color : "",
      overlayOpacity: overlay ? getComputedStyle(overlay).opacity : "",
    };
  });
  const alphaChannel = (color: string) =>
    Number(color.match(/rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)\)/)?.[1] ?? 1);
  expect(alphaChannel(selectionColors.overlay)).toBeGreaterThanOrEqual(0.25);
  expect(alphaChannel(selectionColors.overlay)).toBeLessThanOrEqual(0.4);
  expect(selectionColors.maximumAlpha).toBeGreaterThanOrEqual(64);
  expect(selectionColors.maximumAlpha).toBeLessThanOrEqual(102);
  expect(selectionColors.overlayOpacity).toBe("1");
  await expect
    .poll(() => page.evaluate(() => window.getSelection()?.toString() ?? ""))
    .toBe("");
  await askAboutSelection.click();
  await expect(page).toHaveURL(/panel=ask/);
  await expect(
    page.getByText("What would you like to understand?"),
  ).toBeVisible();
  await expect(
    page.getByText(/paper’s claims, methods, or conclusions/),
  ).toBeVisible();
  await expect(page.getByText("Selection from page 2")).toBeVisible();
  const readerComposer = page
    .getByRole("textbox", { name: "Ask a follow-up" })
    .locator("xpath=ancestor::form");
  await expect(readerComposer).toBeVisible();
  expect(
    await readerComposer.evaluate(
      (element) => getComputedStyle(element).borderTopColor,
    ),
  ).not.toBe("rgba(0, 0, 0, 0)");
  await expect(askAboutSelection).toHaveCount(0);
  await expect(page.locator("[data-active-selection-overlay]")).toHaveCount(0);

  await page.getByRole("button", { name: "Close context panel" }).click();
  await page.getByRole("button", { name: "Open context panel" }).click();
  await expect(page).toHaveURL(/panel=ask/);
  await expect(
    page.getByRole("searchbox", {
      name: "Search this paper's conversations",
    }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("searchbox", {
      name: "Search this paper's conversations",
    }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Annotations" }).click();
  await expect(page.getByText("No annotations yet")).toBeVisible();

  await page.getByRole("button", { name: "Details" }).click();
  await expect(page.getByText("Authors", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Close context panel" }).click();
  await page.getByRole("button", { name: "Open context panel" }).click();
  await expect(page.getByText("Authors", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Search PDF" }).click();
  const search = page.getByRole("textbox", { name: "Search PDF" });
  await search.fill("reasoning");
  await expect(page.getByText(/^1 \/ \d+$/)).toBeVisible();
  const currentSearchMatch = page.locator(
    '.pdf-search-match[data-search-match-current="true"]',
  );
  await expect(currentSearchMatch.first()).toBeVisible();
  await expect(currentSearchMatch.first()).toHaveText(/reasoning/i);
  expect(
    await currentSearchMatch.first().evaluate((element) => ({
      hit: element.textContent?.length ?? 0,
      textItem: element.parentElement?.textContent?.length ?? 0,
    })),
  ).toEqual(expect.objectContaining({ hit: "reasoning".length }));
  expect(
    await currentSearchMatch
      .first()
      .evaluate(
        (element) =>
          (element.parentElement?.textContent?.length ?? 0) >
          (element.textContent?.length ?? 0),
      ),
  ).toBe(true);
  const initialMatchId = await currentSearchMatch
    .first()
    .getAttribute("data-search-match-id");
  const searchColors = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    const current = document.querySelector<HTMLElement>(
      '.pdf-search-match[data-search-match-current="true"]',
    );
    const other = document.querySelector<HTMLElement>(
      '.pdf-search-match:not([data-search-match-current="true"])',
    );
    return {
      current: current ? getComputedStyle(current).backgroundColor : "",
      currentToken: root
        .getPropertyValue("--color-document-search-current")
        .trim(),
      match: other ? getComputedStyle(other).backgroundColor : "",
      matchToken: root.getPropertyValue("--color-document-search-match").trim(),
    };
  });
  expect(searchColors.current).not.toBe(searchColors.match);
  expect(searchColors.currentToken).not.toBe(searchColors.matchToken);
  await page.getByRole("button", { name: "Next match" }).click();
  await expect
    .poll(() => currentSearchMatch.first().getAttribute("data-search-match-id"))
    .not.toBe(initialMatchId);
  await page.getByRole("button", { name: "Close PDF search" }).click();
  await expect(search).toBeHidden();
  await expect(page.locator(".pdf-search-match")).toHaveCount(0);

  // Development streams async root metadata independently from the Reader.
  await expect(page).toHaveTitle("Scholens");
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("keeps the desktop selection translation anchored while SSE content grows", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockReaderReflow(page);
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  await expect(
    page.locator('[data-pdf-page-number="2"] > canvas'),
  ).toBeVisible();

  await selectPdfPassage(page, 2);
  const floating = page.locator("[data-reader-selection-floating]");
  const preview = page.locator("[data-reader-selection-translation-preview]");
  const previewText = page.locator("[data-reader-selection-translation-text]");
  await expect(preview).toBeVisible({ timeout: 8_000 });
  await expect(previewText).toContainText("译文：");

  const initial = await floating.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return {
      placement: element.getAttribute("data-reader-selection-placement"),
      top: rect.top,
    };
  });
  const pdfScrollBefore = await pdfScrollTop(page, 2);
  const documentScrollBefore = await page.evaluate(() => ({
    body: document.body.scrollTop,
    root: document.documentElement.scrollTop,
  }));

  await expect(previewText).toContainText("内部滚动");
  const after = await floating.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return {
      placement: element.getAttribute("data-reader-selection-placement"),
      top: rect.top,
    };
  });
  expect(after.placement).toBe(initial.placement);
  expect(Math.abs(after.top - initial.top)).toBeLessThanOrEqual(2);
  expect(await pdfScrollTop(page, 2)).toBe(pdfScrollBefore);
  expect(
    await page.evaluate(() => ({
      body: document.body.scrollTop,
      root: document.documentElement.scrollTop,
    })),
  ).toEqual(documentScrollBefore);

  const previewMetrics = await preview.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return {
      bodyOverflow: getComputedStyle(
        element.querySelector("[data-reader-selection-translation-text]")!,
      ).overflowY,
      pageOverflow:
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
      width: rect.width,
    };
  });
  expect(previewMetrics.width).toBeGreaterThanOrEqual(360);
  expect(previewMetrics.width).toBeLessThanOrEqual(480);
  expect(previewMetrics.bodyOverflow).toBe("auto");
  expect(previewMetrics.pageOverflow).toBe(false);
});

test("uses the fluid preview width on an ultra-wide Reader viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 2560, height: 1440 });
  await mockReaderReflow(page);
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  await expect(
    page.locator('[data-pdf-page-number="2"] > canvas'),
  ).toBeVisible();
  await selectPdfPassage(page, 2);

  const preview = page.locator("[data-reader-selection-translation-preview]");
  await expect(preview).toBeVisible({ timeout: 8_000 });
  const metrics = await preview.evaluate((element) => ({
    pageOverflow:
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth,
    width: element.getBoundingClientRect().width,
  }));
  expect(metrics.width).toBeGreaterThanOrEqual(360);
  expect(metrics.width).toBeLessThanOrEqual(480);
  expect(metrics.pageOverflow).toBe(false);
});

test("creates a persistent document highlight with the full color palette", async ({
  page,
}) => {
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  await expect(
    page.locator('[data-pdf-page-number="2"] > canvas'),
  ).toBeVisible();
  await page.locator('[data-pdf-page-number="3"]').scrollIntoViewIfNeeded();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("3");
  await page.getByRole("button", { name: "Previous page" }).click();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("2");
  await selectPdfPassage(page, 2);

  await page.getByRole("button", { name: "Highlight selection" }).click();
  const highlightPalette = page.getByRole("group", {
    name: "Highlight selection",
  });
  const swatches = highlightPalette.getByRole("button");
  await expect(swatches).toHaveCount(8);
  expect(
    await swatches.evaluateAll(
      (items) =>
        new Set(
          items.map(
            (item) =>
              getComputedStyle(
                item.querySelector<HTMLElement>(
                  "[data-reader-highlight-swatch]",
                )!,
              ).backgroundColor,
          ),
        ).size,
    ),
  ).toBe(8);

  await highlightPalette
    .getByRole("button", { name: "Yellow highlight" })
    .click();
  const persistedHighlight = page.locator(
    '[data-reader-annotation-highlight="20000000-0000-4000-8000-000000000001"]',
  );
  await expect(persistedHighlight.first()).toBeVisible();
  const persistedAppearance = await persistedHighlight
    .first()
    .evaluate((element) => {
      const style = getComputedStyle(element);
      const root = getComputedStyle(document.documentElement);
      return {
        background: style.backgroundColor,
        boxShadow: style.boxShadow,
        token: root
          .getPropertyValue("--color-document-highlight-yellow")
          .trim(),
      };
    });
  expect(persistedAppearance.token).toBe("#ffd400");
  expect(persistedAppearance.background).not.toBe("rgba(0, 0, 0, 0)");
  expect(persistedAppearance.background).not.toBe("rgb(255, 255, 255)");
  expect(persistedAppearance.boxShadow).toBe("none");
  await expect(persistedHighlight.first()).toHaveAttribute(
    "data-reader-annotation-mode",
    "highlight",
  );
  expect(
    await persistedHighlight
      .first()
      .evaluate((element) => Number(getComputedStyle(element).opacity)),
  ).toBeLessThanOrEqual(0.3);
  expect(
    await persistedHighlight.evaluateAll((items) =>
      items.every((item) => getComputedStyle(item).boxShadow === "none"),
    ),
  ).toBe(true);
  await page.reload();
  await expect(persistedHighlight.first()).toBeVisible();
  await expect(persistedHighlight.first()).toHaveCSS(
    "background-color",
    persistedAppearance.background,
  );
});

test("preserves Reader swatch colors and one focus owner in forced colors", async ({
  page,
}) => {
  await page.emulateMedia({ forcedColors: "active" });
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  await expect(
    page.locator('[data-pdf-page-number="2"] > canvas'),
  ).toBeVisible();
  await selectPdfPassage(page, 2);
  await page.getByRole("button", { name: "Add annotation" }).click();

  const palette = page.locator("[data-reader-highlight-palette]");
  const swatches = palette.getByRole("button");
  await expect(swatches).toHaveCount(8);
  expect(
    await palette
      .locator("[data-reader-highlight-swatch]")
      .evaluateAll(
        (items) =>
          new Set(items.map((item) => getComputedStyle(item).backgroundColor))
            .size,
      ),
  ).toBe(8);

  const selected = palette.getByRole("button", { name: "Yellow highlight" });
  await expect(selected).toHaveAttribute("aria-pressed", "true");
  await expect(
    selected.locator("[data-reader-highlight-swatch]"),
  ).toHaveAttribute("data-selected", "true");
  await focusThroughTab(selected);
  await expect
    .poll(() =>
      selected.evaluate((element) => ({
        outline: getComputedStyle(element).outlineWidth,
        swatchOutline: getComputedStyle(
          element.querySelector<HTMLElement>("[data-reader-highlight-swatch]")!,
        ).outlineStyle,
      })),
    )
    .toEqual({ outline: "2px", swatchOutline: "none" });
});
test("preserves an exact partial-span PDF selection", async ({ page }) => {
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("2");
  await expect(
    page.locator('[data-pdf-page-number="2"] > canvas'),
  ).toBeVisible();
  const textLayer = await waitForPdfTextLayer(page, 2);
  await expect(
    textLayer.locator("span").filter({ hasText: "The NLP landscape" }),
  ).toBeAttached();

  const highlightButton = page.getByRole("button", {
    name: "Highlight selection",
  });
  const yellowHighlight = page.getByRole("button", {
    name: "Yellow highlight",
  });
  await expect(async () => {
    await textLayer.evaluate((layer) => {
      const spans = [...layer.querySelectorAll("span")].filter((span) =>
        span.textContent?.trim(),
      );
      const firstSpan = spans.find((span) =>
        span.textContent?.includes("The NLP landscape"),
      );
      if (!firstSpan?.firstChild) return;
      const text = firstSpan.textContent ?? "";
      const start = text.indexOf("NLP");
      if (start < 0) return;
      const range = document.createRange();
      range.setStart(firstSpan.firstChild, start);
      range.setEnd(firstSpan.firstChild, start + 3);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      layer.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    });
    await expect(page.locator("[data-active-selection-overlay]")).toBeVisible({
      timeout: 1_500,
    });
    await highlightButton.click({ timeout: 1_500 });
    await expect(yellowHighlight).toBeVisible({ timeout: 1_500 });
  }).toPass({ timeout: 10_000 });

  await yellowHighlight.click();
  await expect.poll(() => createdAnnotationQuotes.at(-1) ?? "").toBe("NLP");
});

test("@selection preserves and persists one cross-page PDF selection", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  await expect(
    page.locator('[data-pdf-page-number="2"] > canvas'),
  ).toBeVisible();
  const pageThree = page.locator('[data-pdf-page-number="3"]');
  await pageThree.scrollIntoViewIfNeeded();
  await expect(pageThree).toBeInViewport();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("3");
  await expect(page).toHaveURL(/page=3/);

  const activeSelectionOverlays = page.locator(
    "[data-active-selection-overlay]",
  );
  let selectedText = "";
  await expect(async () => {
    selectedText = await selectPdfAcrossPages(page, 2, 3);
    await expect(activeSelectionOverlays).toHaveCount(2, { timeout: 1_500 });
  }).toPass({ timeout: 15_000 });
  const selectedPages = await page
    .locator("[data-active-selection-overlay]")
    .evaluateAll((overlays) =>
      overlays.map((overlay) =>
        Number(
          overlay.closest<HTMLElement>("[data-pdf-page-number]")?.dataset
            .pdfPageNumber,
        ),
      ),
    );
  expect(selectedPages).toEqual([2, 3]);
  const highlightButton = pageThree.getByRole("button", {
    name: "Highlight selection",
  });
  const yellowHighlight = pageThree.getByRole("button", {
    name: "Yellow highlight",
  });
  await expect(highlightButton).toBeVisible();
  await expect(async () => {
    await highlightButton.click({ timeout: 1_500 });
    await expect(yellowHighlight).toBeVisible({ timeout: 1_500 });
  }).toPass({ timeout: 10_000 });

  await yellowHighlight.click();
  await expect.poll(() => createdAnnotationQuotes.at(-1)).toBe(selectedText);
  await expect
    .poll(() => {
      const position = createdAnnotationPositions.at(-1) as
        { segments?: Array<{ page_number: number }> } | undefined;
      return position?.segments?.map((segment) => segment.page_number);
    })
    .toEqual([2, 3]);
  const persistedHighlight = page.locator(
    '[data-reader-annotation-highlight="20000000-0000-4000-8000-000000000001"]',
  );
  await expect.poll(() => persistedHighlight.count()).toBeGreaterThanOrEqual(2);
  const persistedPages = await persistedHighlight.evaluateAll((highlights) => [
    ...new Set(
      highlights.map((highlight) =>
        Number(
          highlight.closest<HTMLElement>("[data-pdf-page-number]")?.dataset
            .pdfPageNumber,
        ),
      ),
    ),
  ]);
  expect(persistedPages).toEqual([2, 3]);
});

test("@selection defers visible-page alignment during a cross-page drag", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  const pageTwo = page.locator('[data-pdf-page-number="2"]');
  const pageThree = page.locator('[data-pdf-page-number="3"]');
  await expect(pageTwo.locator(":scope > canvas")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("2");

  await beginPdfSelectionGesture(page, 2);
  await pageThree.scrollIntoViewIfNeeded();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );

  await expect(pageThree).toBeInViewport();
  expect(new URL(page.url()).searchParams.get("page")).toBe("2");
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("2");
  const scrollTopDuringDrag = await pdfScrollTop(page, 3);

  await finishPdfSelectionAcrossPages(page, 2, 3);
  await expect(page.locator("[data-active-selection-overlay]")).toHaveCount(2);
  await expect
    .poll(() =>
      page
        .locator("[data-active-selection-overlay]")
        .evaluateAll((overlays) =>
          overlays.map((overlay) =>
            Number(
              overlay.closest<HTMLElement>("[data-pdf-page-number]")?.dataset
                .pdfPageNumber,
            ),
          ),
        ),
    )
    .toEqual([2, 3]);

  await expect(page).toHaveURL(/page=3/);
  await expect(page.getByRole("textbox", { name: "Page" })).toHaveValue("3");
  await expect(pageThree).toBeInViewport();
  await expect
    .poll(async () =>
      Math.abs((await pdfScrollTop(page, 3)) - scrollTopDuringDrag),
    )
    .toBeLessThanOrEqual(1);
});

test("keeps PDF selection stable while search highlights are present", async ({
  page,
}) => {
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  // Search rewrites the text layer DOM with nested .pdf-search-match spans;
  // the sentinel must be restored and the browser Range must still commit.
  // "NLP landscape" only matches on page 2, so the Reader never navigates
  // away and page 2 keeps rendering while the highlights are applied.
  await page.getByRole("button", { name: "Search PDF" }).click();
  const search = page.getByRole("textbox", { name: "Search PDF" });
  await search.fill("NLP landscape");
  await expect(page.locator(".pdf-search-match").first()).toBeVisible();
  await expect(
    page
      .locator('[data-pdf-page-number="2"] .pdf-text-layer')
      .locator("span")
      .filter({ hasText: "The NLP landscape" }),
  ).toBeAttached();

  await selectPdfPassage(page, 2);
  await expect(page.locator("[data-active-selection-overlay]")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Highlight selection" }),
  ).toBeVisible();
  await expect(page.locator(".pdf-search-match").first()).toBeVisible();
});

test("refreshes visible annotation discussions on the collaboration interval", async ({
  page,
}) => {
  let annotationReads = 0;
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/annotation-threads**`,
    async (route) => {
      if (route.request().method() === "GET") annotationReads += 1;
      await route.fallback();
    },
  );
  await page.goto(
    `/reader/${paperDocument.document_id}?page=2&panel=annotations`,
  );

  await expect.poll(() => annotationReads).toBeGreaterThanOrEqual(1);
  const initialReads = annotationReads;
  await expect
    .poll(() => annotationReads, { timeout: 12_000 })
    .toBeGreaterThan(initialReads);
});

test("switches into a Project Reader and creates a project annotation atomically", async ({
  page,
}) => {
  let createdBody: Record<string, unknown> | undefined;
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/annotation-threads**`,
    async (route) => {
      if (route.request().method() === "POST") {
        createdBody = route.request().postDataJSON() as Record<string, unknown>;
      }
      await route.fallback();
    },
  );
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  await page.getByRole("combobox", { name: "Reader context" }).click();
  await page.getByRole("option", { name: "Agentic Web review" }).click();
  await expect(page).toHaveURL(/project=50000000-0000-4000-8000-000000000001/);

  await selectPdfPassage(page, 2);
  await page.getByRole("button", { name: "Add annotation" }).click();
  await expect(page).toHaveURL(/panel=annotations/);
  await expect(
    page.getByRole("button", { name: "Annotations" }),
  ).toHaveAttribute("data-active", "true");
  await page
    .getByPlaceholder("Add a note to this selection")
    .fill("Compare this claim with the project benchmark.");
  await page.getByRole("button", { name: "Save annotation" }).click();
  await expect
    .poll(() => createdBody)
    .toEqual(
      expect.objectContaining({
        audience: {
          kind: "project",
          project_id: "50000000-0000-4000-8000-000000000001",
        },
        initial_comment: "Compare this claim with the project benchmark.",
      }),
    );
});

test("replies to, resolves, restores, and reopens a Project discussion", async ({
  page,
}) => {
  await page.goto(`/reader/${paperDocument.document_id}?page=2`);
  await page.getByRole("combobox", { name: "Reader context" }).click();
  await page.getByRole("option", { name: "Agentic Web review" }).click();
  await expect(page).toHaveURL(/project=50000000-0000-4000-8000-000000000001/);
  await expect(
    page.locator('[data-pdf-page-number="2"] .pdf-text-layer span').first(),
  ).toBeAttached();
  await selectPdfPassage(page, 2);
  const addAnnotation = page.getByRole("button", { name: "Add annotation" });
  await expect(addAnnotation).toBeVisible();
  await addAnnotation.click();
  await page
    .getByPlaceholder("Add a note to this selection")
    .fill("Compare this claim with the project benchmark.");
  await page.getByRole("button", { name: "Save annotation" }).click();

  const marker = page.getByRole("button", { name: "1 comment" });
  await expect(marker).toBeVisible();
  await marker.click();
  const discussionMark = page.locator(
    '[data-reader-annotation-highlight="20000000-0000-4000-8000-000000000001"]',
  );
  await expect(discussionMark.first()).toHaveAttribute(
    "data-reader-annotation-mode",
    "annotation",
  );
  await expect(discussionMark.first()).toHaveCSS(
    "background-color",
    "rgba(0, 0, 0, 0)",
  );
  expect(
    await discussionMark
      .first()
      .evaluate((element) => getComputedStyle(element).borderBottomWidth),
  ).not.toBe("0px");
  await page
    .getByPlaceholder("Reply to this discussion")
    .fill("The evaluation section now confirms the comparison.");
  await page.getByPlaceholder("Reply to this discussion").press("Enter");
  await expect(page.getByRole("button", { name: "2 comments" })).toBeVisible({
    timeout: 5_000,
  });

  const focusedHighlight = page.locator(
    '[data-reader-annotation-selected="true"]',
  );
  await expect(focusedHighlight.first()).toBeVisible();
  const focusedBox = await focusedHighlight.first().boundingBox();
  expect(focusedBox?.y).toBeGreaterThan(80);
  expect(focusedBox?.y).toBeLessThan(page.viewportSize()!.height - 80);

  await page.getByRole("button", { name: "Resolve" }).click();
  await expect(
    page.locator(
      '[data-reader-annotation-highlight="20000000-0000-4000-8000-000000000001"]',
    ),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "Filter" }).click();
  await page.getByRole("menuitem", { name: "Resolved discussions" }).click();
  const resolvedHighlight = page.locator(
    '[data-reader-annotation-highlight="20000000-0000-4000-8000-000000000001"]',
  );
  await expect(resolvedHighlight.first()).toBeVisible();
  await resolvedHighlight.first().click();
  await page.getByRole("button", { name: "Reopen" }).click();

  await page.getByRole("button", { name: "Filter" }).click();
  await page.getByRole("menuitem", { name: "Current" }).click();
  await resolvedHighlight.first().click();
  await expect(page.getByPlaceholder("Reply to this discussion")).toBeVisible();
});

test("falls back from an inaccessible Project Reader context", async ({
  page,
}) => {
  await page.goto(
    `/reader/${paperDocument.document_id}?project=50000000-0000-4000-8000-000000000099`,
  );

  await expect(page).not.toHaveURL(/project=/);
  await expect(
    page.getByText("Switched to personal reading", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Reader context" }),
  ).toHaveText("Personal");
});

test("keeps Project context while cached membership is revalidated", async ({
  page,
}) => {
  let membershipReads = 0;
  let releaseFreshMembership!: () => void;
  let markFreshMembershipStarted!: () => void;
  const freshMembershipStarted = new Promise<void>((resolve) => {
    markFreshMembershipStarted = resolve;
  });
  const freshMembershipRelease = new Promise<void>((resolve) => {
    releaseFreshMembership = resolve;
  });

  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/projects`,
    async (route) => {
      membershipReads += 1;
      if (membershipReads === 1) {
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            items: [],
            next_cursor: null,
            total_count: 0,
          }),
        });
        return;
      }

      markFreshMembershipStarted();
      await freshMembershipRelease;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: [readerProject],
          next_cursor: null,
          total_count: 1,
        }),
      });
    },
  );
  await page.route(/\/api\/v1\/projects(?:\?.*)?$/, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [readerProject],
        next_cursor: null,
        previous_cursor: null,
        total_count: 1,
      }),
    }),
  );
  await page.route(`${apiPattern}/projects/${readerProject.id}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(readerProject),
    }),
  );
  await page.route(
    `${apiPattern}/projects/${readerProject.id}/papers**`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: [readerProjectPaper],
          next_cursor: null,
          previous_cursor: null,
          total_count: 1,
        }),
      }),
  );
  await page.route(
    `${apiPattern}/projects/${readerProject.id}/outputs**`,
    (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: [],
          next_cursor: null,
          previous_cursor: null,
          total_count: 0,
        }),
      }),
  );

  await page.goto(`/reader/${paperDocument.document_id}`);
  await expect.poll(() => membershipReads).toBe(1);

  await page.getByRole("link", { name: "Projects" }).click();
  await expect(page).toHaveURL(/\/projects(?:\?.*)?$/);
  await page.getByRole("link", { name: readerProject.title }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${readerProject.id}`));
  await page
    .locator(
      `a[href="/reader/${paperDocument.document_id}?project=${readerProject.id}"]`,
    )
    .click();
  await expect(page).toHaveURL(
    new RegExp(
      `/reader/${paperDocument.document_id}\\?project=${readerProject.id}`,
    ),
  );
  await expect.poll(() => membershipReads).toBe(2);
  await freshMembershipStarted;

  await expect(page).toHaveURL(new RegExp(`project=${readerProject.id}`));
  await expect(
    page.getByText("Switched to personal reading", { exact: true }),
  ).toHaveCount(0);

  releaseFreshMembership();
  await expect(
    page.getByRole("combobox", { name: "Reader context" }),
  ).toHaveText(readerProject.title);
});

test("deduplicates exact anchors and reveals resolved Project discussions weakly", async ({
  page,
}) => {
  const sharedPosition = {
    kind: "pdf_text" as const,
    page_number: 2,
    rects: [{ x: 0.15, y: 0.32, width: 0.55, height: 0.035 }],
  };
  const resolvedPosition = {
    ...sharedPosition,
    rects: [{ x: 0.15, y: 0.42, width: 0.45, height: 0.035 }],
  };
  const projectId = "50000000-0000-4000-8000-000000000001";
  const seeded = [
    annotationFixture({
      id: "21000000-0000-4000-8000-000000000001",
      position: sharedPosition,
    }),
    annotationFixture({
      audience: { kind: "project", project_id: projectId },
      id: "21000000-0000-4000-8000-000000000002",
      position: sharedPosition,
    }),
    annotationFixture({
      audience: { kind: "project", project_id: projectId },
      id: "21000000-0000-4000-8000-000000000003",
      position: resolvedPosition,
      status: "resolved",
    }),
  ];
  await page.route(
    `${apiPattern}/papers/${paperDocument.document_id}/annotation-threads**`,
    (route) => {
      const status =
        new URL(route.request().url()).searchParams.get("status") ?? "open";
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: seeded
            .filter((item) => item.annotation_thread.status === status)
            .map(annotationSummary),
          next_cursor: null,
        }),
      });
    },
  );
  await page.route(`${apiPattern}/annotation-threads/*`, (route) => {
    if (new URL(route.request().url()).pathname.endsWith("/comments")) {
      return route.fallback();
    }
    const id = route.request().url().split("/").at(-1);
    const item = seeded.find((candidate) => candidate.id === id);
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(item),
    });
  });
  await page.goto(
    `/reader/${paperDocument.document_id}?page=2&project=${projectId}`,
  );

  const grouped = page.locator('[data-reader-annotation-count="2"]');
  await expect(grouped).toHaveCount(sharedPosition.rects.length);
  await expect(page.locator('[data-reader-annotation-count="1"]')).toHaveCount(
    0,
  );
  await expect(page.getByRole("button", { name: "2 comments" })).toHaveCount(1);
  await page.getByRole("button", { name: "Open context panel" }).click();
  await page.getByRole("button", { name: "Annotations" }).click();
  const previewCard = page.locator(
    '[data-reader-annotation-card="21000000-0000-4000-8000-000000000001"]',
  );
  await previewCard.hover();
  await expect(
    page.locator(
      '[data-reader-annotation-highlight="21000000-0000-4000-8000-000000000001"][data-reader-annotation-previewed="true"]',
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "Filter" }).hover();
  await expect(
    page.locator('[data-reader-annotation-previewed="true"]'),
  ).toHaveCount(0);
  await grouped.first().click();
  await expect(
    page.getByRole("button", { name: "Annotations" }),
  ).toHaveAttribute("data-active", "true");

  const originalOrder = await page
    .locator("[data-reader-annotation-card]")
    .evaluateAll((cards) =>
      cards.map((card) => card.getAttribute("data-reader-annotation-card")),
    );
  await page
    .locator(
      '[data-reader-annotation-card="21000000-0000-4000-8000-000000000002"]',
    )
    .click();
  await expect
    .poll(() =>
      page
        .locator("[data-reader-annotation-card]")
        .evaluateAll((cards) =>
          cards.map((card) => card.getAttribute("data-reader-annotation-card")),
        ),
    )
    .toEqual(originalOrder);
  await page.getByRole("button", { name: "Filter" }).click();
  await page.getByRole("menuitem", { name: "Resolved discussions" }).click();
  const resolved = page.locator(
    '[data-reader-annotation-highlight="21000000-0000-4000-8000-000000000003"]',
  );
  await expect(resolved).toBeVisible();
  expect(
    await resolved.evaluate((element) =>
      Number(getComputedStyle(element).opacity),
    ),
  ).toBeLessThan(0.4);
});

test("filters Project Ask by the current paper and preserves an unsent draft", async ({
  page,
}) => {
  const conversationRequests: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "GET" &&
      request.url().includes("/api/v1/conversations?")
    ) {
      conversationRequests.push(request.url());
    }
  });
  await page.goto(`/reader/${paperDocument.document_id}?panel=ask`);
  const composer = page.getByRole("textbox", { name: "Ask a follow-up" });
  await composer.fill("Keep this unsent project question");
  await page.getByRole("combobox", { name: "Reader context" }).click();
  await page.getByRole("option", { name: "Agentic Web review" }).click();

  await expect(composer).toHaveValue("Keep this unsent project question");
  await expect
    .poll(() =>
      conversationRequests.some((url) => {
        const requestUrl = new URL(url);
        return (
          requestUrl.searchParams.get("scope_type") === "project" &&
          requestUrl.searchParams.get("scope_id") ===
            "50000000-0000-4000-8000-000000000001" &&
          requestUrl.searchParams.get("context_document_id") ===
            paperDocument.document_id
        );
      }),
    )
    .toBe(true);
});

test("activates a newly created Reader conversation before history refreshes", async ({
  page,
}) => {
  const { answer, getConversationId } =
    await mockReaderConversationCreation(page);
  const question = "What is the paper's central contribution?";
  await page.goto(`/reader/${paperDocument.document_id}?panel=ask`);

  await page.getByRole("textbox", { name: "Ask a follow-up" }).fill(question);
  await page.getByRole("button", { name: "Ask Scholens" }).click();

  await expect.poll(getConversationId).not.toBeUndefined();
  const conversationId = getConversationId();
  if (!conversationId) throw new Error("Conversation start was not observed");

  await expect(page).toHaveURL(
    new RegExp(`panel=ask.*conversation=${conversationId}`),
  );
  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await expect(page.getByText(answer, { exact: true })).toBeVisible();
  await expect(
    page.getByText("Started a new private conversation for this context"),
  ).toHaveCount(0);
  await page.waitForTimeout(300);
  await expect(page).toHaveURL(new RegExp(`conversation=${conversationId}`));
});

test("uses an immersive mobile Reader without the Workspace bottom navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/reader/${paperDocument.document_id}`);

  await expect(
    page.getByRole("button", { name: "Return to library" }),
  ).toBeVisible();
  await expect(
    page.locator('[data-pdf-page-number="1"] > canvas'),
  ).toBeVisible();
  await expect(page.locator("aside canvas")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Library" })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Ask about selection" }),
  ).toHaveCount(0);

  const pageDoesNotOwnViewportScroll = await page.evaluate(() => ({
    body: document.body.scrollHeight <= window.innerHeight,
    root:
      document.documentElement.scrollHeight <=
      document.documentElement.clientHeight,
  }));
  expect(pageDoesNotOwnViewportScroll).toEqual({ body: true, root: true });

  await page.getByRole("button", { name: "Search PDF" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Search PDF" })).toBeVisible();
});

test("uses the full translation panel instead of a desktop preview on narrow Reader", async ({
  page,
}) => {
  await mockReaderReflow(page);
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`/reader/${paperDocument.document_id}?page=2`);
    await expect(
      page.locator('[data-pdf-page-number="2"] > canvas'),
    ).toBeVisible();
    await selectPdfPassage(page, 2);
    await expect(
      page.locator("[data-reader-selection-translation-preview]"),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Translate selection" }).click();
    await expect(page).toHaveURL(/panel=translation/);
    await expect(
      page.getByText("Selected text", { exact: true }),
    ).toBeVisible();
  }
});

test("keeps full translation in the toolbar and renders traceable bilingual reflow", async ({
  page,
}) => {
  await mockReaderReflow(page);
  await page.goto(`/reader/${paperDocument.document_id}?view=reflow`);

  await expect(
    page.getByRole("heading", { name: "Evidence-driven academic reading" }),
  ).toBeVisible();
  await expect(page.getByText("<sup>", { exact: false })).toHaveCount(0);
  await expect(page.locator('[data-reflow-kind="authors"] .katex')).toHaveCount(
    2,
  );
  await expect(
    page
      .getByRole("toolbar", { name: "Page" })
      .getByText("Full translation", { exact: true }),
  ).toHaveCount(1);
  await expect(page.getByText("Full translation", { exact: true })).toHaveCount(
    1,
  );

  await page.getByRole("button", { name: "Show document outline" }).click();
  const outline = page.getByRole("navigation", { name: "Document outline" });
  await expect(outline).toBeVisible();
  await outline.getByRole("button", { name: "1 Method" }).click();
  await page.getByRole("button", { name: "Hide document outline" }).click();
  await expect(outline).toHaveCount(0);

  await page
    .getByRole("button", { name: "Full translation: Not enabled" })
    .click();
  const settings = page.getByRole("dialog", { name: "Full translation" });
  await expect(settings).toBeVisible();
  await settings
    .getByRole("switch", { name: "Enable full translation" })
    .click();
  await expect(page).toHaveURL(/translate=full/);
  await expect(page.getByText("基于证据的学术阅读")).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Evidence-driven academic reading",
      exact: true,
    }),
  ).toBeVisible();

  await settings.getByRole("combobox", { name: "Display" }).click();
  await page.getByRole("option", { name: "Translation only" }).click();
  await expect(page.getByText("基于证据的学术阅读")).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Evidence-driven academic reading",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("columnheader", { name: "Evidence source" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("columnheader", { name: "证据来源" }),
  ).toBeVisible();
});

test("keeps the reflow outline action stable while headings load", async ({
  page,
}) => {
  await mockReaderReflow(page, { delayMs: 1_000 });
  await page.goto(`/reader/${paperDocument.document_id}?view=reflow`);

  const outline = page.getByRole("button", {
    name: "Show document outline",
  });
  await expect(outline).toBeVisible();
  await expect(outline).toBeDisabled();
  await expect(outline).toBeEnabled();
});

test("hides full translation in the PDF view", async ({ page }) => {
  await page.goto(`/reader/${paperDocument.document_id}`);
  const translation = page.getByRole("button", {
    name: "Full translation: Not enabled",
  });
  await expect(translation).toHaveCount(0);
});

test("keeps the context-panel control pinned to the viewport edge", async ({
  page,
}) => {
  await page.goto(`/reader/${paperDocument.document_id}`);
  const open = page.getByRole("button", { name: "Open context panel" });
  const before = await open.boundingBox();
  expect(before).not.toBeNull();
  await open.click();
  const close = page.getByRole("button", { name: "Close context panel" });
  await expect
    .poll(async () => {
      const after = await close.boundingBox();
      return Math.abs((before?.x ?? 0) - (after?.x ?? 0));
    })
    .toBeLessThanOrEqual(2);
});

test("keeps Reader Ask controls inside a panned visual viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockVisualViewport(page, { height: 844, offsetTop: 0 });
  await page.goto(`/reader/${paperDocument.document_id}?panel=ask`);

  const panel = page.locator('[data-placement="visual-full"]');
  const switcher = panel.locator("[data-conversation-switcher]");
  const history = switcher.locator("[data-conversation-switcher-history]");
  const reasoning = switcher.getByRole("button", {
    name: "Reasoning strength: Standard",
  });
  const create = switcher
    .getByRole("button", { name: "New conversation", exact: true })
    .last();
  const close = panel.getByRole("button", { name: "Close context panel" });
  const composer = page
    .getByRole("textbox", { name: "Ask a follow-up" })
    .locator("xpath=ancestor::form");
  await expect(panel).toBeVisible();
  await expect(history).toBeVisible();
  await expect(close).toBeVisible();
  await expect(composer).toBeVisible();
  const controlBoxes = await Promise.all(
    [history, reasoning, create].map((control) => control.boundingBox()),
  );
  expect(controlBoxes.every(Boolean)).toBe(true);
  expect(controlBoxes.map((box) => Math.round(box!.x))).toEqual(
    [...controlBoxes]
      .sort((left, right) => left!.x - right!.x)
      .map((box) => Math.round(box!.x)),
  );
  expect(controlBoxes[0]!.width).toBeGreaterThan(
    Math.max(...controlBoxes.slice(1).map((box) => box!.width)),
  );
  expect(
    controlBoxes
      .slice(0, -1)
      .every((box, index) => box!.x + box!.width <= controlBoxes[index + 1]!.x),
  ).toBe(true);
  const closeBox = await close.boundingBox();
  expect(closeBox).not.toBeNull();
  expect(closeBox!.y + closeBox!.height).toBeLessThanOrEqual(
    controlBoxes[0]!.y,
  );
  expect(
    await switcher.evaluate((element) => element.scrollWidth),
  ).toBeLessThanOrEqual(
    await switcher.evaluate((element) => element.clientWidth),
  );
  await reasoning.click();
  await page.getByRole("menuitemradio", { name: /Deep/ }).click();
  await expect(
    switcher.getByRole("button", { name: "Reasoning strength: Deep" }),
  ).toBeVisible();

  await setVisualViewport(page, { height: 500, offsetTop: 220 });
  await expect
    .poll(() =>
      panel.evaluate((element) => {
        const bounds = element.getBoundingClientRect();
        return {
          bottom: Math.round(bounds.bottom),
          height: Math.round(bounds.height),
          top: Math.round(bounds.top),
        };
      }),
    )
    .toEqual({ bottom: 720, height: 500, top: 220 });
  const [historyBox, composerBox] = await Promise.all([
    history.boundingBox(),
    composer.boundingBox(),
  ]);
  expect(historyBox!.y).toBeGreaterThanOrEqual(220);
  expect(composerBox!.y + composerBox!.height).toBeLessThanOrEqual(720);

  await setVisualViewport(page, { height: 844, offsetTop: 0 });
  await expect
    .poll(() => panel.evaluate((element) => element.clientHeight))
    .toBe(844);
});

for (const width of [320, 390]) {
  test(`uses a bottom sheet without Reader-wide horizontal scrolling at ${width}px`, async ({
    page,
  }) => {
    await mockReaderReflow(page);
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`/reader/${paperDocument.document_id}?view=reflow`);

    await expect(
      page.getByRole("button", { name: "More actions" }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Show document outline" }).click();
    const outline = page.getByRole("dialog", { name: "Document outline" });
    await expect(outline).toBeVisible();
    await expect(
      outline.getByRole("button", { name: "1 Method" }),
    ).toBeVisible();
    await outline.getByRole("button", { name: "1 Method" }).click();
    await expect(outline).toHaveCount(0);

    await page
      .getByRole("button", { name: "Full translation: Not enabled" })
      .click();
    const sheet = page.getByRole("dialog", { name: "Full translation" });
    await expect(sheet).toBeVisible();
    await expect(sheet.getByText("Display", { exact: true })).toBeVisible();
    await sheet.evaluate(async (element) => {
      await Promise.all(
        element.getAnimations().map((animation) => animation.finished),
      );
    });

    const overflow = await page.evaluate(() => ({
      body: document.body.scrollWidth - document.body.clientWidth,
      root:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    }));
    expect(overflow.body).toBeLessThanOrEqual(0);
    expect(overflow.root).toBeLessThanOrEqual(0);
    await expect(page.locator('[data-reflow-kind="table"]')).toHaveCount(1);

    const results = await new AxeBuilder({ page }).exclude("canvas").analyze();
    expect(results.violations).toEqual([]);
  });
}
