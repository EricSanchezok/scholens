export type ReaderFloatingRect = {
  bottom: number;
  left: number;
  right: number;
  top: number;
};

export type ReaderFloatingSize = {
  height: number;
  width: number;
};

export type ReaderFloatingPosition = {
  contentMaxHeight: number;
  left: number;
  maxHeight: number;
  maxWidth: number;
  placement: "top" | "bottom";
  top: number;
};

function clamp(value: number, minimum: number, maximum: number) {
  if (maximum < minimum) return minimum;
  return Math.min(Math.max(value, minimum), maximum);
}

export function computeReaderFloatingPosition({
  anchor,
  boundary,
  floating,
  gap = 8,
  padding = 8,
  preferredPlacement = "bottom",
  lockedPlacement,
}: {
  anchor: ReaderFloatingRect;
  boundary: ReaderFloatingRect;
  floating: ReaderFloatingSize;
  gap?: number;
  padding?: number;
  preferredPlacement?: "top" | "bottom";
  lockedPlacement?: "top" | "bottom";
}): ReaderFloatingPosition {
  const boundaryWidth = Math.max(
    0,
    boundary.right - boundary.left - padding * 2,
  );
  const boundaryHeight = Math.max(
    0,
    boundary.bottom - boundary.top - padding * 2,
  );
  const width = Math.min(Math.max(0, floating.width), boundaryWidth);
  const height = Math.min(Math.max(0, floating.height), boundaryHeight);
  const spaceAbove = Math.max(0, anchor.top - boundary.top - gap - padding);
  const spaceBelow = Math.max(
    0,
    boundary.bottom - anchor.bottom - gap - padding,
  );
  const preferredSpace = preferredPlacement === "top" ? spaceAbove : spaceBelow;
  const alternateSpace = preferredPlacement === "top" ? spaceBelow : spaceAbove;
  const placement =
    lockedPlacement ??
    (floating.height <= preferredSpace || preferredSpace >= alternateSpace
      ? preferredPlacement
      : preferredPlacement === "top"
        ? "bottom"
        : "top");
  const desiredTop =
    placement === "top" ? anchor.top - gap - height : anchor.bottom + gap;
  const left = clamp(
    (anchor.left + anchor.right - width) / 2,
    boundary.left + padding,
    boundary.right - padding - width,
  );
  const top = clamp(
    desiredTop,
    boundary.top + padding,
    boundary.bottom - padding - height,
  );
  const maxHeight = Math.max(0, boundary.bottom - top - padding);

  return {
    contentMaxHeight: Math.max(0, maxHeight - height - gap),
    left,
    maxHeight,
    maxWidth: boundaryWidth,
    placement,
    top,
  };
}
