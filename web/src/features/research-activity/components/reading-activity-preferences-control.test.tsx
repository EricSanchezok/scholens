import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { ReadingActivityPreferencesControl } from "./reading-activity-preferences-control";

function renderControl({
  pending = false,
  saved = false,
  recordingEnabled = false,
  contributeAnonymousProjectAggregates = true,
} = {}) {
  const onChange = vi.fn();
  render(
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <ReadingActivityPreferencesControl
        onChange={onChange}
        pending={pending}
        saved={saved}
        value={{
          contributeAnonymousProjectAggregates,
          recordingEnabled,
        }}
      />
    </NextIntlClientProvider>,
  );
  return onChange;
}

describe("ReadingActivityPreferencesControl", () => {
  it("keeps anonymous Project contribution independently controllable", () => {
    const onChange = renderControl();
    const aggregateSwitch = screen.getByRole("switch", {
      name: "Contribute anonymous Project reading",
    });

    expect(aggregateSwitch).toBeEnabled();
    expect(aggregateSwitch).toBeChecked();
    expect(aggregateSwitch).toHaveAttribute(
      "aria-describedby",
      "reading-activity-project-description",
    );
    expect(
      screen.getByRole("switch", { name: "Record my reading activity" }),
    ).toHaveAttribute(
      "aria-describedby",
      "reading-activity-recording-description",
    );
    fireEvent.click(aggregateSwitch);
    expect(onChange).toHaveBeenCalledWith({
      contributeAnonymousProjectAggregates: false,
      recordingEnabled: false,
    });
    expect(
      screen.getByText(
        /earlier anonymous contributions remain until you delete that Project's reading contribution/i,
      ),
    ).toBeInTheDocument();
  });

  it("disables both controls only while a preference save is pending", () => {
    renderControl({ pending: true });
    for (const control of screen.getAllByRole("switch")) {
      expect(control).toBeDisabled();
    }
  });

  it("announces a confirmed server save", () => {
    renderControl({ saved: true });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Reading activity preferences saved.",
    );
  });
});
