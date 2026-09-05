import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";

import { PaperSearchForm, usePaperSearchDraft } from "./paper-search-form";

function ControlledForm({
  initialCommittedQuery = "",
  onCommit = vi.fn(),
}: {
  initialCommittedQuery?: string;
  onCommit?: (query: string) => void;
}) {
  const [committedQuery, setCommittedQuery] = React.useState(
    initialCommittedQuery,
  );
  const [draft, setDraft] = React.useState(initialCommittedQuery);
  return (
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <PaperSearchForm
        committedQuery={committedQuery}
        draft={draft}
        label="Search papers"
        onCommit={(query) => {
          onCommit(query);
          setCommittedQuery(query);
        }}
        onDraftChange={setDraft}
      />
    </NextIntlClientProvider>
  );
}

function DraftSynchronizationHarness() {
  const [committedQuery, setCommittedQuery] = React.useState("memory");
  const [filter, setFilter] = React.useState("all");
  const [draft, setDraft] = usePaperSearchDraft(
    committedQuery,
    "library-papers",
  );
  return (
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <PaperSearchForm
        committedQuery={committedQuery}
        draft={draft}
        label="Search papers"
        onCommit={setCommittedQuery}
        onDraftChange={setDraft}
      />
      <p>{filter}</p>
      <button onClick={() => setFilter("reading")} type="button">
        Filter reading
      </button>
      <button onClick={() => setCommittedQuery("external")} type="button">
        Change URL query
      </button>
      <button onClick={() => setCommittedQuery("memory")} type="button">
        Restore URL query
      </button>
    </NextIntlClientProvider>
  );
}

describe("PaperSearchForm", () => {
  it("keeps a draft local until Enter submits its trimmed value", async () => {
    const onCommit = vi.fn();
    const user = userEvent.setup();
    render(<ControlledForm onCommit={onCommit} />);
    const input = screen.getByRole("searchbox", { name: "Search papers" });

    await user.type(input, "  code world  ");
    expect(input).toHaveValue("  code world  ");
    expect(onCommit).not.toHaveBeenCalled();

    await user.keyboard("{Enter}");
    expect(onCommit).toHaveBeenCalledOnce();
    expect(onCommit).toHaveBeenCalledWith("code world");
    expect(input).toHaveValue("code world");
    expect(input).toHaveFocus();
  });

  it("keeps a cleared draft local until Enter commits it", async () => {
    const onCommit = vi.fn();
    const user = userEvent.setup();
    render(
      <ControlledForm initialCommittedQuery="memory" onCommit={onCommit} />,
    );
    const input = screen.getByRole("searchbox", { name: "Search papers" });

    await user.clear(input);
    expect(onCommit).not.toHaveBeenCalled();

    await user.keyboard("{Enter}");
    expect(onCommit).toHaveBeenCalledWith("");
  });

  it("describes a one-character query error without committing it", async () => {
    const onCommit = vi.fn();
    const user = userEvent.setup();
    render(<ControlledForm onCommit={onCommit} />);
    const input = screen.getByRole("searchbox", { name: "Search papers" });

    await user.type(input, "a{Enter}");
    expect(onCommit).not.toHaveBeenCalled();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(
      "Enter at least 2 characters, or clear the field to show all papers.",
    );

    await user.clear(input);
    await user.type(input, "😀{Enter}");
    expect(onCommit).not.toHaveBeenCalled();
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("does not submit while an IME composition is active", () => {
    const onCommit = vi.fn();
    render(<ControlledForm onCommit={onCommit} />);
    const input = screen.getByRole("searchbox", { name: "Search papers" });
    const form = input.closest("form");

    fireEvent.compositionStart(input, { data: "世" });
    fireEvent.change(input, { target: { value: "世界" } });
    fireEvent.submit(form!);
    expect(onCommit).not.toHaveBeenCalled();

    fireEvent.compositionEnd(input, { data: "世界" });
    fireEvent.submit(form!);
    expect(onCommit).toHaveBeenCalledWith("世界");
  });

  it("preserves a dirty draft across filters and syncs a changed URL query", async () => {
    const user = userEvent.setup();
    render(<DraftSynchronizationHarness />);
    const input = screen.getByRole("searchbox", { name: "Search papers" });

    await user.clear(input);
    await user.type(input, "unfinished draft");
    await user.click(screen.getByRole("button", { name: "Filter reading" }));
    expect(input).toHaveValue("unfinished draft");

    await user.click(screen.getByRole("button", { name: "Change URL query" }));
    expect(input).toHaveValue("external");

    await user.click(screen.getByRole("button", { name: "Restore URL query" }));
    expect(input).toHaveValue("memory");
  });
});
