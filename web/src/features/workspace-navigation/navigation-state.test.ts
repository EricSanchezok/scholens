import { beforeEach, describe, expect, it } from "vitest";

import {
  MAX_NAVIGATION_CONTEXTS,
  clearNavigationSession,
  readNavigationContext,
  readWorkspaceDestination,
  rememberWorkspaceDestination,
  saveNavigationContext,
  withNavigationToken,
  withoutNavigationToken,
  workspaceDestinationForPath,
  type NavigationContextV1,
} from "./navigation-state";

function context(
  token: string,
  actorId = 7,
  origin = "/library?q=causal",
): NavigationContextV1 {
  return {
    actorId,
    createdAt: Number(token.replace(/\D/g, "")) || 0,
    destination: "/reader/document-1?page=4",
    focusKey: "document-1",
    origin,
    originKind: "library",
    snapshots: { collection: { scrollTop: 480 } },
    token,
    version: 1,
  };
}

describe("workspace navigation state", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    clearNavigationSession(7);
    clearNavigationSession(8);
  });

  it("adds and removes an opaque navigation token without losing URL state", () => {
    const contextual = withNavigationToken(
      "/reader/document-1?project=project-1&page=4#selection",
      "token-1",
    );
    expect(contextual).toBe(
      "/reader/document-1?project=project-1&page=4&nav=token-1#selection",
    );
    expect(withoutNavigationToken(contextual)).toBe(
      "/reader/document-1?project=project-1&page=4#selection",
    );
  });

  it("keeps navigation contexts actor-scoped and bounded", () => {
    for (let index = 0; index < MAX_NAVIGATION_CONTEXTS + 2; index += 1) {
      saveNavigationContext(context(`token-${index}`));
    }
    saveNavigationContext(context("actor-8", 8));

    expect(readNavigationContext(7, "token-0")).toBeUndefined();
    expect(readNavigationContext(7, "token-2")).toBeDefined();
    expect(readNavigationContext(7, "actor-8")).toBeUndefined();
    expect(readNavigationContext(8, "actor-8")?.actorId).toBe(8);
  });

  it("remembers only safe internal primary-destination URLs per actor", () => {
    rememberWorkspaceDestination(7, "library", "/library?q=graph&tag=one");
    rememberWorkspaceDestination(7, "projects", "https://example.com");

    expect(readWorkspaceDestination(7, "library", "/library")).toBe(
      "/library?q=graph&tag=one",
    );
    expect(readWorkspaceDestination(7, "projects", "/projects")).toBe(
      "/projects",
    );
    expect(readWorkspaceDestination(8, "library", "/library")).toBe("/library");
  });

  it("recognizes only restorable Workspace roots", () => {
    expect(workspaceDestinationForPath("/library")).toBe("library");
    expect(workspaceDestinationForPath("/projects")).toBe("projects");
    expect(workspaceDestinationForPath("/me")).toBe("me");
    expect(workspaceDestinationForPath("/reader/document-1")).toBeUndefined();
  });
});
