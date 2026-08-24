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
    expect(screen.getByLabelText("Page reading distribution")).toHaveStyle({
      backgroundImage:
        "linear-gradient(90deg, transparent 0%, var(--color-activity-peak) 25%, transparent 50%, var(--color-activity-medium) 75%, transparent 100%)",
    });
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
