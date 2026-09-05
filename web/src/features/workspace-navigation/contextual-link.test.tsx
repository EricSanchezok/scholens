import { fireEvent, render, screen } from "@testing-library/react";
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({
  openContextualRoute: vi.fn(),
  updateContextRoute: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a {...props} href={String(href)} />
  ),
}));

vi.mock("./workspace-navigation-provider", () => ({
  useOptionalWorkspaceNavigation: () => navigation,
}));

import { ContextRouteLink, ContextualLink } from "./contextual-link";

describe("ContextualLink", () => {
  const preventTestNavigation = (event: Event) => event.preventDefault();

  beforeEach(() => {
    navigation.openContextualRoute.mockReset();
    navigation.updateContextRoute.mockReset();
    document.addEventListener("click", preventTestNavigation);
  });
  afterEach(() => document.removeEventListener("click", preventTestNavigation));

  it("keeps a canonical href and creates context only for a plain same-tab click", () => {
    const onPrimaryNavigate = vi.fn();
    render(
      <ContextualLink
        focusKey="document-1"
        href="/reader/document-1?project=project-1"
        onPrimaryNavigate={onPrimaryNavigate}
        originKind="library"
      >
        Open paper
      </ContextualLink>,
    );
    const link = screen.getByRole("link", { name: "Open paper" });

    expect(link).toHaveAttribute(
      "href",
      "/reader/document-1?project=project-1",
    );
    fireEvent.click(link, { metaKey: true });
    fireEvent.click(link, { button: 1 });
    expect(navigation.openContextualRoute).not.toHaveBeenCalled();
    expect(onPrimaryNavigate).not.toHaveBeenCalled();

    fireEvent.click(link);
    expect(onPrimaryNavigate).toHaveBeenCalledOnce();
    expect(navigation.openContextualRoute).toHaveBeenCalledOnce();
    expect(navigation.openContextualRoute).toHaveBeenCalledWith({
      destination: "/reader/document-1?project=project-1",
      focusKey: "document-1",
      originKind: "library",
    });
  });

  it("preserves context for same-tab route-state links", () => {
    render(
      <ContextRouteLink href="/projects/project-1?view=papers">
        View papers
      </ContextRouteLink>,
    );

    fireEvent.click(screen.getByRole("link", { name: "View papers" }));

    expect(navigation.updateContextRoute).toHaveBeenCalledWith(
      "/projects/project-1?view=papers",
      { history: "push" },
    );
  });
});
