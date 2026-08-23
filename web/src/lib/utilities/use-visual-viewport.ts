"use client";

import * as React from "react";

export type VisualViewportMetrics = {
  height: number;
  offsetTop: number;
};

export function readVisualViewport(
  visualViewport?: { height: number; offsetTop: number } | null,
  innerHeight = 0,
): VisualViewportMetrics {
  if (!visualViewport) {
    return { height: innerHeight, offsetTop: 0 };
  }

  return {
    height: visualViewport.height,
    offsetTop: visualViewport.offsetTop,
  };
}

/**
 * Track the browser's visible viewport instead of the layout viewport. Mobile
 * browsers can shrink and pan this viewport independently when browser chrome
 * or the software keyboard opens.
 */
export function useVisualViewport(
  enabled = true,
): VisualViewportMetrics | null {
  const [viewport, setViewport] = React.useState<VisualViewportMetrics | null>(
    null,
  );

  React.useEffect(() => {
    if (!enabled) return;

    const visualViewport = window.visualViewport;

    function update() {
      setViewport(
        readVisualViewport(
          visualViewport
            ? {
                height: visualViewport.height,
                offsetTop: visualViewport.offsetTop,
              }
            : null,
          window.innerHeight,
        ),
      );
    }

    update();
    window.addEventListener("resize", update);
    visualViewport?.addEventListener("resize", update);
    visualViewport?.addEventListener("scroll", update);

    return () => {
      window.removeEventListener("resize", update);
      visualViewport?.removeEventListener("resize", update);
      visualViewport?.removeEventListener("scroll", update);
    };
  }, [enabled]);

  return enabled ? viewport : null;
}
