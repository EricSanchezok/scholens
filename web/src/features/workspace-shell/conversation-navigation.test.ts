import { describe, expect, it } from "vitest";

import { withoutConversationSearchParam } from "./conversation-navigation";

describe("withoutConversationSearchParam", () => {
  it("removes only the active conversation from a workspace URL", () => {
    expect(
      withoutConversationSearchParam(
        "/reader/document-1",
        "panel=ask&project=project-1&conversation=conversation-1&page=4",
      ),
    ).toBe("/reader/document-1?panel=ask&project=project-1&page=4");
  });

  it("returns the pathname when conversation was the only parameter", () => {
    expect(
      withoutConversationSearchParam("/", "conversation=conversation-1"),
    ).toBe("/");
  });

  it("leaves unrelated URLs unchanged", () => {
    expect(withoutConversationSearchParam("/projects", "sort=updated")).toBe(
      "/projects?sort=updated",
    );
  });
});
