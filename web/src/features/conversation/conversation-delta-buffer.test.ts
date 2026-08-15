import { describe, expect, it, vi } from "vitest";

import {
  ConversationDeltaBuffer,
  type ConversationDeltaEvent,
} from "./conversation-delta-buffer";

function delta(value: string): ConversationDeltaEvent {
  return {
    type: "assistant_item_delta",
    response_id: "60000000-0000-4000-8000-000000000001",
    item_id: "assistant:1",
    delta: value,
  };
}

describe("ConversationDeltaBuffer", () => {
  it("commits ordered deltas once per animation frame", () => {
    let scheduled: FrameRequestCallback | undefined;
    const onFlush = vi.fn();
    const request = vi.fn((callback: FrameRequestCallback) => {
      scheduled = callback;
      return 7;
    });
    const buffer = new ConversationDeltaBuffer(onFlush, {
      cancel: vi.fn(),
      request,
    });

    buffer.push(delta("流"));
    buffer.push(delta("式"));

    expect(request).toHaveBeenCalledTimes(1);
    expect(onFlush).not.toHaveBeenCalled();
    scheduled?.(16);
    expect(onFlush).toHaveBeenCalledWith([delta("流"), delta("式")]);
  });

  it("flushes before a non-delta event and cancels the pending frame", () => {
    const onFlush = vi.fn();
    const cancel = vi.fn();
    const buffer = new ConversationDeltaBuffer(onFlush, {
      cancel,
      request: () => 11,
    });

    buffer.push(delta("answer"));
    buffer.flush();

    expect(cancel).toHaveBeenCalledWith(11);
    expect(onFlush).toHaveBeenCalledWith([delta("answer")]);
  });

  it("drops queued deltas when a stream is superseded", () => {
    const onFlush = vi.fn();
    const buffer = new ConversationDeltaBuffer(onFlush, {
      cancel: vi.fn(),
      request: () => 13,
    });

    buffer.push(delta("stale"));
    buffer.discard();
    buffer.flush();

    expect(onFlush).not.toHaveBeenCalled();
  });
});
