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
  placementKey,
  preferredPlacement = "bottom",
}: {
  boundaryRef?: React.RefObject<HTMLElement | null>;
  bounds: ReaderFloatingRect;
  placementKey: string;
  preferredPlacement?: "top" | "bottom";
}) {
  const floatingRef = React.useRef<HTMLDivElement>(null);
  const measureRef = React.useRef<HTMLDivElement>(null);
  const placementRef = React.useRef<"top" | "bottom" | undefined>(undefined);
  const previousPlacementKeyRef = React.useRef(placementKey);
  const [position, setPosition] = React.useState<ReaderFloatingPosition>();

  if (previousPlacementKeyRef.current !== placementKey) {
    previousPlacementKeyRef.current = placementKey;
    placementRef.current = undefined;
  }

  React.useLayoutEffect(() => {
    const floating = floatingRef.current;
    const measure = measureRef.current;
    const offsetParent = floating?.offsetParent;
    if (!floating || !measure || !(offsetParent instanceof HTMLElement)) return;
    const boundaryElement = boundaryRef?.current;
    let frame: number | undefined;

    function updatePosition() {
      frame = undefined;
      const floatingRect = floating!.getBoundingClientRect();
      const measureRect = measure!.getBoundingClientRect();
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
          height: measureRect.height,
          width: floatingRect.width,
        },
        lockedPlacement: placementRef.current,
        preferredPlacement,
      });
      if (!placementRef.current) placementRef.current = nextPosition.placement;
      setPosition((current) =>
        current &&
        current.contentMaxHeight === nextPosition.contentMaxHeight &&
        current.left === nextPosition.left &&
        current.top === nextPosition.top &&
        current.maxHeight === nextPosition.maxHeight &&
        current.maxWidth === nextPosition.maxWidth &&
        current.placement === nextPosition.placement &&
        current.visible === nextPosition.visible
          ? current
          : nextPosition,
      );
    }

    function schedulePositionUpdate(resetPlacement = false) {
      if (resetPlacement) placementRef.current = undefined;
      if (frame !== undefined) return;
      frame = window.requestAnimationFrame(updatePosition);
    }

    let floatingWidth = floating.getBoundingClientRect().width;
    const observer = new ResizeObserver((entries) => {
      let resetPlacement = false;
      let widthChanged = false;
      for (const entry of entries) {
        if (entry.target === floating) {
          if (entry.contentRect.width !== floatingWidth) {
            floatingWidth = entry.contentRect.width;
            widthChanged = true;
          }
        } else {
          resetPlacement = true;
        }
      }
      if (resetPlacement || widthChanged) {
        schedulePositionUpdate(resetPlacement);
      }
    });
    observer.observe(floating);
    observer.observe(measure);
    observer.observe(offsetParent);
    if (boundaryElement && boundaryElement !== offsetParent) {
      observer.observe(boundaryElement);
    }
    const handleWindowResize = () => schedulePositionUpdate(true);
    const handleWindowScroll = () => schedulePositionUpdate();
    const handleViewportResize = () => schedulePositionUpdate(true);
    const handleViewportScroll = () => schedulePositionUpdate();
    window.addEventListener("resize", handleWindowResize, {
      passive: true,
    });
    window.addEventListener("scroll", handleWindowScroll, {
      capture: true,
      passive: true,
    });
    window.visualViewport?.addEventListener("resize", handleViewportResize);
    window.visualViewport?.addEventListener("scroll", handleViewportScroll);
    updatePosition();

    return () => {
      if (frame !== undefined) window.cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", handleWindowResize);
      window.removeEventListener("scroll", handleWindowScroll, true);
      window.visualViewport?.removeEventListener(
        "resize",
        handleViewportResize,
      );
      window.visualViewport?.removeEventListener(
        "scroll",
        handleViewportScroll,
      );
    };
  }, [
    boundaryRef,
    bounds.bottom,
    bounds.left,
    bounds.right,
    bounds.top,
    placementKey,
    preferredPlacement,
  ]);

  return { floatingRef, measureRef, position };
}
