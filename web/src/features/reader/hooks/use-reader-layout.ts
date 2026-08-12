"use client";

import * as React from "react";

const DOCUMENT_NAVIGATION_QUERY = "(min-width: 48rem)";
const DESKTOP_PANEL_QUERY = "(min-width: 64rem)";

function subscribe(query: string, onStoreChange: () => void) {
  const mediaQuery = window.matchMedia(query);
  mediaQuery.addEventListener("change", onStoreChange);
  return () => mediaQuery.removeEventListener("change", onStoreChange);
}

function useMediaQuery(query: string) {
  const subscribeToQuery = React.useCallback(
    (onStoreChange: () => void) => subscribe(query, onStoreChange),
    [query],
  );
  const getSnapshot = React.useCallback(
    () => window.matchMedia(query).matches,
    [query],
  );
  return React.useSyncExternalStore(
    subscribeToQuery,
    getSnapshot,
    getServerSnapshot,
  );
}

function getServerSnapshot() {
  return false;
}

/**
 * Keeps document navigation out of the DOM when the responsive layout hides it.
 * CSS-only hiding would still initialize PDF.js thumbnail canvases on phones.
 */
export function useDocumentNavigationRail() {
  return useMediaQuery(DOCUMENT_NAVIGATION_QUERY);
}

/** Prevents a visually hidden mobile Sheet from making the desktop inert. */
export function useDesktopReaderPanel() {
  return useMediaQuery(DESKTOP_PANEL_QUERY);
}
