import { describe, expect, it } from "vitest";

import { readerQueries } from "./queries";

describe("Reader query policy", () => {
  it("revalidates Project membership whenever Reader mounts", () => {
    const query = readerQueries.projects("document-1", "project-1");

    expect(query.queryKey).toEqual([
      "reader",
      "projects",
      "document-1",
      "project-1",
    ]);
    expect(query.refetchOnMount).toBe("always");
  });
});
