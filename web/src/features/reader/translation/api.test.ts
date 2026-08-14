import { describe, expect, it } from "vitest";

import { parseSelectionTranslationEvent } from "./api";

describe("selection translation SSE parsing", () => {
  it("parses start, delta, and completion events", () => {
    expect(
      parseSelectionTranslationEvent({
        event: "start",
        data: '{"target_language":"zh-CN","cache_hit":false}',
      }),
    ).toEqual({
      type: "start",
      targetLanguage: "zh-CN",
      cacheHit: false,
    });
    expect(
      parseSelectionTranslationEvent({
        event: "delta",
        data: '{"text":"译文"}',
      }),
    ).toEqual({ type: "delta", text: "译文" });
    expect(
      parseSelectionTranslationEvent({
        event: "complete",
        data: '{"cache_hit":true}',
      }),
    ).toEqual({ type: "complete", cacheHit: true });
  });

  it("preserves stable application error details", () => {
    expect(
      parseSelectionTranslationEvent({
        event: "error",
        data: '{"code":"token_quota_exceeded","message":"exhausted","retryable":false}',
      }),
    ).toEqual({
      type: "error",
      code: "token_quota_exceeded",
      message: "exhausted",
      retryable: false,
    });
  });

  it("rejects malformed and unknown events", () => {
    expect(() =>
      parseSelectionTranslationEvent({ event: "delta", data: "{}" }),
    ).toThrow("Translation stream event was malformed");
    expect(() =>
      parseSelectionTranslationEvent({ event: "legacy", data: "{}" }),
    ).toThrow("Translation stream event was malformed");
  });
});
