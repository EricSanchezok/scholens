import { describe, expect, it } from "vitest";

import { parseLibrarySearch, serializeLibrarySearch } from "./library-search";

describe("Library URL state", () => {
  it("uses the canonical Papers defaults for unknown values", () => {
    expect(
      parseLibrarySearch(
        new URLSearchParams("tab=unknown&sort=random&tag=&cursor="),
      ),
    ).toEqual({
      cursor: undefined,
      kinds: [],
      query: "",
      sort: "added_desc",
      statuses: [],
      tab: "papers",
      tagIds: [],
    });
  });

  it("round-trips repeated Papers filters and cursor state", () => {
    const state = parseLibrarySearch(
      new URLSearchParams(
        "q=reasoning&sort=last_accessed_desc&status=reading&status=completed&tag=one&tag=two&cursor=opaque",
      ),
    );
    expect(state).toMatchObject({
      cursor: "opaque",
      query: "reasoning",
      sort: "last_accessed_desc",
      statuses: ["reading", "completed"],
      tagIds: ["one", "two"],
    });
    expect(serializeLibrarySearch(state).toString()).toBe(
      "q=reasoning&sort=last_accessed_desc&tag=one&tag=two&status=reading&status=completed&cursor=opaque",
    );
  });

  it("keeps Outputs kinds and sort separate from Papers state", () => {
    const state = parseLibrarySearch(
      new URLSearchParams(
        "tab=outputs&kind=citation&kind=data_table&kind=report&sort=title_desc",
      ),
    );
    expect(state).toMatchObject({
      kinds: ["citation", "data_table"],
      sort: "title_desc",
      tab: "outputs",
    });
    expect(serializeLibrarySearch(state).toString()).toBe(
      "tab=outputs&sort=title_desc&kind=citation&kind=data_table",
    );
  });
});
