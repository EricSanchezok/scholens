import { act, cleanup, renderHook } from "@testing-library/react";
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { useReadingActivityTracker } from "./use-reading-activity-tracker";

const originalVisibilityState = Object.getOwnPropertyDescriptor(
  document,
  "visibilityState",
);

function createReaderRoot() {
  const root = document.createElement("div");
  const page = document.createElement("div");
  page.dataset.pdfPageNumber = "1";
  root.append(page);
  document.body.append(root);
  root.getBoundingClientRect = () => new DOMRect(0, 0, 800, 600);
  page.getBoundingClientRect = () => new DOMRect(0, 0, 800, 600);
  return root;
}

async function advance(milliseconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

describe("useReadingActivityTracker lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
  });

  afterEach(() => {
    cleanup();
    document.body.replaceChildren();
    if (originalVisibilityState) {
      Object.defineProperty(
        document,
        "visibilityState",
        originalVisibilityState,
      );
    }
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("establishes the session after the first admitted reading slice", async () => {
    const rootRef: React.RefObject<HTMLDivElement | null> = {
      current: createReaderRoot(),
    };
    const startSession = vi.fn().mockResolvedValue({ revision: 0 });
    const updateSession = vi.fn().mockResolvedValue({ revision: 1 });

    renderHook(() =>
      useReadingActivityTracker({
        contributionKey: true,
        documentId: "40000000-0000-4000-8000-000000000001",
        enabled: true,
        rootRef,
        startSession,
        updateSession,
        viewMode: "pdf",
      }),
    );

    await advance(5_000);

    expect(startSession).toHaveBeenCalledTimes(1);
    expect(updateSession).toHaveBeenCalledTimes(1);
    expect(updateSession.mock.calls[0]?.[0].snapshot).toMatchObject({
      active_ms: 5_000,
      visible_ms: 5_000,
    });
  });

  it("does not create revisions for background ticks", async () => {
    vi.mocked(document.hasFocus).mockReturnValue(false);
    const rootRef: React.RefObject<HTMLDivElement | null> = {
      current: createReaderRoot(),
    };
    const startSession = vi.fn().mockResolvedValue({ revision: 0 });
    const updateSession = vi.fn().mockResolvedValue({ revision: 1 });

    renderHook(() =>
      useReadingActivityTracker({
        contributionKey: true,
        documentId: "40000000-0000-4000-8000-000000000001",
        enabled: true,
        rootRef,
        startSession,
        updateSession,
        viewMode: "pdf",
      }),
    );

    await advance(30_000);

    expect(startSession).not.toHaveBeenCalled();
    expect(updateSession).not.toHaveBeenCalled();
  });

  it("ends on pagehide and never appends to that session afterward", async () => {
    const rootRef: React.RefObject<HTMLDivElement | null> = {
      current: createReaderRoot(),
    };
    const startSession = vi.fn().mockResolvedValue({ revision: 0 });
    const updateSession = vi
      .fn()
      .mockResolvedValueOnce({ revision: 1 })
      .mockResolvedValueOnce({ revision: 2 });

    renderHook(() =>
      useReadingActivityTracker({
        contributionKey: true,
        documentId: "40000000-0000-4000-8000-000000000001",
        enabled: true,
        rootRef,
        startSession,
        updateSession,
        viewMode: "pdf",
      }),
    );
    await advance(5_000);

    await act(async () => {
      window.dispatchEvent(new PageTransitionEvent("pagehide"));
      await Promise.resolve();
    });

    expect(updateSession).toHaveBeenCalledTimes(2);
    expect(updateSession.mock.calls[1]?.[0]).toMatchObject({
      keepalive: true,
    });
    expect(updateSession.mock.calls[1]?.[0].endedAt).toBeTruthy();

    await advance(15_000);
    expect(updateSession).toHaveBeenCalledTimes(2);
  });

  it("retries a lost acknowledgement with the exact same revision payload", async () => {
    const rootRef: React.RefObject<HTMLDivElement | null> = {
      current: createReaderRoot(),
    };
    const startSession = vi.fn().mockResolvedValue({ revision: 0 });
    const updateSession = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("response lost after commit"))
      .mockResolvedValueOnce({ revision: 1 })
      .mockResolvedValueOnce({ revision: 2 });

    renderHook(() =>
      useReadingActivityTracker({
        contributionKey: true,
        documentId: "40000000-0000-4000-8000-000000000001",
        enabled: true,
        rootRef,
        startSession,
        updateSession,
        viewMode: "pdf",
      }),
    );

    await advance(5_000);
    await advance(5_000);

    expect(updateSession).toHaveBeenCalledTimes(3);
    expect(updateSession.mock.calls[1]?.[0]).toBe(
      updateSession.mock.calls[0]?.[0],
    );
    expect(updateSession.mock.calls[1]?.[0]).toEqual(
      updateSession.mock.calls[0]?.[0],
    );
    expect(updateSession.mock.calls[2]?.[0]).toMatchObject({
      revision: 2,
      snapshot: {
        active_ms: 10_000,
        visible_ms: 10_000,
      },
    });
  });

  it("pauses for bfcache without ending and resumes with a new tick baseline", async () => {
    const rootRef: React.RefObject<HTMLDivElement | null> = {
      current: createReaderRoot(),
    };
    const startSession = vi.fn().mockResolvedValue({ revision: 0 });
    const updateSession = vi
      .fn()
      .mockResolvedValueOnce({ revision: 1 })
      .mockResolvedValueOnce({ revision: 2 })
      .mockResolvedValueOnce({ revision: 3 });

    renderHook(() =>
      useReadingActivityTracker({
        contributionKey: true,
        documentId: "40000000-0000-4000-8000-000000000001",
        enabled: true,
        rootRef,
        startSession,
        updateSession,
        viewMode: "pdf",
      }),
    );
    await advance(5_000);
    await advance(2_500);

    await act(async () => {
      window.dispatchEvent(
        new PageTransitionEvent("pagehide", { persisted: true }),
      );
      await Promise.resolve();
    });

    expect(updateSession).toHaveBeenCalledTimes(2);
    expect(updateSession.mock.calls[1]?.[0]).toMatchObject({
      endedAt: undefined,
      keepalive: true,
    });

    window.dispatchEvent(
      new PageTransitionEvent("pageshow", { persisted: true }),
    );
    await advance(30_000);

    expect(updateSession).toHaveBeenCalledTimes(3);
    expect(updateSession.mock.calls[2]?.[0].endedAt).toBeUndefined();
    expect(
      updateSession.mock.calls[2]?.[0].snapshot.visible_ms,
    ).toBeGreaterThan(7_500);
  });

  it("ends the old session when the Project contribution preference changes", async () => {
    const rootRef: React.RefObject<HTMLDivElement | null> = {
      current: createReaderRoot(),
    };
    const startSession = vi.fn().mockResolvedValue({ revision: 0 });
    const updateSession = vi.fn().mockImplementation((input) =>
      Promise.resolve({
        revision: input.endedAt ? 2 : 1,
      }),
    );
    const { rerender } = renderHook(
      ({ contributionKey }) =>
        useReadingActivityTracker({
          contributionKey,
          documentId: "40000000-0000-4000-8000-000000000001",
          enabled: true,
          projectId: "50000000-0000-4000-8000-000000000001",
          rootRef,
          startSession,
          updateSession,
          viewMode: "pdf",
        }),
      { initialProps: { contributionKey: true } },
    );
    await advance(5_000);
    const firstSessionId = startSession.mock.calls[0]?.[0].sessionId;

    await act(async () => {
      rerender({ contributionKey: false });
      await Promise.resolve();
    });
    await advance(5_000);

    expect(startSession).toHaveBeenCalledTimes(2);
    expect(startSession.mock.calls[1]?.[0].sessionId).not.toBe(firstSessionId);
    expect(
      updateSession.mock.calls.some(
        ([input]) =>
          input.sessionId === firstSessionId && Boolean(input.endedAt),
      ),
    ).toBe(true);
  });

  it("keeps a personal session when the Project contribution preference changes", async () => {
    const rootRef: React.RefObject<HTMLDivElement | null> = {
      current: createReaderRoot(),
    };
    const startSession = vi.fn().mockResolvedValue({ revision: 0 });
    const updateSession = vi.fn().mockImplementation((input) =>
      Promise.resolve({
        revision: input.endedAt ? 2 : 1,
      }),
    );
    const { rerender } = renderHook(
      ({ contributionKey }) =>
        useReadingActivityTracker({
          contributionKey,
          documentId: "40000000-0000-4000-8000-000000000001",
          enabled: true,
          rootRef,
          startSession,
          updateSession,
          viewMode: "pdf",
        }),
      { initialProps: { contributionKey: true } },
    );
    await advance(5_000);
    const sessionId = startSession.mock.calls[0]?.[0].sessionId;

    await act(async () => {
      rerender({ contributionKey: false });
      await Promise.resolve();
    });
    await advance(5_000);

    expect(startSession).toHaveBeenCalledTimes(1);
    expect(startSession.mock.calls[0]?.[0].sessionId).toBe(sessionId);
    expect(
      updateSession.mock.calls.some(([input]) => Boolean(input.endedAt)),
    ).toBe(false);
  });

  it("ends and replaces a session before its 24-hour server limit", async () => {
    vi.setSystemTime(new Date("2026-08-24T00:00:00Z"));
    const rootRef: React.RefObject<HTMLDivElement | null> = {
      current: createReaderRoot(),
    };
    const startSession = vi.fn().mockResolvedValue({ revision: 0 });
    const updateSession = vi.fn().mockImplementation((input) =>
      Promise.resolve({
        revision: input.endedAt ? 2 : 1,
      }),
    );

    renderHook(() =>
      useReadingActivityTracker({
        contributionKey: true,
        documentId: "40000000-0000-4000-8000-000000000001",
        enabled: true,
        rootRef,
        startSession,
        updateSession,
        viewMode: "pdf",
      }),
    );
    await advance(5_000);
    const firstSessionId = startSession.mock.calls[0]?.[0].sessionId;

    vi.setSystemTime(new Date("2026-08-24T23:59:00Z"));
    await advance(5_000);
    await advance(5_000);

    expect(
      updateSession.mock.calls.some(
        ([input]) =>
          input.sessionId === firstSessionId && Boolean(input.endedAt),
      ),
    ).toBe(true);
    expect(startSession).toHaveBeenCalledTimes(2);
    expect(startSession.mock.calls[1]?.[0].sessionId).not.toBe(firstSessionId);
  });

  it.each([
    "reading_session_not_found",
    "reading_session_ended",
    "reading_session_revision_conflict",
  ])("starts one fresh session after terminal error %s", async (code) => {
    const rootRef: React.RefObject<HTMLDivElement | null> = {
      current: createReaderRoot(),
    };
    const startSession = vi.fn().mockResolvedValue({ revision: 0 });
    const updateSession = vi
      .fn()
      .mockRejectedValueOnce(new ApiError("session unavailable", 409, code))
      .mockResolvedValueOnce({ revision: 1 });

    renderHook(() =>
      useReadingActivityTracker({
        contributionKey: true,
        documentId: "40000000-0000-4000-8000-000000000001",
        enabled: true,
        rootRef,
        startSession,
        updateSession,
        viewMode: "pdf",
      }),
    );

    await advance(5_000);
    const retiredSessionId = startSession.mock.calls[0]?.[0].sessionId;
    await advance(5_000);

    expect(startSession).toHaveBeenCalledTimes(2);
    expect(startSession.mock.calls[1]?.[0].sessionId).not.toBe(
      retiredSessionId,
    );
    expect(updateSession).toHaveBeenCalledTimes(2);
    expect(updateSession.mock.calls[1]?.[0].sessionId).not.toBe(
      retiredSessionId,
    );
  });

  it("stops a session after a deterministic client rejection", async () => {
    const rootRef: React.RefObject<HTMLDivElement | null> = {
      current: createReaderRoot(),
    };
    const startSession = vi.fn().mockResolvedValue({ revision: 0 });
    const updateSession = vi
      .fn()
      .mockRejectedValue(
        new ApiError(
          "page totals are invalid",
          422,
          "reading_session_page_totals_invalid",
        ),
      );

    renderHook(() =>
      useReadingActivityTracker({
        contributionKey: true,
        documentId: "40000000-0000-4000-8000-000000000001",
        enabled: true,
        rootRef,
        startSession,
        updateSession,
        viewMode: "pdf",
      }),
    );

    await advance(5_000);
    await advance(60_000);

    expect(startSession).toHaveBeenCalledTimes(1);
    expect(updateSession).toHaveBeenCalledTimes(1);
  });
});
