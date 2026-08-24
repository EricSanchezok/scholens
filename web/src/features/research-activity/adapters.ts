import type { components } from "@/lib/api/generated/schema";
import {
  densifyResearchActivityDays,
  historyIsPartial,
} from "./activity-dates";
import type {
  PaperActivitySummary,
  PaperPageActivity,
  PaperResearchInsights,
  PersonalResearchInsights,
  ProjectActivityEvent,
  ProjectResearchInsights,
  ReadingActivityPreferences,
} from "./types";

type PaperInsightsResponse = components["schemas"]["PaperInsightsResponse"];
type ProjectInsightsResponse = components["schemas"]["ProjectInsightsResponse"];
type ProjectActivityResponse = components["schemas"]["ProjectActivityResponse"];
type ResearchInsightsResponse =
  components["schemas"]["ResearchInsightsResponse"];
type ReadingPaperSummariesResponse =
  components["schemas"]["ReadingPaperSummariesResponse"];

function readingMetric(
  key: string,
  value: number,
  unit: "count" | "milliseconds" | "percent" = "count",
) {
  return { key, unit, value } as const;
}

export function adaptPreferences(
  value: components["schemas"]["ReadingActivityPreferencesResponse"],
): ReadingActivityPreferences {
  return {
    contributeAnonymousProjectAggregates:
      value.contribute_anonymous_project_aggregates,
    recordingEnabled: value.recording_enabled,
  };
}

export const MAX_PAPER_ACTIVITY_CELLS = 200;

/**
 * Keeps the reader panel bounded without discarding evidence. Normal papers
 * retain one cell per page; very long documents are projected into contiguous
 * page ranges with cumulative metrics.
 */
export function projectPaperPageActivity(
  value: PaperInsightsResponse,
  readerPageCount?: number,
): PaperPageActivity[] {
  const pageCount = Math.max(
    value.page_count ?? readerPageCount ?? 0,
    ...value.pages.map((page) => page.page_number),
  );
  if (pageCount <= 0) return [];

  const pagesPerCell = Math.max(
    1,
    Math.ceil(pageCount / MAX_PAPER_ACTIVITY_CELLS),
  );
  const cellCount = Math.ceil(pageCount / pagesPerCell);
  const cells = Array.from({ length: cellCount }, (_, index) => {
    const pageNumber = index * pagesPerCell + 1;
    return {
      activeMs: 0,
      annotationCount: 0,
      firstAnnotatedPageNumber: undefined as number | undefined,
      hottestActiveMs: 0,
      navigationPageNumber: pageNumber,
      pageEndNumber: Math.min(pageCount, pageNumber + pagesPerCell - 1),
      pageNumber,
      verticalSegmentsMs: Array.from({ length: 20 }, () => 0),
      visibleMs: 0,
      visitCount: 0,
    };
  });

  for (const page of value.pages) {
    const cell = cells[Math.floor((page.page_number - 1) / pagesPerCell)];
    if (!cell) continue;
    cell.activeMs += page.active_ms;
    cell.visibleMs += page.visible_ms;
    cell.visitCount += page.visit_count;
    cell.annotationCount += page.annotation_count;
    if (
      page.annotation_count > 0 &&
      (cell.firstAnnotatedPageNumber === undefined ||
        page.page_number < cell.firstAnnotatedPageNumber)
    ) {
      cell.firstAnnotatedPageNumber = page.page_number;
    }
    if (
      page.active_ms > cell.hottestActiveMs ||
      (page.active_ms === cell.hottestActiveMs &&
        page.page_number < cell.navigationPageNumber)
    ) {
      cell.hottestActiveMs = page.active_ms;
      cell.navigationPageNumber = page.page_number;
    }
    if (page.vertical_segments_ms.length === 20) {
      page.vertical_segments_ms.forEach((milliseconds, index) => {
        cell.verticalSegmentsMs[index] =
          (cell.verticalSegmentsMs[index] ?? 0) + milliseconds;
      });
    }
  }

  return cells.map((cell) => ({
    activeMs: cell.activeMs,
    annotationCount: cell.annotationCount,
    navigationPageNumber:
      cell.hottestActiveMs > 0
        ? cell.navigationPageNumber
        : (cell.firstAnnotatedPageNumber ?? cell.navigationPageNumber),
    pageEndNumber: cell.pageEndNumber,
    pageNumber: cell.pageNumber,
    verticalSegmentsMs: cell.verticalSegmentsMs,
    visibleMs: cell.visibleMs,
    visitCount: cell.visitCount,
  }));
}

export function adaptPaperInsights(
  allTime: PaperInsightsResponse,
  recent: PaperInsightsResponse,
  readerPageCount?: number,
): PaperResearchInsights {
  return {
    activityHistoryCompleteSince: allTime.activity_history_complete_since,
    daily: densifyResearchActivityDays({
      days: recent.trend.map((day) => ({
        activeMs: day.active_ms,
        date: day.date,
        sessionCount: day.session_count,
        visibleMs: day.visible_ms,
      })),
      emptyDay: { activeMs: 0, sessionCount: 0, visibleMs: 0 },
      range: recent.range,
      readingDataSince: recent.reading_data_since,
      timeZone: recent.time_zone,
    }),
    pages: projectPaperPageActivity(allTime, readerPageCount),
    readingDataSince: allTime.reading_data_since,
    metricDefinitionVersion: allTime.metric_definition_version,
    historyPartial: historyIsPartial({
      activityHistoryCompleteSince: allTime.activity_history_complete_since,
      range: allTime.range,
      timeZone: allTime.time_zone,
    }),
    summary: [
      readingMetric("active_ms", allTime.summary.active_ms, "milliseconds"),
      readingMetric("visible_ms", allTime.summary.visible_ms, "milliseconds"),
      readingMetric("sessions", allTime.summary.session_count),
      readingMetric("active_days", allTime.summary.active_days),
      readingMetric(
        "annotations",
        allTime.pages.reduce((total, page) => total + page.annotation_count, 0),
      ),
      ...(allTime.summary.coverage_percent == null
        ? []
        : [
            readingMetric(
              "coverage_percent",
              allTime.summary.coverage_percent,
              "percent",
            ),
          ]),
    ],
  };
}

export function adaptProjectInsights(
  value: ProjectInsightsResponse,
): ProjectResearchInsights {
  return {
    activityHistoryCompleteSince: value.activity_history_complete_since,
    daily: densifyResearchActivityDays({
      days: value.trend.map((day) => ({
        activeMs: day.my_active_ms,
        date: day.date,
        sharedEventCount: day.shared_activity_count,
        teamActiveMs: day.team_active_ms,
      })),
      emptyDay: {
        activeMs: 0,
        sharedEventCount: 0,
        teamActiveMs: null,
      },
      range: value.range,
      readingDataSince: value.reading_data_since,
      timeZone: value.time_zone,
    }),
    mine: [
      readingMetric("active_ms", value.mine.reading.active_ms, "milliseconds"),
      readingMetric(
        "visible_ms",
        value.mine.reading.visible_ms,
        "milliseconds",
      ),
      readingMetric("active_days", value.mine.reading.active_days),
      readingMetric("sessions", value.mine.reading.session_count),
      ...(value.mine.reading.substantive_pages == null
        ? []
        : [
            readingMetric(
              "substantive_pages",
              value.mine.reading.substantive_pages,
            ),
          ]),
      ...(value.mine.reading.coverage_percent == null
        ? []
        : [
            readingMetric(
              "coverage_percent",
              value.mine.reading.coverage_percent,
              "percent",
            ),
          ]),
      readingMetric("papers_with_activity", value.mine.papers_with_activity),
      readingMetric("annotations", value.mine.annotation_count),
      readingMetric("conversations", value.mine.private_conversation_count),
    ],
    papers: value.papers.map((paper) => ({
      activeMs: paper.my_active_ms,
      coveragePercent: paper.my_coverage_percent ?? null,
      discussionMessageCount: paper.discussion_message_count,
      documentId: paper.document_id,
      lastActivityAt: paper.last_activity_at,
      sharedAnnotationCount: paper.shared_annotation_count,
      title: paper.title,
    })),
    papersTotalCount: value.papers_total_count,
    range: value.range,
    metricDefinitionVersion: value.metric_definition_version,
    readingDataSince: value.reading_data_since,
    team: [
      ...(value.team.anonymous_reading_available && value.team.active_ms != null
        ? [readingMetric("active_ms", value.team.active_ms, "milliseconds")]
        : []),
      ...(value.team.anonymous_reading_available &&
      value.team.visible_ms != null
        ? [readingMetric("visible_ms", value.team.visible_ms, "milliseconds")]
        : []),
      ...(value.team.anonymous_reading_available &&
      value.team.papers_with_activity != null
        ? [
            readingMetric(
              "papers_with_activity",
              value.team.papers_with_activity,
            ),
          ]
        : []),
      ...(value.team.anonymous_reading_available &&
      value.team.substantive_pages != null
        ? [readingMetric("substantive_pages", value.team.substantive_pages)]
        : []),
      readingMetric("active_members", value.team.active_collaborators),
      readingMetric("papers_added", value.team.papers_added),
      readingMetric("shared_annotations", value.team.shared_annotations),
      readingMetric("discussion_messages", value.team.discussion_message_count),
      readingMetric("resolved_discussions", value.team.resolved_discussions),
      readingMetric("outputs", value.team.outputs),
    ],
    teamReadingAvailable: value.team.anonymous_reading_available,
    historyPartial: historyIsPartial({
      activityHistoryCompleteSince: value.activity_history_complete_since,
      range: value.range,
      timeZone: value.time_zone,
    }),
  };
}

function projectActivityKind(kind: string): ProjectActivityEvent["kind"] {
  if (
    kind === "annotation_created" ||
    kind === "discussion_message_posted" ||
    kind === "discussion_resolved" ||
    kind === "member_joined" ||
    kind === "output_created" ||
    kind === "paper_added"
  ) {
    return kind;
  }
  return "unknown";
}

export function adaptProjectActivity(
  value: ProjectActivityResponse,
): ProjectActivityEvent[] {
  return value.items.map((item) => ({
    actorName: item.actor_display_name,
    documentId: item.document_id,
    documentTitle: item.document_title,
    id: item.id,
    kind: projectActivityKind(item.kind),
    occurredAt: item.occurred_at,
  }));
}

export function adaptPersonalInsights(
  value: ResearchInsightsResponse,
): PersonalResearchInsights {
  return {
    activityHistoryCompleteSince: value.activity_history_complete_since,
    daily: densifyResearchActivityDays({
      days: value.trend.map((day) => ({
        activeMs: day.active_ms,
        date: day.date,
        sessionCount: day.session_count,
        visibleMs: day.visible_ms,
      })),
      emptyDay: { activeMs: 0, sessionCount: 0, visibleMs: 0 },
      range: value.range,
      readingDataSince: value.reading_data_since,
      timeZone: value.time_zone,
    }),
    papers: value.top_papers.map((paper) => ({
      activeMs: paper.active_ms,
      documentId: paper.document_id,
      lastReadAt: paper.last_read_at,
      sessionCount: paper.session_count,
      title: paper.title,
    })),
    projects: value.projects.map((project) => ({
      activeMs: project.active_ms,
      projectId: project.project_id,
      sessionCount: project.session_count,
      title: project.title,
    })),
    range: value.range,
    metricDefinitionVersion: value.metric_definition_version,
    historyPartial: historyIsPartial({
      activityHistoryCompleteSince: value.activity_history_complete_since,
      range: value.range,
      timeZone: value.time_zone,
    }),
    readingDataSince: value.reading_data_since,
    summary: [
      readingMetric("active_ms", value.summary.active_ms, "milliseconds"),
      readingMetric("visible_ms", value.summary.visible_ms, "milliseconds"),
      readingMetric("active_days", value.summary.active_days),
      readingMetric("sessions", value.summary.session_count),
      ...(value.summary.substantive_pages == null
        ? []
        : [
            readingMetric("substantive_pages", value.summary.substantive_pages),
          ]),
      readingMetric("papers_with_activity", value.papers_with_activity),
      readingMetric("annotations", value.annotation_count),
      readingMetric("conversations", value.conversation_count),
      readingMetric("outputs", value.output_count),
    ],
  };
}

export function adaptPaperSummaries(
  value: ReadingPaperSummariesResponse,
): PaperActivitySummary[] {
  return value.items.map((item) => ({
    activeMs: item.active_ms,
    coveragePercent: item.coverage_percent ?? null,
    documentId: item.document_id,
    pageBuckets: item.page_buckets.map((bucket) => ({
      activeMs: bucket.active_ms,
      endPage: bucket.end_page,
      startPage: bucket.start_page,
    })),
    visibleMs: item.visible_ms,
  }));
}

export function chunkPaperSummaryDocumentIds(documentIds: string[]) {
  const uniqueIds = [...new Set(documentIds)];
  return Array.from({ length: Math.ceil(uniqueIds.length / 100) }, (_, index) =>
    uniqueIds.slice(index * 100, (index + 1) * 100),
  );
}
