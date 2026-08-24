import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "@/i18n/messages/en.json";
import type { PaperActivitySummary } from "../types";
import {
  CompactPaperActivityDuration,
  CompactPaperActivityTrail,
  hasPaperActivityEvidence,
} from "./compact-paper-activity";

const summary: PaperActivitySummary = {
  activeMs: 0,
  coveragePercent: null,
  documentId: "40000000-0000-4000-8000-000000000001",
  pageBuckets: [{ activeMs: 0, endPage: 5, startPage: 1 }],
  visibleMs: 0,
};

describe("compact paper activity", () => {
  it("omits summaries without active-reading evidence", () => {
    expect(hasPaperActivityEvidence(summary)).toBe(false);
    expect(hasPaperActivityEvidence({ ...summary, visibleMs: 1 })).toBe(false);
    expect(hasPaperActivityEvidence({ ...summary, coveragePercent: 10 })).toBe(
      false,
    );
    expect(hasPaperActivityEvidence({ ...summary, activeMs: 1 })).toBe(true);
    expect(
      hasPaperActivityEvidence({
        ...summary,
        pageBuckets: [{ activeMs: 1, endPage: 5, startPage: 1 }],
      }),
    ).toBe(true);
  });

  it("separates the reading duration from the page-distribution trail", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <CompactPaperActivityTrail
          summary={{
            ...summary,
            activeMs: 120_000,
            pageBuckets: [
              { activeMs: 120_000, endPage: 1, startPage: 1 },
              { activeMs: 0, endPage: 2, startPage: 2 },
              { activeMs: 60_000, endPage: 3, startPage: 3 },
            ],
          }}
        />
        <CompactPaperActivityDuration
          summary={{ ...summary, activeMs: 120_000 }}
        />
      </NextIntlClientProvider>,
    );

    const activity = screen.getByLabelText("2 min active reading estimate");
    expect(activity).toBeInTheDocument();
    expect(activity).not.toHaveAccessibleName(/coverage/i);
    const trail = screen.getByLabelText("Recorded page reading distribution");
    const cells = trail.querySelectorAll("[data-paper-activity-cell]");
    expect(cells).toHaveLength(3);
    expect(trail).toHaveAttribute("data-page-range-complete", "false");
    expect(
      trail.querySelector("[data-paper-activity-continuation]"),
    ).toHaveTextContent("…");
    expect(cells[0]).toHaveClass("bg-activity-peak");
    expect(cells[0]).toHaveAttribute("title", "Page 1: 2 min active reading");
    expect(cells[1]).toHaveClass("bg-activity-empty");
    expect(cells[2]).toHaveClass("bg-activity-medium");
  });

  it("bounds dense page distributions to twelve contiguous cells", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <CompactPaperActivityTrail
          summary={{
            ...summary,
            activeMs: 180_000,
            coveragePercent: 60,
            pageBuckets: Array.from({ length: 18 }, (_, index) => ({
              activeMs: (index + 1) * 1_000,
              endPage: index + 1,
              startPage: index + 1,
            })),
          }}
        />
      </NextIntlClientProvider>,
    );

    const cells = screen
      .getByLabelText("Page reading distribution")
      .querySelectorAll("[data-paper-activity-cell]");
    expect(cells).toHaveLength(12);
    expect(cells[0]).toHaveAttribute("data-page-range", "1");
    expect(cells[11]).toHaveAttribute("data-page-range", "17–18");
    expect(
      screen
        .getByLabelText("Page reading distribution")
        .querySelector("[data-paper-activity-continuation]"),
    ).not.toBeInTheDocument();
  });

  it("omits an empty distribution instead of exposing an empty image", () => {
    const { container } = render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <CompactPaperActivityTrail
          summary={{ ...summary, activeMs: 60_000, pageBuckets: [] }}
        />
      </NextIntlClientProvider>,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("keeps known coverage as supporting text in the reading column", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <CompactPaperActivityDuration
          summary={{ ...summary, activeMs: 120_000, coveragePercent: 25 }}
        />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("2 min")).toBeInTheDocument();
    expect(screen.getByText("25% covered")).toBeInTheDocument();
  });
});
