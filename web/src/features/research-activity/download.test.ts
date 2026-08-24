import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadResearchActivityExport } from "./download";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("downloadResearchActivityExport", () => {
  it("clicks an attached anchor and revokes the URL on a later task", () => {
    vi.useFakeTimers();
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:research-activity");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL");
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function clickAttachedAnchor(
        this: HTMLAnchorElement,
      ) {
        expect(this.isConnected).toBe(true);
      });

    downloadResearchActivityExport(new Blob(["date,active_ms\n"]));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(
      document.querySelector('a[download="scholens-reading-activity.csv"]'),
    ).toBeNull();
    expect(revokeObjectURL).not.toHaveBeenCalled();

    vi.runOnlyPendingTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:research-activity");
  });
});
