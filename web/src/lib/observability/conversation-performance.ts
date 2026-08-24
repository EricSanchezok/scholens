import { reportConversationPerformance } from "./web-performance";

export type ConversationStreamKind = "direct" | "resume";

type ConversationPerformanceReporter = typeof reportConversationPerformance;

export type ConversationPerformanceTracker = {
  markAccepted: (streamKind: ConversationStreamKind) => void;
  markContentVisible: () => void;
  markEvent: () => void;
  markFeedback: () => void;
  markReady: () => void;
  markTerminal: () => void;
};

export function createConversationPerformanceTracker(
  now: () => number = () => performance.now(),
  report: ConversationPerformanceReporter = reportConversationPerformance,
): ConversationPerformanceTracker {
  const startedAt = now();
  let acceptedAt: number | undefined;
  let firstContentReported = false;
  let firstEventReported = false;
  let feedbackReported = false;
  let lastEventAt: number | undefined;
  let maxStall = 0;
  let readyReported = false;
  let terminalReported = false;
  let streamKind: ConversationStreamKind | undefined;

  const elapsed = (timestamp: number) => Math.max(0, timestamp - startedAt);

  return {
    markAccepted(kind) {
      if (acceptedAt !== undefined) return;
      acceptedAt = now();
      lastEventAt = acceptedAt;
      streamKind = kind;
      report("conversation_accepted", elapsed(acceptedAt), streamKind);
    },
    markContentVisible() {
      if (firstContentReported) return;
      firstContentReported = true;
      const timestamp = now();
      report("conversation_first_content", elapsed(timestamp), streamKind);
    },
    markEvent() {
      const timestamp = now();
      if (lastEventAt !== undefined) {
        maxStall = Math.max(maxStall, timestamp - lastEventAt);
      }
      lastEventAt = timestamp;
      if (!firstEventReported) {
        firstEventReported = true;
        report("conversation_first_event", elapsed(timestamp), streamKind);
      }
    },
    markFeedback() {
      if (feedbackReported) return;
      feedbackReported = true;
      report("conversation_feedback", elapsed(now()), streamKind);
    },
    markReady() {
      if (readyReported) return;
      readyReported = true;
      const timestamp = now();
      report("conversation_ready", elapsed(timestamp), streamKind);
    },
    markTerminal() {
      if (terminalReported) return;
      terminalReported = true;
      const timestamp = now();
      if (lastEventAt !== undefined) {
        maxStall = Math.max(maxStall, timestamp - lastEventAt);
      }
      report("conversation_max_stall", Math.max(0, maxStall), streamKind);
    },
  };
}
