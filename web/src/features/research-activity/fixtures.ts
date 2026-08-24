import type {
  PaperResearchInsights,
  PersonalResearchInsights,
  ProjectActivityEvent,
  ProjectResearchInsights,
  ResearchActivityDay,
  ReadingActivityPreferences,
} from "./types";

const day = 86_400_000;
const end = Date.UTC(2026, 7, 24);

export const activityDays: ResearchActivityDay[] = Array.from(
  { length: 30 },
  (_, index) => {
    const date = new Date(end - (29 - index) * day).toISOString().slice(0, 10);
    const active = index % 6 === 0 ? 0 : (18 + ((index * 17) % 76)) * 60_000;
    return {
      activeMs: active,
      date,
      sharedEventCount: index % 5,
      teamActiveMs: index % 7 === 0 ? null : active + 24 * 60_000,
    };
  },
);

const readingActivityDays: ResearchActivityDay[] = activityDays.map(
  (entry, index) => ({
    activeMs: entry.activeMs,
    date: entry.date,
    sessionCount: entry.activeMs > 0 ? 1 + (index % 3) : 0,
    visibleMs: entry.activeMs > 0 ? entry.activeMs + 12 * 60_000 : 0,
  }),
);

export const paperInsightsFixture: PaperResearchInsights = {
  activityHistoryCompleteSince: null,
  daily: readingActivityDays,
  historyPartial: false,
  metricDefinitionVersion: "active-reading-v1",
  pages: Array.from({ length: 24 }, (_, index) => {
    const activeMs = index % 7 === 0 ? 0 : ((index * 43) % 260) * 1_000;
    const segments = Array.from({ length: 20 }, (__, segment) =>
      segment === (index * 3) % 20 ? activeMs : 0,
    );
    return {
      activeMs,
      annotationCount: index % 6 === 2 ? 1 : 0,
      navigationPageNumber: index + 1,
      pageEndNumber: index + 1,
      pageNumber: index + 1,
      verticalSegmentsMs: segments,
      visibleMs: activeMs + 18_000,
      visitCount: activeMs ? 1 + (index % 4) : 0,
    };
  }),
  readingDataSince: "2026-07-12T08:00:00Z",
  summary: [
    { key: "active_ms", unit: "milliseconds", value: 5_940_000 },
    { key: "visible_ms", unit: "milliseconds", value: 7_380_000 },
    { key: "sessions", unit: "count", value: 8 },
    { key: "active_days", unit: "count", value: 6 },
    { key: "annotations", unit: "count", value: 4 },
    { key: "coverage_percent", unit: "percent", value: 71 },
  ],
};

const projectPapers = [
  "Attention Is All You Need",
  "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
  "Generative Agents: Interactive Simulacra of Human Behavior",
  "A Survey on Large Language Model Based Autonomous Agents",
].map((title, index) => ({
  activeMs: (index + 2) * 31 * 60_000,
  coveragePercent: null,
  documentId: `10000000-0000-4000-8000-00000000000${index + 1}`,
  lastActivityAt: index === 3 ? null : `2026-08-${20 + index}T08:00:00Z`,
  discussionMessageCount: index + 1,
  sharedAnnotationCount: index,
  title,
}));

export const projectInsightsFixture: ProjectResearchInsights = {
  activityHistoryCompleteSince: null,
  daily: activityDays,
  historyPartial: false,
  metricDefinitionVersion: "active-reading-v1",
  mine: [
    { key: "active_ms", unit: "milliseconds", value: 13_320_000 },
    { key: "visible_ms", unit: "milliseconds", value: 15_720_000 },
    { key: "active_days", unit: "count", value: 18 },
    { key: "sessions", unit: "count", value: 31 },
    { key: "papers_with_activity", unit: "count", value: 8 },
    { key: "annotations", unit: "count", value: 27 },
    { key: "conversations", unit: "count", value: 14 },
  ],
  papers: projectPapers,
  papersTotalCount: 148,
  range: "30d",
  readingDataSince: "2026-07-12T08:00:00Z",
  team: [
    { key: "active_ms", unit: "milliseconds", value: 28_260_000 },
    { key: "visible_ms", unit: "milliseconds", value: 33_480_000 },
    { key: "papers_with_activity", unit: "count", value: 12 },
    { key: "active_members", unit: "count", value: 4 },
    { key: "papers_added", unit: "count", value: 12 },
    { key: "shared_annotations", unit: "count", value: 27 },
    { key: "discussion_messages", unit: "count", value: 18 },
    { key: "resolved_discussions", unit: "count", value: 6 },
    { key: "outputs", unit: "count", value: 5 },
  ],
  teamReadingAvailable: true,
};

export const projectActivityFixture: ProjectActivityEvent[] = [
  {
    actorName: "Mina Park",
    documentId: "10000000-0000-4000-8000-000000000001",
    documentTitle: "Generative Agents: Interactive Simulacra of Human Behavior",
    id: "activity-1",
    kind: "annotation_created",
    occurredAt: "2026-08-24T08:00:00Z",
  },
  {
    actorName: "Eric Sanchez",
    id: "activity-2",
    kind: "output_created",
    occurredAt: "2026-08-23T10:30:00Z",
  },
  {
    actorName: "Mina Park",
    id: "activity-3",
    kind: "discussion_resolved",
    occurredAt: "2026-08-22T09:00:00Z",
  },
];

export const personalInsightsFixture: PersonalResearchInsights = {
  activityHistoryCompleteSince: null,
  daily: readingActivityDays,
  historyPartial: false,
  metricDefinitionVersion: "active-reading-v1",
  papers: projectPapers.map((paper, index) => ({
    activeMs: paper.activeMs,
    documentId: paper.documentId,
    lastReadAt: `2026-08-${20 + index}T08:00:00Z`,
    sessionCount: 4 + index,
    title: paper.title,
  })),
  projects: [
    {
      activeMs: 13_320_000,
      projectId: "50000000-0000-4000-8000-000000000001",
      sessionCount: 31,
      title: "Living World Engine",
    },
    {
      activeMs: 7_260_000,
      projectId: "50000000-0000-4000-8000-000000000002",
      sessionCount: 17,
      title: "Trustworthy retrieval",
    },
  ],
  range: "365d",
  readingDataSince: "2026-07-12T08:00:00Z",
  summary: [
    { key: "active_ms", unit: "milliseconds", value: 31_860_000 },
    { key: "visible_ms", unit: "milliseconds", value: 38_520_000 },
    { key: "active_days", unit: "count", value: 42 },
    { key: "sessions", unit: "count", value: 78 },
    { key: "papers_with_activity", unit: "count", value: 36 },
    { key: "outputs", unit: "count", value: 12 },
  ],
};

export const paperActivitySummaryFixture = {
  activeMs: 5_940_000,
  coveragePercent: 71,
  documentId: "10000000-0000-4000-8000-000000000001",
  pageBuckets: Array.from({ length: 12 }, (_, index) => ({
    activeMs: index % 4 === 0 ? 0 : ((index * 47) % 210) * 1_000,
    endPage: (index + 1) * 2,
    startPage: index * 2 + 1,
  })),
  visibleMs: 7_020_000,
};

export const readingActivityPreferencesFixture = {
  contributeAnonymousProjectAggregates: true,
  recordingEnabled: true,
} satisfies ReadingActivityPreferences;
