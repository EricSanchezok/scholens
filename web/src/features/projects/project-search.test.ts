import { describe, expect, it } from "vitest";

import {
  parseProjectDetailSearch,
  parseProjectsSearch,
  serializeProjectDetailSearch,
  serializeProjectsSearch,
} from "./project-search";

describe("Projects URL state", () => {
  it("normalizes invalid list state", () => {
    expect(
      parseProjectsSearch(new URLSearchParams("q=%20truth%20&sort=nope")),
    ).toEqual({
      cursor: undefined,
      query: "truth",
      sort: "activity_desc",
    });
  });

  it("round-trips list filters", () => {
    const state = {
      cursor: "next",
      query: "rag",
      sort: "papers_desc",
    } as const;
    expect(parseProjectsSearch(serializeProjectsSearch(state))).toEqual(state);
  });

  it("keeps detail collections independently addressable", () => {
    const state = parseProjectDetailSearch(
      new URLSearchParams(
        "view=outputs&conversation=c1&panel=chat&paper_q=attention&paper_sort=title_asc&paper_cursor=p1&output_q=citation&output_kind=citation&output_kind=data_table&output_sort=title_asc&output_cursor=o1",
      ),
    );
    expect(
      parseProjectDetailSearch(serializeProjectDetailSearch(state)),
    ).toEqual(state);
  });

  it("keeps a selected conversation when the chat panel is collapsed", () => {
    const state = parseProjectDetailSearch(
      new URLSearchParams("conversation=c1"),
    );
    expect(state.panel).toBeUndefined();
    expect(state.conversation).toBe("c1");
    const serialized = serializeProjectDetailSearch(state).toString();
    expect(serialized).toContain("conversation=c1");
    expect(serialized).not.toContain("panel=chat");
  });
});
