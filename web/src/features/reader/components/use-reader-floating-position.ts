"use client";

import * as React from "react";

import {
  computeReaderFloatingPosition,
  type ReaderFloatingPosition,
  type ReaderFloatingRect,
} from "./reader-floating-position";

export function useReaderFloatingPosition({
  boundaryRef,
  bounds,
}: {
  boundaryRef?: React.RefObject<HTMLElement | null>;
  bounds: ReaderFloatingRect;
}) {
  const floatingRef = React.useRef<HTMLDivElement>(null);
  const [position, setPosition] = React.useState<ReaderFloatingPosition>();

  React.useLayoutEffect(() => {
    const floating = floatingRef.current;
    const offsetParent = floating?.offsetParent;
    if (!floating || !(offsetParent instanceof HTMLElement)) return;
    const boundaryElement = boundaryRef?.current;
    let frame: number | undefined;

    function updatePosition() {
      frame = undefined;
      const floatingRect = floating!.getBoundingClientRect();
      const offsetParentRect = offsetParent!.getBoundingClientRect();
      const hostRect =
        boundaryElement?.getBoundingClientRect() ?? offsetParentRect;
      const viewport = window.visualViewport;
      const viewportLeft = viewport?.offsetLeft ?? 0;
      const viewportTop = viewport?.offsetTop ?? 0;
      const viewportRect: ReaderFloatingRect = {
        left: viewportLeft,
        top: viewportTop,
        right:
          viewportLeft +
          (viewport?.width ?? document.documentElement.clientWidth),
        bottom:
          viewportTop +
          (viewport?.height ?? document.documentElement.clientHeight),
      };
      const boundary: ReaderFloatingRect = {
        left:
          Math.max(offsetParentRect.left, hostRect.left, viewportRect.left) -
          offsetParentRect.left,
        right:
          Math.min(offsetParentRect.right, hostRect.right, viewportRect.right) -
          offsetParentRect.left,
        top: Math.max(hostRect.top, viewportRect.top) - offsetParentRect.top,
        bottom:
          Math.min(hostRect.bottom, viewportRect.bottom) - offsetParentRect.top,
      };
      const anchor: ReaderFloatingRect = {
        left: bounds.left * offsetParentRect.width,
        right: bounds.right * offsetParentRect.width,
        top: bounds.top * offsetParentRect.height,
        bottom: bounds.bottom * offsetParentRect.height,
      };
      const nextPosition = computeReaderFloatingPosition({
        anchor,
        boundary,
        floating: {
          height: floatingRect.height,
          width: floatingRect.width,
        },
      });
      setPosition((current) =>
        current &&
        current.left === nextPosition.left &&
        current.top === nextPosition.top &&
        current.maxHeight === nextPosition.maxHeight &&
        current.maxWidth === nextPosition.maxWidth &&
        current.placement === nextPosition.placement
          ? current
          : nextPosition,
      );
    }

    function schedulePositionUpdate() {
      if (frame !== undefined) return;
      frame = window.requestAnimationFrame(updatePosition);
    }

    const observer = new ResizeObserver(schedulePositionUpdate);
    observer.observe(floating);
    observer.observe(offsetParent);
    if (boundaryElement && boundaryElement !== offsetParent) {
      observer.observe(boundaryElement);
    }
    window.addEventListener("resize", schedulePositionUpdate, {
      passive: true,
    });
    window.addEventListener("scroll", schedulePositionUpdate, {
      capture: true,
      passive: true,
    });
    window.visualViewport?.addEventListener("resize", schedulePositionUpdate, {
      passive: true,
    });
    window.visualViewport?.addEventListener("scroll", schedulePositionUpdate, {
      passive: true,
    });
    updatePosition();

    return () => {
      if (frame !== undefined) window.cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", schedulePositionUpdate);
      window.removeEventListener("scroll", schedulePositionUpdate, true);
      window.visualViewport?.removeEventListener(
        "resize",
        schedulePositionUpdate,
      );
      window.visualViewport?.removeEventListener(
        "scroll",
        schedulePositionUpdate,
      );
    };
  }, [boundaryRef, bounds.bottom, bounds.left, bounds.right, bounds.top]);

  return { floatingRef, position };
}
