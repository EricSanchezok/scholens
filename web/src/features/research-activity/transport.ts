import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/lib/api";
import {
  adaptPaperSummaries,
  adaptPersonalInsights,
  adaptPreferences,
  adaptProjectActivity,
  adaptProjectInsights,
} from "./adapters";
import { collectReadingActivityCsv } from "./export";
import type {
  ReadingSessionStarter,
  ReadingSessionUpdater,
} from "./use-reading-activity-tracker";
import type {
  ReadingActivityPreferences,
  ResearchActivityRange,
} from "./types";

function timeZone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function requireData<T>(data: T | undefined, resource: string): T {
  if (!data) throw new Error(`${resource} response was empty`);
  return data;
}

export const researchActivityKeys = {
  all: ["research-activity"] as const,
  preferences: () => ["research-activity", "preferences"] as const,
  paper: (
    documentId: string,
    projectId: string | undefined,
    range: ResearchActivityRange,
    zone: string,
  ) =>
    [
      "research-activity",
      "paper",
      documentId,
      projectId ?? null,
      range,
      zone,
    ] as const,
  project: (projectId: string, range: ResearchActivityRange) =>
    ["research-activity", "project", projectId, range, "UTC"] as const,
  projectActivity: (projectId: string) =>
    ["research-activity", "project", projectId, "activity"] as const,
  personal: (range: ResearchActivityRange, zone: string) =>
    ["research-activity", "personal", range, zone] as const,
  summaries: (documentIds: string[]) =>
    ["research-activity", "paper-summaries", documentIds] as const,
};

export const researchActivityQueries = {
  preferences: () =>
    queryOptions({
      queryKey: researchActivityKeys.preferences(),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/me/reading-activity-preferences",
          { signal },
        );
        return adaptPreferences(
          requireData(data, "Reading activity preferences"),
        );
      },
      staleTime: 60_000,
    }),
  paper: (
    documentId: string,
    projectId: string | undefined,
    range: ResearchActivityRange,
  ) => {
    const zone = timeZone();
    return queryOptions({
      queryKey: researchActivityKeys.paper(documentId, projectId, range, zone),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/papers/{document_id}/insights",
          {
            params: {
              path: { document_id: documentId },
              query: { project_id: projectId, range, time_zone: zone },
            },
            signal,
          },
        );
        return requireData(data, "Paper insights");
      },
    });
  },
  project: (projectId: string, range: ResearchActivityRange) =>
    queryOptions({
      queryKey: researchActivityKeys.project(projectId, range),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/projects/{project_id}/insights",
          {
            params: {
              path: { project_id: projectId },
              query: { range },
            },
            signal,
          },
        );
        return adaptProjectInsights(requireData(data, "Project insights"));
      },
    }),
  projectActivity: (projectId: string) =>
    queryOptions({
      queryKey: researchActivityKeys.projectActivity(projectId),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET(
          "/api/v1/projects/{project_id}/activity",
          {
            params: { path: { project_id: projectId }, query: { limit: 8 } },
            signal,
          },
        );
        return adaptProjectActivity(requireData(data, "Project activity"));
      },
    }),
  personal: (range: ResearchActivityRange) => {
    const zone = timeZone();
    return queryOptions({
      queryKey: researchActivityKeys.personal(range, zone),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.GET("/api/v1/me/research-insights", {
          params: { query: { range, time_zone: zone } },
          signal,
        });
        return adaptPersonalInsights(requireData(data, "Research insights"));
      },
    });
  },
  paperSummaries: (ids: string[]) => {
    const documentIds = [...new Set(ids)];
    if (documentIds.length > 100) {
      throw new RangeError(
        "Paper summary requests are limited to 100 documents",
      );
    }
    return queryOptions({
      enabled: documentIds.length > 0,
      queryKey: researchActivityKeys.summaries(documentIds),
      queryFn: async ({ signal }) => {
        const { data } = await apiClient.POST(
          "/api/v1/me/reading-activity/paper-summaries",
          { body: { document_ids: documentIds }, signal },
        );
        return adaptPaperSummaries(
          requireData(data, "Paper activity summaries"),
        );
      },
      staleTime: 30_000,
    });
  },
};

export async function updateReadingActivityPreferences(
  value: ReadingActivityPreferences,
) {
  const { data } = await apiClient.PUT(
    "/api/v1/me/reading-activity-preferences",
    {
      body: {
        contribute_anonymous_project_aggregates:
          value.contributeAnonymousProjectAggregates,
        recording_enabled: value.recordingEnabled,
      },
    },
  );
  return adaptPreferences(requireData(data, "Reading activity preferences"));
}

export const startReadingSession: ReadingSessionStarter = async (input) => {
  const { data } = await apiClient.POST(
    "/api/v1/papers/{document_id}/reading-sessions",
    {
      body: {
        metric_definition_version: input.metricDefinitionVersion,
        project_id: input.projectId,
        session_id: input.sessionId,
        started_at: input.startedAt,
        time_zone: input.timeZone,
        view_mode: input.viewMode,
      },
      keepalive: input.keepalive,
      params: { path: { document_id: input.documentId } },
    },
  );
  return { revision: requireData(data, "Reading session").revision };
};

export const updateReadingSession: ReadingSessionUpdater = async (input) => {
  const { data } = await apiClient.PUT(
    "/api/v1/reading-sessions/{session_id}",
    {
      body: {
        active_ms: input.snapshot.active_ms,
        ended_at: input.endedAt,
        hours: input.snapshot.hours,
        last_seen_at: input.lastSeenAt,
        pages: input.snapshot.pages,
        revision: input.revision,
        visible_ms: input.snapshot.visible_ms,
      },
      keepalive: input.keepalive,
      params: { path: { session_id: input.sessionId } },
    },
  );
  return { revision: requireData(data, "Reading session").revision };
};

export async function deletePaperReadingActivity(documentId: string) {
  await apiClient.DELETE("/api/v1/papers/{document_id}/reading-activity", {
    params: { path: { document_id: documentId } },
  });
}

export async function deleteProjectReadingActivity(projectId: string) {
  await apiClient.DELETE("/api/v1/projects/{project_id}/me/reading-activity", {
    params: { path: { project_id: projectId } },
  });
}

export async function deleteAllReadingActivity() {
  await apiClient.DELETE("/api/v1/me/reading-activity");
}

export async function exportReadingActivity() {
  return collectReadingActivityCsv(async ({ cursor, includeHeader }) => {
    const { data, response } = await apiClient.GET(
      "/api/v1/me/reading-activity/export",
      {
        params: {
          query: {
            cursor,
            format: "csv",
            include_header: includeHeader,
            limit: 1_000,
          },
        },
        parseAs: "blob",
      },
    );
    return {
      blob: requireData(data, "Reading activity export"),
      nextCursor: response.headers.get("X-Next-Cursor"),
    };
  });
}
