import { expect, userEvent, waitFor } from "storybook/test";

export type FocusShadowPolicy = "stable" | "raised";

export type FocusVisualSnapshot = {
  backgroundColor: string;
  backgroundImage: string;
  borderColors: readonly string[];
  borderRadii: readonly string[];
  borderStyles: readonly string[];
  borderWidths: readonly string[];
  boxShadow: string;
  color: string;
  filter: string;
  height: number;
  opacity: string;
  outlineStyle: string;
  outlineWidth: string;
  scrollbarColor: string;
  transform: string;
  width: number;
};

type FocusCue = {
  element: HTMLElement;
  pseudo?: "::after" | "::before";
};

function visualStyle(element: Element, pseudo?: string) {
  return element.ownerDocument.defaultView!.getComputedStyle(element, pseudo);
}

export function readFocusVisual(
  element: HTMLElement,
  pseudo?: "::after" | "::before",
): FocusVisualSnapshot {
  const style = visualStyle(element, pseudo);
  return {
    backgroundColor: style.backgroundColor,
    backgroundImage: style.backgroundImage,
    borderColors: [
      style.borderTopColor,
      style.borderRightColor,
      style.borderBottomColor,
      style.borderLeftColor,
    ],
    borderRadii: [
      style.borderTopLeftRadius,
      style.borderTopRightRadius,
      style.borderBottomRightRadius,
      style.borderBottomLeftRadius,
    ],
    borderStyles: [
      style.borderTopStyle,
      style.borderRightStyle,
      style.borderBottomStyle,
      style.borderLeftStyle,
    ],
    borderWidths: [
      style.borderTopWidth,
      style.borderRightWidth,
      style.borderBottomWidth,
      style.borderLeftWidth,
    ],
    boxShadow: style.boxShadow,
    color: style.color,
    filter: style.filter,
    height: element.offsetHeight,
    opacity: style.opacity,
    outlineStyle: style.outlineStyle,
    outlineWidth: style.outlineWidth,
    scrollbarColor: style.scrollbarColor,
    transform: style.transform,
    width: element.offsetWidth,
  };
}

function nextAnimationFrame(element: HTMLElement) {
  return new Promise<void>((resolve) => {
    element.ownerDocument.defaultView!.requestAnimationFrame(() => resolve());
  });
}

/** Waits until theme initialization and semantic color transitions settle. */
export async function readSettledFocusVisual(
  element: HTMLElement,
  pseudo?: "::after" | "::before",
) {
  await nextAnimationFrame(element);
  await nextAnimationFrame(element);
  let previous = readFocusVisual(element, pseudo);
  let stableFrames = 0;
  await waitFor(
    async () => {
      await nextAnimationFrame(element);
      const current = readFocusVisual(element, pseudo);
      if (JSON.stringify(current) === JSON.stringify(previous)) {
        stableFrames += 1;
      } else {
        stableFrames = 0;
      }
      previous = current;
      expect(stableFrames).toBeGreaterThanOrEqual(2);
    },
    { timeout: 1_000 },
  );
  return previous;
}

function perimeter(snapshot: FocusVisualSnapshot) {
  return {
    borderColors: snapshot.borderColors,
    borderRadii: snapshot.borderRadii,
    borderStyles: snapshot.borderStyles,
    borderWidths: snapshot.borderWidths,
    height: snapshot.height,
    width: snapshot.width,
  };
}

function surfaceChanged(
  resting: FocusVisualSnapshot,
  focused: FocusVisualSnapshot,
) {
  return (
    focused.backgroundColor !== resting.backgroundColor ||
    focused.backgroundImage !== resting.backgroundImage ||
    focused.color !== resting.color ||
    focused.scrollbarColor !== resting.scrollbarColor ||
    (focused.filter !== resting.filter &&
      ["brightness(0.92)", "brightness(0.94)"].includes(focused.filter))
  );
}

function resolvedShadow(element: HTMLElement, value: string) {
  const reference = element.ownerDocument.createElement("span");
  reference.style.boxShadow = value;
  reference.style.position = "fixed";
  reference.style.pointerEvents = "none";
  reference.style.visibility = "hidden";
  (element.parentElement ?? element.ownerDocument.body).append(reference);
  const resolved = visualStyle(reference).boxShadow;
  reference.remove();
  return resolved;
}

/**
 * Moves focus with a real Tab interaction without making a story depend on all
 * focusable siblings that happen to precede the contract target.
 */
export async function focusWithKeyboard(element: HTMLElement) {
  const sentinel = element.ownerDocument.createElement("button");
  await expect(element.tabIndex).toBeGreaterThanOrEqual(0);
  sentinel.style.opacity = "0";
  sentinel.style.pointerEvents = "none";
  sentinel.style.position = "fixed";
  sentinel.style.width = "1px";
  sentinel.tabIndex = 0;
  element.before(sentinel);
  sentinel.focus();
  await userEvent.tab();
  sentinel.remove();
  await expect(element).toHaveFocus();
}

export async function expectQuietPointerFocus({
  element,
  resting,
  cue,
}: {
  element: HTMLElement;
  resting: FocusVisualSnapshot;
  cue?: FocusCue & { resting: FocusVisualSnapshot };
}) {
  await waitFor(() => {
    expect(readFocusVisual(element)).toEqual(resting);
    if (cue) {
      expect(readFocusVisual(cue.element, cue.pseudo)).toEqual(cue.resting);
    }
  });
}

export async function expectStableFocusPerimeter({
  element,
  resting,
  shadow = "stable",
}: {
  element: HTMLElement;
  resting: FocusVisualSnapshot;
  shadow?: FocusShadowPolicy;
}) {
  await waitFor(() => {
    const focused = readFocusVisual(element);
    expect(perimeter(focused)).toEqual(perimeter(resting));
    expect(focused.outlineStyle).toBe("none");
    if (shadow === "raised") {
      expect(focused.boxShadow).toBe(
        resolvedShadow(element, "var(--elevation-raised)"),
      );
    } else {
      expect(focused.boxShadow).toBe(resting.boxShadow);
    }
  });
}

export async function expectLayeredKeyboardFocus({
  element,
  resting,
  cue,
  shadow = "stable",
}: {
  element: HTMLElement;
  resting: FocusVisualSnapshot;
  cue?: FocusCue & { resting: FocusVisualSnapshot };
  shadow?: FocusShadowPolicy;
}) {
  await expectStableFocusPerimeter({ element, resting, shadow });
  await waitFor(() => {
    const focused = readFocusVisual(element);
    const focusedCue = cue ? readFocusVisual(cue.element, cue.pseudo) : focused;
    const restingCue = cue?.resting ?? resting;
    expect(focusedCue.opacity).toBe(restingCue.opacity);
    if (focusedCue.filter !== restingCue.filter) {
      expect(["brightness(0.92)", "brightness(0.94)"]).toContain(
        focusedCue.filter,
      );
    }
    expect(focusedCue.transform).toBe(restingCue.transform);
    expect(surfaceChanged(restingCue, focusedCue)).toBe(true);
  });
}
