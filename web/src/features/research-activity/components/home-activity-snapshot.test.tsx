import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { HomeActivitySnapshot } from "./home-activity-snapshot";

describe("HomeActivitySnapshot", () => {
  it("routes a recording-off empty state to activity settings", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <HomeActivitySnapshot onRetry={vi.fn()} recordingEnabled={false} />
      </NextIntlClientProvider>,
    );

    expect(
      screen.getByRole("link", { name: /Activity settings/i }),
    ).toHaveAttribute("href", "/me/settings/display?returnTo=/");
    expect(screen.getByText(/Reading recording is off/)).toBeInTheDocument();
  });

  it("shows non-reading research facts instead of an empty state", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <HomeActivitySnapshot
          insights={{
            activityHistoryCompleteSince: null,
            daily: [],
            historyPartial: false,
            metricDefinitionVersion: "active-reading-v1",
            papers: [],
            projects: [],
            range: "30d",
            summary: [
              { key: "active_ms", unit: "milliseconds", value: 0 },
              { key: "annotations", unit: "count", value: 5 },
              { key: "conversations", unit: "count", value: 2 },
              { key: "outputs", unit: "count", value: 1 },
            ],
          }}
          onRetry={vi.fn()}
          recordingEnabled
        />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("5 annotations")).toBeInTheDocument();
    expect(screen.getByText("2 private questions")).toBeInTheDocument();
    expect(screen.getByText("1 output")).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Your reading rhythm and research progress will appear here.",
      ),
    ).not.toBeInTheDocument();
  });

  it("keeps a single recorded day in one slot of the 30-day trend", () => {
    const { container } = render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <HomeActivitySnapshot
          insights={{
            activityHistoryCompleteSince: null,
            daily: [{ activeMs: 180_000, date: "2026-08-25" }],
            historyPartial: false,
            metricDefinitionVersion: "active-reading-v1",
            papers: [],
            projects: [],
            range: "30d",
            readingDataSince: "2026-08-25T00:00:00Z",
            summary: [
              { key: "active_ms", unit: "milliseconds", value: 180_000 },
              { key: "active_days", unit: "count", value: 1 },
              { key: "papers_with_activity", unit: "count", value: 1 },
            ],
          }}
          onRetry={vi.fn()}
          recordingEnabled
        />
      </NextIntlClientProvider>,
    );

    expect(
      container.querySelectorAll('[data-activity-slot="missing"]'),
    ).toHaveLength(29);
    expect(
      container.querySelectorAll('[data-activity-slot="active"]'),
    ).toHaveLength(1);
  });
});
