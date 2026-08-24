import type { ConversationStreamEvent } from "./api/conversations";
import {
  reduceLiveTurn,
  reduceLiveTurnEvents,
  type ConversationConnectionState,
  type ConversationFailure,
  type ConversationTraceEntry,
  type LiveTurn,
  type ProvisionalAssistantItem,
} from "./conversation-state";

type Listener = () => void;
type TimerHandle = number;

export type ConversationLiveMetadata = Pick<
  LiveTurn,
  | "connectionState"
  | "depth"
  | "durationMs"
  | "failure"
  | "generationKind"
  | "phase"
  | "readyTurn"
  | "references"
  | "responseId"
  | "startedAtMs"
  | "stopFailure"
  | "suggestions"
  | "trace"
  | "turnId"
  | "userMessage"
  | "variantIndex"
>;

export type ConversationLiveContent = {
  answerCandidate: ProvisionalAssistantItem | null;
  content: string;
  phase: LiveTurn["phase"];
  references: Record<string, unknown> | null;
};

export type ConversationLiveWorklog = {
  connectionState: ConversationConnectionState;
  durationMs: number | null;
  entries: ConversationTraceEntry[];
  failure: ConversationFailure | null;
  phase: LiveTurn["phase"];
  provisionalItems: ProvisionalAssistantItem[];
  startedAtMs: number;
  stopFailure: boolean;
};

export type ConversationLiveScheduler = {
  cancelAnimationFrame: (handle: number) => void;
  clearTimeout: (handle: TimerHandle) => void;
  hidden: () => boolean;
  now: () => number;
  requestAnimationFrame: (callback: FrameRequestCallback) => number;
  setTimeout: (callback: () => void, delayMs: number) => TimerHandle;
};

const foregroundPublishIntervalMs = 50;
const backgroundPublishIntervalMs = 250;

const browserScheduler: ConversationLiveScheduler = {
  cancelAnimationFrame: (handle) => window.cancelAnimationFrame(handle),
  clearTimeout: (handle) => window.clearTimeout(handle),
  hidden: () => document.visibilityState === "hidden",
  now: () => performance.now(),
  requestAnimationFrame: (callback) => window.requestAnimationFrame(callback),
  setTimeout: (callback, delayMs) => window.setTimeout(callback, delayMs),
};

function metadataFrom(turn: LiveTurn | null): ConversationLiveMetadata | null {
  if (!turn) return null;
  return {
    connectionState: turn.connectionState,
    depth: turn.depth,
    durationMs: turn.durationMs,
    failure: turn.failure,
    generationKind: turn.generationKind,
    phase: turn.phase,
    readyTurn: turn.readyTurn,
    references: turn.references,
    responseId: turn.responseId,
    startedAtMs: turn.startedAtMs,
    stopFailure: turn.stopFailure,
    suggestions: turn.suggestions,
    trace: turn.trace,
    turnId: turn.turnId,
    userMessage: turn.userMessage,
    variantIndex: turn.variantIndex,
  };
}

function contentFrom(turn: LiveTurn | null): ConversationLiveContent | null {
  if (!turn) return null;
  return {
    answerCandidate: turn.answerCandidate,
    content: turn.content,
    phase: turn.phase,
    references: turn.references,
  };
}

function worklogFrom(turn: LiveTurn | null): ConversationLiveWorklog | null {
  if (!turn) return null;
  return {
    connectionState: turn.connectionState,
    durationMs: turn.durationMs,
    entries: turn.entries,
    failure: turn.failure,
    phase: turn.phase,
    provisionalItems: turn.provisionalItems,
    startedAtMs: turn.startedAtMs,
    stopFailure: turn.stopFailure,
  };
}

function shallowEqualRecord<T extends object>(left: T | null, right: T | null) {
  if (left === right) return true;
  if (!left || !right) return false;
  const keys = Object.keys(left) as Array<keyof T>;
  return (
    keys.length === Object.keys(right).length &&
    keys.every((key) => Object.is(left[key], right[key]))
  );
}

type DeltaEvent = Extract<
  ConversationStreamEvent,
  { type: "assistant_candidate_delta" | "assistant_item_delta" }
>;

function isDeltaEvent(event: ConversationStreamEvent): event is DeltaEvent {
  return (
    event.type === "assistant_candidate_delta" ||
    event.type === "assistant_item_delta"
  );
}

function mergeDelta(left: DeltaEvent, right: DeltaEvent): DeltaEvent | null {
  if (
    left.type !== right.type ||
    left.item_id !== right.item_id ||
    left.response_id !== right.response_id
  ) {
    return null;
  }
  return { ...left, delta: left.delta + right.delta } as DeltaEvent;
}

/**
 * Feature-private external store for the one active response. Incoming deltas
 * update an unpublished target; React can only observe the cadence-controlled
 * published snapshot. Separate projections keep transcript and Reader parents
 * out of the token-render path.
 */
export class ConversationLiveStore {
  private target: LiveTurn | null;
  private published: LiveTurn | null;
  private metadata: ConversationLiveMetadata | null;
  private content: ConversationLiveContent | null;
  private worklog: ConversationLiveWorklog | null;
  private pendingDeltas: DeltaEvent[] = [];
  private readonly metadataListeners = new Set<Listener>();
  private readonly contentListeners = new Set<Listener>();
  private readonly worklogListeners = new Set<Listener>();
  private timeout: TimerHandle | undefined;
  private animationFrame: number | undefined;
  private lastPublishedAt: number;

  constructor(
    initial: LiveTurn | null = null,
    private readonly scheduler: ConversationLiveScheduler = browserScheduler,
  ) {
    this.target = initial;
    this.published = initial;
    this.metadata = metadataFrom(initial);
    this.content = contentFrom(initial);
    this.worklog = worklogFrom(initial);
    this.lastPublishedAt = scheduler.now();
  }

  readonly subscribeMetadata = (listener: Listener) => {
    this.metadataListeners.add(listener);
    return () => this.metadataListeners.delete(listener);
  };

  readonly subscribeContent = (listener: Listener) => {
    this.contentListeners.add(listener);
    return () => this.contentListeners.delete(listener);
  };

  readonly subscribeWorklog = (listener: Listener) => {
    this.worklogListeners.add(listener);
    return () => this.worklogListeners.delete(listener);
  };

  readonly getSnapshot = () => this.published;
  readonly getMetadataSnapshot = () => this.metadata;
  readonly getContentSnapshot = () => this.content;
  readonly getWorklogSnapshot = () => this.worklog;

  reset(next: LiveTurn | null) {
    this.cancelScheduledPublish();
    this.pendingDeltas = [];
    this.target = next;
    this.publish();
  }

  update(update: (current: LiveTurn | null) => LiveTurn | null) {
    this.applyPendingDeltas();
    this.target = update(this.target);
    this.publish();
  }

  dispatch(event: ConversationStreamEvent) {
    if (isDeltaEvent(event)) {
      const previous = this.pendingDeltas.at(-1);
      const merged = previous ? mergeDelta(previous, event) : null;
      if (merged) this.pendingDeltas[this.pendingDeltas.length - 1] = merged;
      else this.pendingDeltas.push(event);
      if (this.scheduler.hidden() && this.animationFrame !== undefined) {
        this.scheduler.cancelAnimationFrame(this.animationFrame);
        this.animationFrame = undefined;
      }
      this.schedulePublish();
      return;
    }
    this.cancelScheduledPublish();
    this.applyPendingDeltas();
    this.target = reduceLiveTurn(this.target, event);
    this.publish();
  }

  flush() {
    this.cancelScheduledPublish();
    this.applyPendingDeltas();
    this.publish();
  }

  discardPending() {
    this.cancelScheduledPublish();
    this.pendingDeltas = [];
  }

  private applyPendingDeltas() {
    if (this.pendingDeltas.length === 0) return;
    const deltas = this.pendingDeltas;
    this.pendingDeltas = [];
    this.target = reduceLiveTurnEvents(this.target, deltas);
  }

  private schedulePublish() {
    if (this.timeout !== undefined || this.animationFrame !== undefined) return;
    const interval = this.scheduler.hidden()
      ? backgroundPublishIntervalMs
      : foregroundPublishIntervalMs;
    const delay = Math.max(
      0,
      interval - (this.scheduler.now() - this.lastPublishedAt),
    );
    this.timeout = this.scheduler.setTimeout(() => {
      this.timeout = undefined;
      if (this.scheduler.hidden()) {
        this.applyPendingDeltas();
        this.publish();
        return;
      }
      this.animationFrame = this.scheduler.requestAnimationFrame(() => {
        this.animationFrame = undefined;
        this.applyPendingDeltas();
        this.publish();
      });
    }, delay);
  }

  private cancelScheduledPublish() {
    if (this.timeout !== undefined) {
      this.scheduler.clearTimeout(this.timeout);
      this.timeout = undefined;
    }
    if (this.animationFrame !== undefined) {
      this.scheduler.cancelAnimationFrame(this.animationFrame);
      this.animationFrame = undefined;
    }
  }

  private publish() {
    if (this.published === this.target) return;
    const nextMetadata = metadataFrom(this.target);
    const nextContent = contentFrom(this.target);
    const nextWorklog = worklogFrom(this.target);
    const metadataChanged = !shallowEqualRecord(this.metadata, nextMetadata);
    const contentChanged = !shallowEqualRecord(this.content, nextContent);
    const worklogChanged = !shallowEqualRecord(this.worklog, nextWorklog);

    this.published = this.target;
    this.metadata = metadataChanged ? nextMetadata : this.metadata;
    this.content = contentChanged ? nextContent : this.content;
    this.worklog = worklogChanged ? nextWorklog : this.worklog;
    this.lastPublishedAt = this.scheduler.now();

    if (metadataChanged)
      this.metadataListeners.forEach((listener) => listener());
    if (contentChanged) this.contentListeners.forEach((listener) => listener());
    if (worklogChanged) this.worklogListeners.forEach((listener) => listener());
  }
}
