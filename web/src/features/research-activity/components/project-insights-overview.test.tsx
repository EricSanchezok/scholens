import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { projectActivityFixture, projectInsightsFixture } from "../fixtures";
import { ProjectInsightsOverview } from "./project-insights-overview";

describe("ProjectInsightsOverview", () => {
  it.each(["loading", "error"] as const)(
    "keeps project identity, range, and toolbar controls stable while %s",
    (state) => {
      render(
        <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
          <ProjectInsightsOverview
            activity={[]}
            error={state === "error"}
            loading={state === "loading"}
            onRangeChange={vi.fn()}
            onRetry={vi.fn()}
            projectId="50000000-0000-4000-8000-000000000001"
            range="90d"
            toolbar={<button type="button">Activity settings</button>}
          />
        </NextIntlClientProvider>,
      );

      expect(
        screen.getByRole("heading", { name: "Research progress" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("group", { name: "Activity range" }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "90 days" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(
        screen.getByRole("button", { name: "Activity settings" }),
      ).toBeInTheDocument();
    },
  );

  it("shows selected-period last activity and preserves an honest null state", () => {
    const firstPaper = projectInsightsFixture.papers[0];
    const paperWithoutActivity = projectInsightsFixture.papers[3];
    if (!firstPaper || !paperWithoutActivity) {
      throw new Error("Project fixture needs activity and null-state papers");
    }
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <ProjectInsightsOverview
          activity={projectActivityFixture.slice(0, 2)}
          insights={{
            ...projectInsightsFixture,
            daily: [],
            mine: [],
            papers: [firstPaper, paperWithoutActivity],
            papersTotalCount: 150,
            team: [],
          }}
          onRangeChange={vi.fn()}
          onRetry={vi.fn()}
          projectId="50000000-0000-4000-8000-000000000001"
          range="30d"
        />
      </NextIntlClientProvider>,
    );

    expect(
      screen.getByRole("columnheader", { name: "Last activity" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Page coverage appears in All time only/),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Aug 20, 2026").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText("No activity in this period").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", {
        name: "Generative Agents: Interactive Simulacra of Human Behavior",
      }),
    ).toHaveAttribute(
      "href",
      "/reader/10000000-0000-4000-8000-000000000001?project=50000000-0000-4000-8000-000000000001&panel=insights",
    );
    expect(screen.getByText("Added a shared annotation")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Created a shared output" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Showing 2 of 150 project papers."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "View all project papers" }),
    ).toHaveAttribute(
      "href",
      "/projects/50000000-0000-4000-8000-000000000001?view=papers",
    );
  });
});
