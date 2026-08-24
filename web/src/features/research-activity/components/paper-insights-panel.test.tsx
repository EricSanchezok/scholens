import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import type { PaperResearchInsights } from "../types";
import { PaperInsightsPanel } from "./paper-insights-panel";

const annotationOnlyInsights: PaperResearchInsights = {
  activityHistoryCompleteSince: null,
  daily: [],
  historyPartial: false,
  metricDefinitionVersion: "active-reading-v1",
  pages: [
    {
      activeMs: 0,
      annotationCount: 1,
      navigationPageNumber: 1,
      pageEndNumber: 1,
      pageNumber: 1,
      verticalSegmentsMs: Array.from({ length: 20 }, () => 0),
      visibleMs: 0,
      visitCount: 0,
    },
  ],
  summary: [
    { key: "active_ms", unit: "milliseconds", value: 0 },
    { key: "visible_ms", unit: "milliseconds", value: 0 },
    { key: "annotations", unit: "count", value: 1 },
  ],
};

describe("PaperInsightsPanel", () => {
  it("distinguishes recording-off from a first-use empty state", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <PaperInsightsPanel
          insights={{
            activityHistoryCompleteSince: "2026-08-01T00:00:00Z",
            daily: [],
            historyPartial: false,
            metricDefinitionVersion: "active-reading-v1",
            pages: [],
            summary: [],
          }}
          onPageSelect={vi.fn()}
          onRetry={vi.fn()}
          recordingEnabled={false}
        />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("Reading recording is off")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Activity settings" }),
    ).toHaveAttribute("href", "/me/settings/display");
    expect(
      screen.queryByText("Your reading map will appear here"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Activity metrics available since Aug 1, 2026"),
    ).toBeInTheDocument();
  });

  it("shows an annotation-only paper instead of the empty state", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <PaperInsightsPanel
          insights={annotationOnlyInsights}
          onPageSelect={vi.fn()}
          onRetry={vi.fn()}
        />
      </NextIntlClientProvider>,
    );

    expect(
      screen.getByRole("heading", { name: "Reading summary" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Annotations")).toBeInTheDocument();
    expect(
      screen.getByText(/at least 15 seconds of accumulated active reading/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Substantial coverage")).not.toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Page 1:.*1 annotation/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Your reading map will appear here"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Under 15 sec")).toBeInTheDocument();
    expect(screen.getByText("At least 3 min")).toBeInTheDocument();
  });

  it("shows localized singular and plural revisit context", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <PaperInsightsPanel
          insights={{
            ...annotationOnlyInsights,
            activityHistoryCompleteSince: "2026-08-01T00:00:00Z",
            pages: [
              {
                activeMs: 120_000,
                annotationCount: 1,
                navigationPageNumber: 1,
                pageEndNumber: 1,
                pageNumber: 1,
                verticalSegmentsMs: [
                  120_000,
                  ...Array.from({ length: 19 }, () => 0),
                ],
                visibleMs: 140_000,
                visitCount: 1,
              },
              {
                activeMs: 60_000,
                annotationCount: 3,
                navigationPageNumber: 2,
                pageEndNumber: 2,
                pageNumber: 2,
                verticalSegmentsMs: [
                  60_000,
                  ...Array.from({ length: 19 }, () => 0),
                ],
                visibleMs: 80_000,
                visitCount: 2,
              },
            ],
            summary: [
              { key: "active_ms", unit: "milliseconds", value: 180_000 },
              { key: "annotations", unit: "count", value: 4 },
            ],
            readingDataSince: "2026-08-20T00:00:00Z",
          }}
          onPageSelect={vi.fn()}
          onRetry={vi.fn()}
        />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("1 visit · 1 annotation")).toBeInTheDocument();
    expect(screen.getByText("2 visits · 3 annotations")).toBeInTheDocument();
    expect(
      screen.getByText("Recording since Aug 20, 2026"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Activity metrics available since Aug 1, 2026"),
    ).not.toBeInTheDocument();
  });

  it("keeps destructive activity deletion inside the Data menu", async () => {
    const onDeleteActivity = vi.fn();
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <PaperInsightsPanel
          insights={{
            ...annotationOnlyInsights,
            summary: [
              { key: "active_ms", unit: "milliseconds", value: 60_000 },
              { key: "annotations", unit: "count", value: 1 },
            ],
          }}
          onDeleteActivity={onDeleteActivity}
          onPageSelect={vi.fn()}
          onRetry={vi.fn()}
        />
      </NextIntlClientProvider>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: "Data" }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Delete activity" }),
    );
    expect(onDeleteActivity).toHaveBeenCalledOnce();
  });
});
