import type { ConversationStreamEvent } from "./api/conversations";

export type ConversationDeltaEvent = Extract<
  ConversationStreamEvent,
  { type: "assistant_item_delta" | "assistant_candidate_delta" }
>;

type AnimationFrameScheduler = {
  cancel: (frame: number) => void;
  request: (callback: FrameRequestCallback) => number;
};

export class ConversationDeltaBuffer {
  private events: ConversationDeltaEvent[] = [];
  private frame: number | undefined;

  constructor(
    private readonly onFlush: (events: ConversationDeltaEvent[]) => void,
    private readonly scheduler: AnimationFrameScheduler = {
      cancel: (frame) => window.cancelAnimationFrame(frame),
      request: (callback) => window.requestAnimationFrame(callback),
    },
  ) {}

  push(event: ConversationDeltaEvent) {
    this.events.push(event);
    if (this.frame !== undefined) return;
    this.frame = this.scheduler.request(() => {
      this.frame = undefined;
      this.release();
    });
  }

  flush() {
    if (this.frame !== undefined) {
      this.scheduler.cancel(this.frame);
      this.frame = undefined;
    }
    this.release();
  }

  discard() {
    if (this.frame !== undefined) {
      this.scheduler.cancel(this.frame);
      this.frame = undefined;
    }
    this.events = [];
  }

  private release() {
    if (this.events.length === 0) return;
    const events = this.events;
    this.events = [];
    this.onFlush(events);
  }
}
