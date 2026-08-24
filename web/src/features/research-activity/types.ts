export type ResearchActivityRange = "7d" | "30d" | "90d" | "365d" | "all";

export type ResearchActivityMetric = {
  key: string;
  value: number;
  unit: "count" | "milliseconds" | "percent";
};

export type ResearchActivityDay = {
  date: string;
  activeMs: number;
  visibleMs?: number;
  sessionCount?: number;
  teamActiveMs?: number | null;
  sharedEventCount?: number;
};

export type PaperPageActivity = {
  pageNumber: number;
  pageEndNumber: number;
  navigationPageNumber: number;
  activeMs: number;
  visibleMs: number;
  visitCount: number;
  annotationCount: number;
  verticalSegmentsMs: number[];
};

export type ProjectPaperActivityRow = {
  documentId: string;
  title: string | null;
  activeMs: number;
  coveragePercent: number | null;
  lastActivityAt: string | null;
  sharedAnnotationCount: number;
  discussionMessageCount: number;
};

export type PersonalPaperActivityRow = {
  documentId: string;
  title: string | null;
  activeMs: number;
  lastReadAt: string | null;
  sessionCount: number;
};

export type PaperActivitySummary = {
  documentId: string;
  activeMs: number;
  visibleMs: number;
  coveragePercent: number | null;
  pageBuckets: Array<{
    startPage: number;
    endPage: number;
    activeMs: number;
  }>;
};

export type ProjectActivityEvent = {
  id: string;
  kind:
    | "annotation_created"
    | "discussion_message_posted"
    | "discussion_resolved"
    | "member_joined"
    | "output_created"
    | "paper_added"
    | "unknown";
  occurredAt: string;
  actorName?: string | null;
  documentId?: string | null;
  documentTitle?: string | null;
};

export type ProjectResearchInsights = {
  activityHistoryCompleteSince?: string | null;
  historyPartial: boolean;
  metricDefinitionVersion: string;
  range: ResearchActivityRange;
  readingDataSince?: string | null;
  mine: ResearchActivityMetric[];
  team: ResearchActivityMetric[];
  daily: ResearchActivityDay[];
  papers: ProjectPaperActivityRow[];
  papersTotalCount: number;
  teamReadingAvailable: boolean;
};

export type PersonalResearchInsights = {
  activityHistoryCompleteSince?: string | null;
  historyPartial: boolean;
  metricDefinitionVersion: string;
  range: ResearchActivityRange;
  readingDataSince?: string | null;
  summary: ResearchActivityMetric[];
  daily: ResearchActivityDay[];
  projects: Array<{
    projectId: string;
    title: string;
    activeMs: number;
    sessionCount: number;
  }>;
  papers: PersonalPaperActivityRow[];
};

export type PaperResearchInsights = {
  activityHistoryCompleteSince?: string | null;
  historyPartial: boolean;
  metricDefinitionVersion: string;
  readingDataSince?: string | null;
  summary: ResearchActivityMetric[];
  daily: ResearchActivityDay[];
  pages: PaperPageActivity[];
};

export type ReadingActivityPreferences = {
  recordingEnabled: boolean;
  contributeAnonymousProjectAggregates: boolean;
};
