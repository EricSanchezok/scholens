import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReaderSelection } from "../components/pdf-page";
import * as translationApi from "./api";
import {
  AUTO_TRANSLATION_DELAY_MS,
  useReaderTranslation,
} from "./use-reader-translation";

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

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  queryClient.setQueryData(translationApi.translationKeys.current(), {
    auto_translate_selection: true,
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
});
