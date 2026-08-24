import { fireEvent, render, screen } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";

import {
  ActivityCalendar,
  ActivityTrendChart,
  activityTrendPath,
  ReadingIntensityMap,
} from "./activity-visualizations";

describe("activityTrendPath", () => {
  it("starts a new segment after suppressed or missing team values", () => {
    const path = activityTrendPath([10, null, 20, 30], 300, 100, 30);

    expect(path.match(/M/g)).toHaveLength(2);
    expect(path).toContain("M200.00,33.33 L300.00,0.00");
  });

  it("renders a visible point when the selected range has one day", () => {
    const { container } = render(
      React.createElement(ActivityTrendChart, {
        days: [{ activeMs: 60_000, date: "2026-08-24" }],
        labels: {
          active: "Active reading estimate",
          chart: "Activity trend",
          date: "Date",
          events: "Events",
          sessions: "Sessions",
          table: "View data table",
          team: "Team reading",
          visible: "Visible time",
        },
        locale: "en",
      }),
    );

    expect(container.querySelector('path[d^="M360.00,"]')).toBeInTheDocument();
    expect(
      container.querySelector('circle[data-series="personal"]'),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Aug 24")).toHaveLength(2);
  });
});

describe("ActivityCalendar", () => {
  it("exposes visible time and sessions in its tabular equivalent", () => {
    render(
      React.createElement(ActivityCalendar, {
        days: [
          {
            activeMs: 60_000,
            date: "2026-08-24",
            sessionCount: 2,
            visibleMs: 90_000,
          },
        ],
        labels: {
          chart: "Reading calendar",
          date: "Date",
          sessions: "Sessions",
          table: "View data table",
          time: "Active reading estimate",
          visible: "Visible time",
        },
        locale: "en",
        tableInitiallyOpen: true,
      }),
    );

    expect(
      screen.getByRole("columnheader", { name: "Visible time" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Sessions" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "2" })).toBeInTheDocument();
  });
});

describe("ReadingIntensityMap", () => {
  it("labels aggregated ranges, navigates to their hottest page, and skips inactive segment DOM", () => {
    const onPageSelect = vi.fn();
    render(
      React.createElement(ReadingIntensityMap, {
        labels: {
          annotations: (count) => `${count} annotations`,
          page: (page) => String(page),
          pageDetail: ({ page }) => `Page ${page}`,
          pageRange: (startPage, endPage) => `${startPage}–${endPage}`,
          pageRangeDetail: ({ endPage, startPage }) =>
            `Pages ${startPage}–${endPage}`,
        },
        locale: "en",
        onPageSelect,
        pages: [
          {
            activeMs: 0,
            annotationCount: 1,
            navigationPageNumber: 1,
            pageEndNumber: 50,
            pageNumber: 1,
            verticalSegmentsMs: Array.from({ length: 20 }, () => 0),
            visibleMs: 0,
            visitCount: 0,
          },
          {
            activeMs: 60_000,
            annotationCount: 2,
            navigationPageNumber: 72,
            pageEndNumber: 100,
            pageNumber: 51,
            verticalSegmentsMs: [
              60_000,
              ...Array.from({ length: 19 }, () => 0),
            ],
            visibleMs: 80_000,
            visitCount: 2,
          },
        ],
      }),
    );

    const inactive = screen.getByRole("button", { name: "Pages 1–50" });
    const active = screen.getByRole("button", { name: "Pages 51–100" });
    expect(inactive.querySelectorAll("span[aria-hidden] span")).toHaveLength(0);
    expect(active.querySelectorAll("span[aria-hidden] span")).toHaveLength(20);
    expect(
      inactive.querySelector('span[aria-label="1 annotations"]'),
    ).toHaveClass("bg-activity-peak");
    expect(
      active.querySelector('span[aria-label="2 annotations"]'),
    ).toHaveClass("bg-surface");

    fireEvent.click(active);
    expect(onPageSelect).toHaveBeenCalledWith(72);
  });
});
