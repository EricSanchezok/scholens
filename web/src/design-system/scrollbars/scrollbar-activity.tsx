"use client";

import { useEffect } from "react";

export const scrollbarActivityAttribute = "data-scrollbar-active";
export const scrollbarIdleDelayMs = 500;
export const scrollbarTrackRemovalDelayMs = 1_000;

let activityConsumers = 0;
let stopActivityTracking: (() => void) | undefined;

function scrollingElement(target: EventTarget | null): Element | null {
  if (target instanceof Element) {
    return target;
  }
  if (target === document) {
    return document.scrollingElement ?? document.documentElement;
  }
  return null;
}

function startActivityTracking() {
  const hideTimers = new Map<Element, number>();

  const showScrollbar = (event: Event) => {
    const element = scrollingElement(event.target);
    if (!element) {
      return;
    }

    element.setAttribute(scrollbarActivityAttribute, "");
    const existingTimer = hideTimers.get(element);
    if (existingTimer !== undefined) {
      window.clearTimeout(existingTimer);
    }
    hideTimers.set(
      element,
      window.setTimeout(() => {
        element.removeAttribute(scrollbarActivityAttribute);
        hideTimers.delete(element);
      }, scrollbarIdleDelayMs),
    );
  };

  document.addEventListener("scroll", showScrollbar, {
    capture: true,
    passive: true,
  });
  return () => {
    document.removeEventListener("scroll", showScrollbar, true);
    hideTimers.forEach((timer, element) => {
      window.clearTimeout(timer);
      element.removeAttribute(scrollbarActivityAttribute);
    });
    hideTimers.clear();
  };
}

export function ScrollbarActivity() {
  useEffect(() => {
    activityConsumers += 1;
    stopActivityTracking ??= startActivityTracking();

    return () => {
      activityConsumers -= 1;
      if (activityConsumers === 0) {
        stopActivityTracking?.();
        stopActivityTracking = undefined;
      }
    };
  }, []);

  return null;
}
