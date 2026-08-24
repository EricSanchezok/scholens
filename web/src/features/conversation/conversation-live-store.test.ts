import { describe, expect, it, vi } from "vitest";

import {
  ConversationLiveStore,
  type ConversationLiveScheduler,
} from "./conversation-live-store";
import { createLiveTurn } from "./conversation-state";

const responseId = "60000000-0000-4000-8000-000000000001";
const turnId = "50000000-0000-4000-8000-000000000001";
const itemId = "assistant:turn-1:answer";

function createScheduler() {
  let now = 0;
  let hidden = false;
  let handle = 0;
  const timeouts = new Map<number, () => void>();
  const frames = new Map<number, FrameRequestCallback>();
  const scheduler: ConversationLiveScheduler = {
    cancelAnimationFrame: (id) => frames.delete(id),
    clearTimeout: (id) => timeouts.delete(id),
    hidden: () => hidden,
    now: () => now,
    requestAnimationFrame: (callback) => {
      const id = ++handle;
      frames.set(id, callback);
      return id;
    },
    setTimeout: (callback) => {
      const id = ++handle;
      timeouts.set(id, callback);
      return id;
    },
  };
  return {
    scheduler,
    setHidden(value: boolean) {
      hidden = value;
    },
    runFrame() {
      const pending = [...frames.values()];
      frames.clear();
      pending.forEach((callback) => callback(now));
    },
    runTimer(elapsedMs = 50) {
      now += elapsedMs;
      const pending = [...timeouts.values()];
      timeouts.clear();
      pending.forEach((callback) => callback());
    },
  };
}

function candidateStart() {
  return {
    type: "assistant_candidate_start" as const,
    response_id: responseId,
    item_id: itemId,
    sequence: 1,
  };
}

function candidateDelta(delta: string) {
  return {
    type: "assistant_candidate_delta" as const,
    response_id: responseId,
    item_id: itemId,
    delta,
  };
}

describe("ConversationLiveStore", () => {
  it("coalesces 500 deltas into one foreground publication", () => {
    const clock = createScheduler();
    const store = new ConversationLiveStore(
      createLiveTurn(turnId, responseId, "Question"),
      clock.scheduler,
    );
    store.dispatch(candidateStart());
    const listener = vi.fn();
    store.subscribeContent(listener);

    for (let index = 0; index < 500; index += 1) {
      store.dispatch(candidateDelta("x"));
    }

    expect(listener).not.toHaveBeenCalled();
    expect(store.getSnapshot()?.answerCandidate?.content).toBe("");
    clock.runTimer();
    expect(listener).not.toHaveBeenCalled();
    clock.runFrame();

    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot()?.answerCandidate?.content).toHaveLength(500);
  });

  it("never exposes the target before its scheduled publication", () => {
    const clock = createScheduler();
    const store = new ConversationLiveStore(
      createLiveTurn(turnId, responseId, "Question"),
      clock.scheduler,
    );
    store.dispatch(candidateStart());
    const published = store.getSnapshot();

    store.dispatch(candidateDelta("private target"));

    expect(store.getSnapshot()).toBe(published);
    expect(store.getSnapshot()?.answerCandidate?.content).toBe("");
  });

  it("flushes pending content and publishes a terminal event immediately", () => {
    const clock = createScheduler();
    const store = new ConversationLiveStore(
      createLiveTurn(turnId, responseId, "Question"),
      clock.scheduler,
    );
    store.dispatch(candidateStart());
    const listener = vi.fn();
    store.subscribeContent(listener);
    store.dispatch(candidateDelta("partial"));

    store.dispatch({
      type: "cancelled",
      response_id: responseId,
      turn_id: turnId,
    });

    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot()?.phase).toBe("cancelled");
    clock.runTimer();
    clock.runFrame();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("discards a scheduled publication without notifying subscribers", () => {
    const clock = createScheduler();
    const store = new ConversationLiveStore(
      createLiveTurn(turnId, responseId, "Question"),
      clock.scheduler,
    );
    store.dispatch(candidateStart());
    const listener = vi.fn();
    store.subscribeContent(listener);
    store.dispatch(candidateDelta("must not publish"));
    clock.runTimer();

    store.discardPending();
    clock.runFrame();

    expect(listener).not.toHaveBeenCalled();
    expect(store.getSnapshot()?.answerCandidate?.content).toBe("");
  });

  it("keeps metadata and worklog subscribers out of steady answer deltas", () => {
    const clock = createScheduler();
    const store = new ConversationLiveStore(
      createLiveTurn(turnId, responseId, "Question"),
      clock.scheduler,
    );
    store.dispatch(candidateStart());
    store.dispatch(candidateDelta("first"));
    clock.runTimer();
    clock.runFrame();

    const metadata = vi.fn();
    const content = vi.fn();
    const worklog = vi.fn();
    store.subscribeMetadata(metadata);
    store.subscribeContent(content);
    store.subscribeWorklog(worklog);

    store.dispatch(candidateDelta(" second"));
    clock.runTimer();
    clock.runFrame();

    expect(content).toHaveBeenCalledTimes(1);
    expect(metadata).not.toHaveBeenCalled();
    expect(worklog).not.toHaveBeenCalled();
  });

  it("uses a lower publication cadence while the document is hidden", () => {
    const clock = createScheduler();
    clock.setHidden(true);
    const store = new ConversationLiveStore(
      createLiveTurn(turnId, responseId, "Question"),
      clock.scheduler,
    );
    store.dispatch(candidateStart());
    const listener = vi.fn();
    store.subscribeContent(listener);
    store.dispatch(candidateDelta("background"));

    clock.runTimer(250);

    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot()?.answerCandidate?.content).toBe("background");
  });

  it("moves a pending animation-frame publish to a background timer", () => {
    const clock = createScheduler();
    const store = new ConversationLiveStore(
      createLiveTurn(turnId, responseId, "Question"),
      clock.scheduler,
    );
    store.dispatch(candidateStart());
    const listener = vi.fn();
    store.subscribeContent(listener);
    store.dispatch(candidateDelta("before"));
    clock.runTimer();

    clock.setHidden(true);
    store.dispatch(candidateDelta(" hidden"));
    clock.runFrame();
    expect(listener).not.toHaveBeenCalled();

    clock.runTimer(250);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot()?.answerCandidate?.content).toBe("before hidden");
  });
});
