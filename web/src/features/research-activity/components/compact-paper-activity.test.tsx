import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "@/i18n/messages/en.json";
import type { PaperActivitySummary } from "../types";
import {
  CompactPaperActivity,
  hasPaperActivityEvidence,
} from "./compact-paper-activity";

const summary: PaperActivitySummary = {
  activeMs: 0,
  coveragePercent: null,
  documentId: "40000000-0000-4000-8000-000000000001",
  pageBuckets: [{ activeMs: 0, endPage: 5, startPage: 1 }],
  visibleMs: 0,
};

describe("CompactPaperActivity", () => {
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

  it("does not announce invented zero coverage when coverage is unavailable", () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <CompactPaperActivity summary={{ ...summary, activeMs: 120_000 }} />
      </NextIntlClientProvider>,
    );

    const activity = screen.getByLabelText("2 min active reading estimate");
    expect(activity).toBeInTheDocument();
    expect(activity).not.toHaveAccessibleName(/coverage/i);
  });
});
