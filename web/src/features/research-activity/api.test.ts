import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/generated/schema";
import {
  adaptPaperInsights,
  adaptPersonalInsights,
  adaptProjectActivity,
  adaptProjectInsights,
  chunkPaperSummaryDocumentIds,
  densifyResearchActivityDays,
  exportReadingActivity,
  historyIsPartial,
  MAX_PAPER_ACTIVITY_CELLS,
  projectPaperPageActivity,
  updateReadingSession,
} from "./api";

afterEach(() => {
  vi.restoreAllMocks();
});

const now = new Date("2026-08-24T12:00:00Z");

function paperInsights(
  range: "30d" | "all",
): components["schemas"]["PaperInsightsResponse"] {
  return {
    activity_history_complete_since: "2026-01-01T00:00:00Z",
    document_id: "40000000-0000-4000-8000-000000000001",
    metric_definition_version: "active-reading-v1",
    page_count: 1,
    pages: [
      {
        active_ms: 0,
        annotation_count: 2,
        page_number: 1,
        vertical_segments_ms: Array.from({ length: 20 }, () => 0),
        visible_ms: 90_000,
        visit_count: 1,
      },
    ],
    range,
    reading_data_since: "2026-01-01T00:00:00Z",
    summary: {
      active_days: 0,
      active_ms: 0,
      coverage_percent: 0,
      session_count: 1,
      substantive_pages: 0,
      visible_ms: 90_000,
    },
    time_zone: "UTC",
    trend: [],
  };
}

describe("research activity history completeness", () => {
  it("does not warn when the complete-history boundary predates a 30-day window", () => {
    expect(
      historyIsPartial({
        activityHistoryCompleteSince: "2026-07-01T00:00:00Z",
        now,
        range: "30d",
        timeZone: "UTC",
      }),
    ).toBe(false);
  });

  it("warns when a 365-day window crosses the complete-history boundary", () => {
    expect(
      historyIsPartial({
        activityHistoryCompleteSince: "2026-07-01T00:00:00Z",
        now,
        range: "365d",
        timeZone: "UTC",
      }),
    ).toBe(true);
  });

  it("treats all-time history as complete when collection and completeness start together", () => {
    expect(
      historyIsPartial({
        activityHistoryCompleteSince: "2026-01-01T00:00:00Z",
        now,
        range: "all",
        timeZone: "UTC",
      }),
    ).toBe(false);
  });

  it("evaluates completeness from the selected calendar day in the response time zone", () => {
    expect(
      historyIsPartial({
        activityHistoryCompleteSince: "2026-08-18T20:00:00Z",
        now: new Date("2026-08-24T16:30:00Z"),
        range: "7d",
        timeZone: "Asia/Shanghai",
      }),
    ).toBe(true);
    expect(
      historyIsPartial({
        activityHistoryCompleteSince: "2026-08-18T15:00:00Z",
        now: new Date("2026-08-24T16:30:00Z"),
        range: "7d",
        timeZone: "Asia/Shanghai",
      }),
    ).toBe(false);
  });

  it("warns for a finite window even without reading evidence", () => {
    expect(
      historyIsPartial({
        activityHistoryCompleteSince: "2026-08-01T00:00:00Z",
        now,
        range: "90d",
        timeZone: "UTC",
      }),
    ).toBe(true);
  });

  it("treats all as the complete collected history", () => {
    expect(
      historyIsPartial({
        activityHistoryCompleteSince: "2026-07-01T00:00:00Z",
        now,
        range: "all",
        timeZone: "UTC",
      }),
    ).toBe(false);
  });
});

describe("research activity trend densification", () => {
  it("fills missing local days without inventing pre-collection history", () => {
    const days = densifyResearchActivityDays({
      days: [
        { activeMs: 60_000, date: "2026-08-02" },
        { activeMs: 180_000, date: "2026-08-04" },
      ],
      now: new Date("2026-08-04T12:00:00Z"),
      range: "30d",
      readingDataSince: "2026-08-02T00:00:00Z",
      timeZone: "UTC",
    });

    expect(days).toEqual([
      { activeMs: 60_000, date: "2026-08-02" },
      { activeMs: 0, date: "2026-08-03" },
      { activeMs: 180_000, date: "2026-08-04" },
    ]);
  });

  it("keeps absent Project team reading null instead of inventing zero", () => {
    const days = densifyResearchActivityDays({
      days: [{ activeMs: 60_000, date: "2026-08-02", teamActiveMs: null }],
      emptyDay: { activeMs: 0, sharedEventCount: 0, teamActiveMs: null },
      now: new Date("2026-08-03T12:00:00Z"),
      range: "30d",
      readingDataSince: "2026-08-02T00:00:00Z",
      timeZone: "UTC",
    });

    expect(days[1]).toMatchObject({
      activeMs: 0,
      date: "2026-08-03",
      teamActiveMs: null,
    });
  });

  it("uses the response time zone and preserves every returned in-range date", () => {
    const days = densifyResearchActivityDays({
      days: [{ activeMs: 60_000, date: "2026-08-18" }],
      now: new Date("2026-08-24T16:30:00Z"),
      range: "7d",
      readingDataSince: "2026-08-01T00:00:00Z",
      timeZone: "Asia/Shanghai",
    });

    expect(days[0]?.date).toBe("2026-08-18");
    expect(days.at(-1)?.date).toBe("2026-08-25");
    expect(days.find((day) => day.date === "2026-08-18")?.activeMs).toBe(
      60_000,
    );
  });

  it("uses UTC for Project-style day windows", () => {
    const days = densifyResearchActivityDays({
      days: [{ activeMs: 60_000, date: "2026-08-18" }],
      now: new Date("2026-08-24T23:30:00Z"),
      range: "7d",
      readingDataSince: "2026-08-01T00:00:00Z",
      timeZone: "UTC",
    });

    expect(days.map((day) => day.date)).toEqual([
      "2026-08-18",
      "2026-08-19",
      "2026-08-20",
      "2026-08-21",
      "2026-08-22",
      "2026-08-23",
      "2026-08-24",
    ]);
  });

  it("densifies calendar dates across a daylight-saving transition", () => {
    const days = densifyResearchActivityDays({
      days: [
        { activeMs: 60_000, date: "2026-03-06" },
        { activeMs: 120_000, date: "2026-03-09" },
      ],
      now: new Date("2026-03-09T16:00:00Z"),
      range: "7d",
      readingDataSince: "2026-01-01T00:00:00Z",
      timeZone: "America/New_York",
    });

    expect(days.map((day) => day.date)).toEqual([
      "2026-03-03",
      "2026-03-04",
      "2026-03-05",
      "2026-03-06",
      "2026-03-07",
      "2026-03-08",
      "2026-03-09",
    ]);
  });

  it("keeps shared Project events that predate the first reading record", () => {
    const days = densifyResearchActivityDays({
      days: [
        {
          activeMs: 0,
          date: "2026-08-20",
          sharedEventCount: 2,
          teamActiveMs: null,
        },
        {
          activeMs: 60_000,
          date: "2026-08-22",
          sharedEventCount: 0,
          teamActiveMs: null,
        },
      ],
      emptyDay: {
        activeMs: 0,
        sharedEventCount: 0,
        teamActiveMs: null,
      },
      now: new Date("2026-08-24T12:00:00Z"),
      range: "7d",
      readingDataSince: "2026-08-22T00:00:00Z",
      timeZone: "UTC",
    });

    expect(days[0]).toMatchObject({
      date: "2026-08-20",
      sharedEventCount: 2,
    });
  });
});

function projectInsights(
  anonymousReadingAvailable: boolean,
): components["schemas"]["ProjectInsightsResponse"] {
  return {
    activity_history_complete_since: "2026-01-01T00:00:00Z",
    metric_definition_version: "active-reading-v1",
    mine: {
      annotation_count: 3,
      papers_with_activity: 2,
      private_conversation_count: 1,
      reading: {
        active_days: 2,
        active_ms: 120_000,
        coverage_percent: 40,
        session_count: 2,
        substantive_pages: 3,
        visible_ms: 150_000,
      },
    },
    papers: [],
    papers_total_count: 0,
    project_id: "50000000-0000-4000-8000-000000000001",
    range: "30d",
    reading_data_since: "2026-01-01T00:00:00Z",
    team: {
      active_collaborators: 4,
      active_ms: anonymousReadingAvailable ? 480_000 : null,
      anonymous_reading_available: anonymousReadingAvailable,
      outputs: 2,
      papers_added: 3,
      papers_with_activity: anonymousReadingAvailable ? 6 : null,
      resolved_discussions: 1,
      shared_annotations: 5,
      discussion_message_count: 7,
      substantive_pages: anonymousReadingAvailable ? 18 : null,
      visible_ms: anonymousReadingAvailable ? 600_000 : null,
    },
    time_zone: "UTC",
    trend: [],
  };
}

describe("project research activity adapter", () => {
  it("keeps only a canonical document destination for feed navigation", () => {
    const events = adaptProjectActivity({
      items: [
        {
          document_id: "40000000-0000-4000-8000-000000000001",
          document_title: "Canonical paper title",
          id: "event-1",
          kind: "annotation_created",
          occurred_at: "2026-08-20T12:00:00Z",
        },
        {
          id: "event-2",
          kind: "output_created",
          occurred_at: "2026-08-20T12:00:00Z",
        },
      ],
      project_id: "50000000-0000-4000-8000-000000000001",
    });

    expect(events[0]?.documentId).toBe("40000000-0000-4000-8000-000000000001");
    expect(events[0]?.documentTitle).toBe("Canonical paper title");
    expect(events[1]?.documentId).toBeUndefined();
  });

  it("emits each team metric once", () => {
    const keys = adaptProjectInsights(projectInsights(true)).team.map(
      (metric) => metric.key,
    );
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys).toEqual(
      expect.arrayContaining([
        "active_ms",
        "visible_ms",
        "papers_with_activity",
        "substantive_pages",
      ]),
    );
    expect(keys).toEqual(
      expect.arrayContaining([
        "papers_added",
        "shared_annotations",
        "discussion_messages",
        "resolved_discussions",
        "outputs",
      ]),
    );
    expect(keys).not.toContain("shared_actions");
    expect(
      adaptProjectInsights(projectInsights(true)).mine.map(
        (metric) => metric.key,
      ),
    ).toEqual(
      expect.arrayContaining([
        "active_ms",
        "visible_ms",
        "active_days",
        "sessions",
        "substantive_pages",
        "coverage_percent",
        "papers_with_activity",
      ]),
    );
  });

  it("does not turn suppressed anonymous reading into zero", () => {
    const keys = adaptProjectInsights(projectInsights(false)).team.map(
      (metric) => metric.key,
    );
    expect(keys).not.toContain("active_ms");
    expect(keys).not.toContain("visible_ms");
    expect(keys).not.toContain("papers_with_activity");
    expect(keys).not.toContain("substantive_pages");
  });

  it("omits unknown personal coverage instead of presenting zero", () => {
    const value = projectInsights(true);
    value.mine.reading.coverage_percent = null;

    expect(
      adaptProjectInsights(value).mine.map((metric) => metric.key),
    ).not.toContain("coverage_percent");
  });

  it("keeps the selected-period paper activity timestamp", () => {
    const value = projectInsights(true);
    value.papers_total_count = 150;
    value.papers = [
      {
        document_id: "40000000-0000-4000-8000-000000000001",
        last_activity_at: "2026-08-20T12:00:00Z",
        my_active_ms: 60_000,
        my_coverage_percent: null,
        discussion_message_count: 2,
        shared_annotation_count: 1,
        title: "Paper",
      },
    ];

    const adapted = adaptProjectInsights(value);
    expect(adapted.papers[0]?.lastActivityAt).toBe("2026-08-20T12:00:00Z");
    expect(adapted.papersTotalCount).toBe(150);
  });
});

describe("personal research activity adapter", () => {
  it("keeps the canonical reading summary dimensions", () => {
    const value: components["schemas"]["ResearchInsightsResponse"] = {
      activity_history_complete_since: "2026-01-01T00:00:00Z",
      annotation_count: 4,
      conversation_count: 3,
      metric_definition_version: "active-reading-v1",
      output_count: 2,
      papers_with_activity: 5,
      projects: [
        {
          active_ms: 60_000,
          project_id: "50000000-0000-4000-8000-000000000001",
          session_count: 3,
          title: "Project",
        },
      ],
      range: "30d",
      reading_data_since: "2026-01-01T00:00:00Z",
      summary: {
        active_days: 6,
        active_ms: 120_000,
        coverage_percent: 50,
        session_count: 7,
        substantive_pages: 8,
        visible_ms: 180_000,
      },
      time_zone: "UTC",
      top_papers: [
        {
          active_ms: 60_000,
          document_id: "40000000-0000-4000-8000-000000000001",
          last_read_at: "2026-08-20T12:00:00Z",
          session_count: 2,
          title: "Paper",
        },
      ],
      trend: [],
    };

    expect(
      adaptPersonalInsights(value).summary.map((metric) => metric.key),
    ).toEqual(
      expect.arrayContaining([
        "active_ms",
        "visible_ms",
        "active_days",
        "sessions",
        "substantive_pages",
      ]),
    );
    expect(adaptPersonalInsights(value).projects[0]).toMatchObject({
      sessionCount: 3,
    });
    expect(adaptPersonalInsights(value).papers[0]).toMatchObject({
      lastReadAt: "2026-08-20T12:00:00Z",
      sessionCount: 2,
    });
  });
});

describe("paper research activity adapter", () => {
  it("keeps visible time and annotation-only evidence in the summary", () => {
    const insights = adaptPaperInsights(
      paperInsights("all"),
      paperInsights("30d"),
    );
    expect(insights.summary).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: "visible_ms", value: 90_000 }),
        expect.objectContaining({ key: "annotations", value: 2 }),
      ]),
    );
  });

  it("does not invent zero coverage when coverage is unknown", () => {
    const allTime = paperInsights("all");
    allTime.summary.coverage_percent = null;

    const insights = adaptPaperInsights(allTime, paperInsights("30d"));

    expect(
      insights.summary.find((metric) => metric.key === "coverage_percent"),
    ).toBeUndefined();
  });

  it("uses the current Reader page count only to complete an old paper map", () => {
    const allTime = paperInsights("all");
    allTime.page_count = null;
    allTime.summary.coverage_percent = null;
    allTime.pages = [
      {
        active_ms: 60_000,
        annotation_count: 0,
        page_number: 10,
        vertical_segments_ms: [60_000, ...Array.from({ length: 19 }, () => 0)],
        visible_ms: 70_000,
        visit_count: 1,
      },
    ];

    const insights = adaptPaperInsights(allTime, paperInsights("30d"), 100);

    expect(insights.pages).toHaveLength(100);
    expect(insights.pages.at(-1)).toMatchObject({
      activeMs: 0,
      pageEndNumber: 100,
      pageNumber: 100,
    });
    expect(
      insights.summary.find((metric) => metric.key === "coverage_percent"),
    ).toBeUndefined();
  });

  it("bounds a 10,000-page map while preserving cumulative evidence", () => {
    const input = paperInsights("all");
    input.page_count = 10_000;
    input.pages = [
      {
        active_ms: 60_000,
        annotation_count: 1,
        page_number: 1,
        vertical_segments_ms: [60_000, ...Array.from({ length: 19 }, () => 0)],
        visible_ms: 70_000,
        visit_count: 1,
      },
      {
        active_ms: 180_000,
        annotation_count: 2,
        page_number: 5_050,
        vertical_segments_ms: [180_000, ...Array.from({ length: 19 }, () => 0)],
        visible_ms: 200_000,
        visit_count: 3,
      },
      {
        active_ms: 90_000,
        annotation_count: 0,
        page_number: 10_000,
        vertical_segments_ms: [90_000, ...Array.from({ length: 19 }, () => 0)],
        visible_ms: 100_000,
        visit_count: 2,
      },
    ];

    const pages = projectPaperPageActivity(input);

    expect(pages).toHaveLength(MAX_PAPER_ACTIVITY_CELLS);
    expect(pages.reduce((sum, page) => sum + page.activeMs, 0)).toBe(330_000);
    expect(pages.reduce((sum, page) => sum + page.visibleMs, 0)).toBe(370_000);
    expect(pages.reduce((sum, page) => sum + page.visitCount, 0)).toBe(6);
    expect(pages.reduce((sum, page) => sum + page.annotationCount, 0)).toBe(3);
    expect(
      pages.reduce(
        (sum, page) =>
          sum +
          page.verticalSegmentsMs.reduce(
            (segmentSum, value) => segmentSum + value,
            0,
          ),
        0,
      ),
    ).toBe(330_000);
    expect(
      pages.find(
        (page) => page.pageNumber <= 5_050 && page.pageEndNumber >= 5_050,
      ),
    ).toMatchObject({ navigationPageNumber: 5_050 });
  });

  it("navigates an inactive aggregate cell to its first annotated page", () => {
    const input = paperInsights("all");
    input.page_count = 1_000;
    input.pages = [
      {
        active_ms: 0,
        annotation_count: 2,
        page_number: 72,
        vertical_segments_ms: Array.from({ length: 20 }, () => 0),
        visible_ms: 0,
        visit_count: 0,
      },
    ];

    expect(
      projectPaperPageActivity(input).find(
        (page) => page.pageNumber <= 72 && page.pageEndNumber >= 72,
      ),
    ).toMatchObject({ navigationPageNumber: 72 });
  });
});

describe("reading session transport", () => {
  it("forwards keepalive to the final fetch Request", async () => {
    const sessionId = "40000000-0000-4000-8000-000000000001";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          active_ms: 5_000,
          document_id: "40000000-0000-4000-8000-000000000002",
          ended_at: null,
          id: sessionId,
          last_seen_at: "2026-08-24T12:00:05Z",
          metric_definition_version: "active-reading-v1",
          page_detail_available: true,
          project_contribution_enabled: true,
          project_id: null,
          revision: 1,
          started_at: "2026-08-24T12:00:00Z",
          time_zone: "UTC",
          view_mode: "pdf",
          visible_ms: 5_000,
        }),
        {
          headers: { "content-type": "application/json" },
          status: 200,
        },
      ),
    );

    await updateReadingSession({
      keepalive: true,
      lastSeenAt: "2026-08-24T12:00:05Z",
      revision: 1,
      sessionId,
      snapshot: {
        active_ms: 5_000,
        hours: [
          {
            active_ms: 5_000,
            bucket_start: "2026-08-24T12:00:00Z",
            visible_ms: 5_000,
          },
        ],
        pages: [],
        visible_ms: 5_000,
      },
    });

    const request = fetchMock.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect((request as Request).keepalive).toBe(true);
    await expect((request as Request).clone().json()).resolves.toMatchObject({
      hours: [
        {
          active_ms: 5_000,
          bucket_start: "2026-08-24T12:00:00Z",
          visible_ms: 5_000,
        },
      ],
    });
  });

  it("collects cursor export pages with one CSV header", async () => {
    const firstPage = new Response(null, {
      headers: {
        "content-type": "text/csv",
        "X-Next-Cursor": "next-page",
      },
    });
    vi.spyOn(firstPage, "blob").mockResolvedValue(
      new Blob(["record_type,payload_json\nsession,{}\n"]),
    );
    const secondPage = new Response(null, {
      headers: { "content-type": "text/csv" },
    });
    vi.spyOn(secondPage, "blob").mockResolvedValue(new Blob(["page,{}\n"]));
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(secondPage);

    const result = await exportReadingActivity();

    expect(await result.text()).toBe(
      "record_type,payload_json\nsession,{}\npage,{}\n",
    );
    const urls = fetchMock.mock.calls.map(
      (call) => new URL((call[0] as Request).url),
    );
    expect(urls[0]?.searchParams.get("include_header")).toBe("true");
    expect(urls[0]?.searchParams.get("limit")).toBe("1000");
    expect(urls[0]?.searchParams.get("cursor")).toBeNull();
    expect(urls[1]?.searchParams.get("include_header")).toBe("false");
    expect(urls[1]?.searchParams.get("cursor")).toBe("next-page");
  });
});

describe("paper summary batching", () => {
  it("keeps every unique document when more than 100 are loaded", () => {
    const ids = Array.from(
      { length: 205 },
      (_, index) =>
        `40000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    );
    const chunks = chunkPaperSummaryDocumentIds([...ids, ids[0] as string]);

    expect(chunks.map((chunk) => chunk.length)).toEqual([100, 100, 5]);
    expect(chunks.flat()).toEqual(ids);
  });
});
