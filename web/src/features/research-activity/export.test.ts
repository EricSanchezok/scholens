import { describe, expect, it, vi } from "vitest";

import { collectReadingActivityCsv } from "./export";

describe("collectReadingActivityCsv", () => {
  it("combines cursor pages and requests the header only once", async () => {
    const loadPage = vi
      .fn()
      .mockResolvedValueOnce({
        blob: new Blob(["session_id,active_ms\nfirst,5000\n"]),
        nextCursor: "cursor-1",
      })
      .mockResolvedValueOnce({
        blob: new Blob(["second,3000\n"]),
        nextCursor: null,
      });

    const result = await collectReadingActivityCsv(loadPage);

    expect(loadPage).toHaveBeenNthCalledWith(1, {
      cursor: undefined,
      includeHeader: true,
    });
    expect(loadPage).toHaveBeenNthCalledWith(2, {
      cursor: "cursor-1",
      includeHeader: false,
    });
    expect(await result.text()).toBe(
      "session_id,active_ms\nfirst,5000\nsecond,3000\n",
    );
  });

  it("preserves the first page when an empty export contains only a header", async () => {
    const result = await collectReadingActivityCsv(async () => ({
      blob: new Blob(["session_id,active_ms\n"]),
      nextCursor: null,
    }));

    expect(await result.text()).toBe("session_id,active_ms\n");
  });

  it("rejects a repeated cursor instead of looping forever", async () => {
    const loadPage = vi.fn().mockResolvedValue({
      blob: new Blob(["row\n"]),
      nextCursor: "repeated",
    });

    await expect(collectReadingActivityCsv(loadPage)).rejects.toThrow(
      "repeated cursor",
    );
    expect(loadPage).toHaveBeenCalledTimes(2);
  });
});
