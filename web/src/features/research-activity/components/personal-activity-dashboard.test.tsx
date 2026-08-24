import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { PersonalActivityDashboard } from "./personal-activity-dashboard";

describe("PersonalActivityDashboard", () => {
  it.each(["loading", "error"] as const)(
    "keeps range and toolbar controls stable while %s",
    (state) => {
      render(
        <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
          <PersonalActivityDashboard
            error={state === "error"}
            loading={state === "loading"}
            onRangeChange={vi.fn()}
            onRetry={vi.fn()}
            range="90d"
            toolbar={<button type="button">Export activity</button>}
          />
        </NextIntlClientProvider>,
      );

      expect(
        screen.getByRole("group", { name: "Activity range" }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "90 days" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(
        screen.getByRole("button", { name: "Export activity" }),
      ).toBeInTheDocument();
    },
  );

  it("keeps recording-off empty history distinct from first use", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <PersonalActivityDashboard
          insights={{
            activityHistoryCompleteSince: null,
            daily: [],
            historyPartial: false,
            metricDefinitionVersion: "active-reading-v1",
            papers: [],
            projects: [],
            range: "30d",
            summary: [],
          }}
          onRangeChange={vi.fn()}
          onRetry={vi.fn()}
          range="30d"
          recordingEnabled={false}
        />
      </NextIntlClientProvider>,
    );

    expect(
      screen.getByRole("heading", { name: "Reading recording is off" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Activity settings" }),
    ).toHaveAttribute("href", "/me/settings/display?returnTo=/me/activity");
    expect(
      screen.queryByText("Your research rhythm starts here"),
    ).not.toBeInTheDocument();
  });

  it("shows session and last-read context for compact breakdowns", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <PersonalActivityDashboard
          insights={{
            activityHistoryCompleteSince: null,
            daily: [],
            historyPartial: false,
            metricDefinitionVersion: "active-reading-v1",
            papers: [
              {
                activeMs: 60_000,
                documentId: "40000000-0000-4000-8000-000000000001",
                lastReadAt: "2026-08-20T12:00:00Z",
                sessionCount: 2,
                title: "Paper with date",
              },
              {
                activeMs: 30_000,
                documentId: "40000000-0000-4000-8000-000000000002",
                lastReadAt: null,
                sessionCount: 1,
                title: "Paper without date",
              },
            ],
            projects: [
              {
                activeMs: 60_000,
                projectId: "50000000-0000-4000-8000-000000000001",
                sessionCount: 3,
                title: "Project",
              },
            ],
            range: "30d",
            summary: [
              { key: "active_ms", unit: "milliseconds", value: 60_000 },
            ],
          }}
          onRangeChange={vi.fn()}
          onRetry={vi.fn()}
          range="30d"
          recordingEnabled
        />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("3 sessions")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Project" })).toHaveAttribute(
      "href",
      "/projects/50000000-0000-4000-8000-000000000001?range=30d",
    );
    expect(
      screen.getByText("2 sessions · Last read Aug 20, 2026"),
    ).toBeInTheDocument();
    expect(screen.getByText("1 session")).toBeInTheDocument();
    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument();
  });

  it("uses the calendar table as the single daily-data equivalent", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <PersonalActivityDashboard
          insights={{
            activityHistoryCompleteSince: null,
            daily: [{ activeMs: 60_000, date: "2026-08-24" }],
            historyPartial: false,
            metricDefinitionVersion: "active-reading-v1",
            papers: [],
            projects: [],
            range: "365d",
            summary: [
              { key: "active_ms", unit: "milliseconds", value: 60_000 },
            ],
          }}
          onRangeChange={vi.fn()}
          onRetry={vi.fn()}
          range="365d"
          recordingEnabled
        />
      </NextIntlClientProvider>,
    );

    expect(
      screen.getAllByText("View data table", { selector: "summary" }),
    ).toHaveLength(1);
  });
});
