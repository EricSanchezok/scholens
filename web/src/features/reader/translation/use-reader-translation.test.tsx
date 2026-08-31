import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReaderSelection } from "../components/pdf-page";
import * as translationApi from "./api";
import {
  AUTO_TRANSLATION_DELAY_MS,
  TRANSLATION_DELTA_FLUSH_INTERVAL_MS,
  useReaderTranslation,
} from "./use-reader-translation";
import { ApiError } from "@/lib/api";

type SelectionTranslationEventHandler = Parameters<
  typeof translationApi.streamSelectionTranslation
>[0]["onEvent"];

function selection(text: string): ReaderSelection {
  return {
    kind: "paper_selection",
    document_id: "10000000-0000-4000-8000-000000000001",
    page_number: 2,
    selected_text: text,
    anchor: {
      kind: "pdf_text",
      page_number: 2,
      rects: [{ x: 0.1, y: 0.2, width: 0.4, height: 0.03 }],
    },
  };
}

function createWrapper(autoTranslateSelection = true) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  queryClient.setQueryData(translationApi.translationKeys.current(), {
    auto_translate_selection: autoTranslateSelection,
    custom_instructions: null,
    source_language: "auto",
    target_language: "zh-CN",
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useReaderTranslation", () => {
  it("waits for a stable selection before automatic translation", async () => {
    vi.useFakeTimers();
    const stream = vi
      .spyOn(translationApi, "streamSelectionTranslation")
      .mockResolvedValue(undefined);
    renderHook(
      () =>
        useReaderTranslation({
          documentId: "10000000-0000-4000-8000-000000000001",
          selection: selection("stable source"),
        }),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTO_TRANSLATION_DELAY_MS - 1);
    });
    expect(stream).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(stream).toHaveBeenCalledOnce();
  });

  it("aborts stale requests when the selection changes", async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    vi.spyOn(translationApi, "streamSelectionTranslation").mockImplementation(
      async ({ signal }) => {
        signals.push(signal);
        await new Promise<void>(() => undefined);
      },
    );
    const { rerender } = renderHook(
      ({ source }) =>
        useReaderTranslation({
          documentId: "10000000-0000-4000-8000-000000000001",
          selection: selection(source),
        }),
      { initialProps: { source: "first" }, wrapper: createWrapper() },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTO_TRANSLATION_DELAY_MS);
    });
    expect(signals[0]?.aborted).toBe(false);

    rerender({ source: "second" });
    expect(signals[0]?.aborted).toBe(true);
  });

  it("merges consecutive deltas into one bounded state commit", async () => {
    vi.useFakeTimers();
    let emit: SelectionTranslationEventHandler | undefined;
    vi.spyOn(translationApi, "streamSelectionTranslation").mockImplementation(
      async ({ onEvent }) => {
        emit = onEvent;
        await new Promise<void>(() => undefined);
      },
    );
    let renderCount = 0;
    const { result } = renderHook(
      () => {
        renderCount += 1;
        return useReaderTranslation({
          documentId: "10000000-0000-4000-8000-000000000001",
          selection: selection("stream source"),
        });
      },
      { wrapper: createWrapper(false) },
    );

    await act(async () => {
      void result.current.translate("manual");
    });
    const rendersBeforeDeltas = renderCount;
    act(() => {
      emit?.({ type: "delta", text: "第" });
      emit?.({ type: "delta", text: "一" });
      emit?.({ type: "delta", text: "段" });
    });
    expect(result.current.state.translatedText).toBe("");
    expect(renderCount).toBe(rendersBeforeDeltas);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(
        TRANSLATION_DELTA_FLUSH_INTERVAL_MS,
      );
    });
    expect(result.current.state.translatedText).toBe("第一段");
    expect(renderCount).toBe(rendersBeforeDeltas + 1);
  });

  it.each(["complete", "error"] as const)(
    "flushes the final delta before a %s event",
    async (terminalEvent) => {
      vi.useFakeTimers();
      vi.spyOn(
        translationApi,
        "streamSelectionTranslation",
      ).mockImplementation(async ({ onEvent }) => {
        onEvent({ type: "delta", text: "最后一段" });
        onEvent(
          terminalEvent === "complete"
            ? { type: "complete", cacheHit: false }
            : {
                type: "error",
                code: "provider_error",
                message: "Provider failed",
                retryable: true,
              },
        );
      });
      const { result } = renderHook(
        () =>
          useReaderTranslation({
            documentId: "10000000-0000-4000-8000-000000000001",
            selection: selection("terminal source"),
          }),
        { wrapper: createWrapper(false) },
      );

      await act(async () => {
        await result.current.translate("manual");
      });

      expect(result.current.state.translatedText).toBe("最后一段");
      expect(result.current.state.status).toBe(
        terminalEvent === "complete" ? "completed" : "error",
      );
    },
  );

  it("ignores late events from an aborted selection request", async () => {
    vi.useFakeTimers();
    const events: SelectionTranslationEventHandler[] = [];
    vi.spyOn(translationApi, "streamSelectionTranslation").mockImplementation(
      async ({ onEvent }) => {
        events.push(onEvent);
        await new Promise<void>(() => undefined);
      },
    );
    const { result, rerender } = renderHook(
      ({ source }) =>
        useReaderTranslation({
          documentId: "10000000-0000-4000-8000-000000000001",
          selection: selection(source),
        }),
      { initialProps: { source: "first" }, wrapper: createWrapper() },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTO_TRANSLATION_DELAY_MS);
    });
    rerender({ source: "second" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTO_TRANSLATION_DELAY_MS);
    });
    act(() => {
      events[0]?.({ type: "delta", text: "stale" });
      events[0]?.({ type: "complete", cacheHit: false });
      events[1]?.({ type: "delta", text: "fresh" });
      events[1]?.({ type: "complete", cacheHit: false });
    });

    expect(result.current.state.selection?.selected_text).toBe("second");
    expect(result.current.state.translatedText).toBe("fresh");
    expect(result.current.state.status).toBe("completed");
  });

  it("maps a codeless 403 into the edge_blocked error state", async () => {
    vi.useFakeTimers();
    vi.spyOn(translationApi, "streamSelectionTranslation").mockRejectedValue(
      new ApiError("Request failed with status 403", 403),
    );
    const { result } = renderHook(
      () =>
        useReaderTranslation({
          documentId: "10000000-0000-4000-8000-000000000001",
          selection: selection("contains ../cwm-sft"),
        }),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTO_TRANSLATION_DELAY_MS);
    });

    expect(result.current.state.status).toBe("error");
    expect(result.current.state.errorCode).toBe("edge_blocked");
    expect(result.current.state.retryable).toBe(false);
    expect(result.current.state.translatedText).toBe("");
  });
});
