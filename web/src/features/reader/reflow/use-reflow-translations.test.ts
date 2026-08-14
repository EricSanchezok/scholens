import { waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { streamReflowBlockTranslation } from "./api";
import { ReflowTranslationScheduler } from "./use-reflow-translations";

function controlledStream() {
  const calls: Array<{
    blockId: string;
    onEvent: Parameters<typeof streamReflowBlockTranslation>[0]["onEvent"];
    resolve: () => void;
    signal: AbortSignal;
  }> = [];
  const stream = vi.fn(
    (input: Parameters<typeof streamReflowBlockTranslation>[0]) =>
      new Promise<void>((resolve) => {
        calls.push({
          blockId: input.blockId,
          onEvent: input.onEvent,
          resolve,
          signal: input.signal,
        });
      }),
  );
  return { calls, stream };
}

describe("ReflowTranslationScheduler", () => {
  it("requests visible blocks with a hard concurrency limit of two", async () => {
    const controlled = controlledStream();
    const scheduler = new ReflowTranslationScheduler(
      "document-1",
      true,
      controlled.stream,
    );

    scheduler.request("block-1");
    scheduler.request("block-2");
    scheduler.request("block-3");
    scheduler.request("block-1");

    expect(controlled.calls.map((call) => call.blockId)).toEqual([
      "block-1",
      "block-2",
    ]);
    expect(scheduler.getSnapshot()["block-3"]?.status).toBe("queued");

    controlled.calls[0]?.onEvent({ type: "delta", text: "译" });
    controlled.calls[0]?.onEvent({ type: "complete", cacheHit: false });
    controlled.calls[0]?.resolve();

    await waitFor(() => expect(controlled.calls).toHaveLength(3));
    expect(controlled.calls[2]?.blockId).toBe("block-3");
    expect(scheduler.getSnapshot()["block-1"]).toMatchObject({
      status: "completed",
      text: "译",
    });
    scheduler.dispose();
  });

  it("aborts in-flight work when the translation session is disposed", () => {
    const controlled = controlledStream();
    const scheduler = new ReflowTranslationScheduler(
      "document-1",
      true,
      controlled.stream,
    );
    scheduler.request("block-1");

    scheduler.dispose();

    expect(controlled.calls[0]?.signal.aborted).toBe(true);
  });

  it("does not enqueue work while full translation is disabled", () => {
    const controlled = controlledStream();
    const scheduler = new ReflowTranslationScheduler(
      "document-1",
      false,
      controlled.stream,
    );
    scheduler.request("block-1");
    expect(controlled.stream).not.toHaveBeenCalled();
    expect(scheduler.getSnapshot()).toEqual({});
  });
});
