import { describe, expect, it } from "vitest";

import { parseServerSentEventBlock } from "./server-sent-events";

describe("server-sent event parsing", () => {
  it("preserves event names and joins multiline data", () => {
    expect(
      parseServerSentEventBlock(
        ': keep-alive\nid: 42-0\nevent: delta\ndata: {"text":\ndata: "hello"}',
      ),
    ).toEqual({ event: "delta", id: "42-0", data: '{"text":\n"hello"}' });
  });

  it("ignores comments without payload data", () => {
    expect(parseServerSentEventBlock(": keep-alive")).toBeUndefined();
  });
});
