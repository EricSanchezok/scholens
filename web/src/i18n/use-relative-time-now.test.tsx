import { act, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";

import { useRelativeTimeNow } from "./use-relative-time-now";

function RelativeLabel({ value }: { value: string }) {
  const formatRelativeTime = useRelativeTimeNow();
  return <span data-testid="relative">{formatRelativeTime(value)}</span>;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("useRelativeTimeNow", () => {
  it("ticks past a frozen provider now instead of showing future times", async () => {
    vi.useFakeTimers();
    // Wall clock when the comment was created, nine minutes after the tab
    // rendered and froze its provider `now`.
    vi.setSystemTime(new Date("2026-08-04T10:20:00Z"));
    const frozenNow = new Date("2026-08-04T10:00:00Z");
    const createdAt = "2026-08-04T10:09:00Z";

    render(
      <NextIntlClientProvider
        locale="en"
        messages={messages}
        now={frozenNow}
        timeZone="UTC"
      >
        <RelativeLabel value={createdAt} />
      </NextIntlClientProvider>,
    );

    // The initial client render inherits the frozen provider now, matching the
    // server markup and reproducing the reported "in 9 minutes" symptom.
    expect(screen.getByTestId("relative")).toHaveTextContent("in 9 minutes");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });

    // After one tick the label is computed against the live clock.
    expect(screen.getByTestId("relative")).toHaveTextContent(/minutes? ago/);
    expect(screen.getByTestId("relative")).not.toHaveTextContent(
      "in 9 minutes",
    );
  });
});
