"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { useAuthSession } from "@/features/authentication";
import {
  readSessionState,
  writeSessionState,
} from "@/lib/browser/session-state";
import {
  createNavigationToken,
  currentAppLocation,
  readNavigationContext,
  readWorkspaceDestination,
  rememberWorkspaceDestination,
  saveNavigationContext,
  withoutNavigationToken,
  withNavigationToken,
  workspaceDestinationForPath,
  type NavigationContextV1,
  type NavigationOriginKind,
  type NavigationSnapshot,
  type RememberedWorkspaceDestination,
} from "./navigation-state";

type NavigationRestorer = {
  capture: () => NavigationSnapshot;
  restore: (
    snapshot: NavigationSnapshot,
    options: { focusKey?: string },
  ) => void;
};

type OpenContextualRouteOptions = {
  destination: string;
  focusKey?: string;
  originKind: NavigationOriginKind;
};

type ContextRouteOptions = {
  history?: "push" | "replace";
  scroll?: boolean;
};

type ContextHistoryMarker = {
  depth: number;
  token: string;
};

type WorkspaceNavigationValue = {
  context?: NavigationContextV1;
  globalSearchOpen: boolean;
  initializeSidebar: (collapsed: boolean) => void;
  openContextualRoute: (options: OpenContextualRouteOptions) => void;
  registerRestorer: (id: string, restorer: NavigationRestorer) => () => void;
  rememberedHref: (
    destination: RememberedWorkspaceDestination,
    fallback: string,
  ) => Route;
  returnFromContext: (fallback: string) => void;
  setGlobalSearchOpen: (open: boolean) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  sidebarCollapsed?: boolean;
  updateContextRoute: (
    destination: string,
    options?: ContextRouteOptions,
  ) => void;
};

const WorkspaceNavigationContext = React.createContext<
  WorkspaceNavigationValue | undefined
>(undefined);

function exactLocation(pathname: string, searchParams: URLSearchParams) {
  const query = searchParams.toString();
  return `${pathname}${query ? `?${query}` : ""}`;
}

function currentContextHistoryMarker() {
  const marker = window.history.state?.__scholensNavigationCurrent as
    Partial<ContextHistoryMarker> | undefined;
  return marker &&
    typeof marker.token === "string" &&
    typeof marker.depth === "number" &&
    Number.isInteger(marker.depth) &&
    marker.depth > 0
    ? (marker as ContextHistoryMarker)
    : undefined;
}

export function WorkspaceNavigationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const session = useAuthSession();
  const restorersRef = React.useRef(new Map<string, NavigationRestorer>());
  const pendingRestoreRef = React.useRef<NavigationContextV1 | undefined>(
    undefined,
  );
  const pendingHistoryMarkerRef = React.useRef<
    ContextHistoryMarker | undefined
  >(undefined);
  const actorId = session.actor?.id;
  const [globalSearchOpen, setGlobalSearchOpen] = React.useState(false);
  const [sidebarState, setSidebarState] = React.useState<{
    actorId?: number;
    collapsed?: boolean;
  }>({});
  const previousActorIdRef = React.useRef(actorId);
  const [restoreEpoch, setRestoreEpoch] = React.useState(0);
  const token = searchParams.get("nav");
  const context = React.useMemo(
    () => (actorId ? readNavigationContext(actorId, token) : undefined),
    [actorId, token],
  );
  const sidebarCollapsed =
    sidebarState.actorId === actorId ? sidebarState.collapsed : undefined;

  React.useEffect(() => {
    if (
      previousActorIdRef.current !== undefined &&
      previousActorIdRef.current !== actorId
    ) {
      setGlobalSearchOpen(false);
    }
    previousActorIdRef.current = actorId;
  }, [actorId]);

  const initializeSidebar = React.useCallback(
    (collapsed: boolean) => {
      setSidebarState((current) => {
        if (current.actorId === actorId && current.collapsed !== undefined) {
          return current;
        }
        return {
          actorId,
          collapsed:
            (actorId
              ? readSessionState<boolean>(
                  `scholens:workspace-sidebar:v1:${actorId}`,
                )
              : undefined) ?? collapsed,
        };
      });
    },
    [actorId],
  );

  const setSidebarCollapsed = React.useCallback(
    (collapsed: boolean) => {
      setSidebarState(() => ({
        actorId,
        collapsed,
      }));
      if (actorId) {
        writeSessionState(
          `scholens:workspace-sidebar:v1:${actorId}`,
          collapsed,
        );
      }
    },
    [actorId],
  );

  const queueRestore = React.useCallback((next: NavigationContextV1) => {
    pendingRestoreRef.current = {
      ...next,
      snapshots: { ...next.snapshots },
    };
    setRestoreEpoch((current) => current + 1);
  }, []);

  React.useEffect(() => {
    if (!actorId) return;
    const destination = workspaceDestinationForPath(pathname);
    if (!destination) return;
    rememberWorkspaceDestination(
      actorId,
      destination,
      withoutNavigationToken(
        exactLocation(pathname, new URLSearchParams(searchParams.toString())),
      ),
    );
  }, [actorId, pathname, searchParams]);

  React.useEffect(() => {
    if (!actorId) return;
    const handlePopState = () => {
      const location = currentAppLocation();
      const originToken = window.history.state?.__scholensNavigationOrigin as
        string | undefined;
      const matched = readNavigationContext(actorId, originToken);
      if (matched?.origin === location) queueRestore(matched);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [actorId, queueRestore]);

  React.useLayoutEffect(() => {
    const pending = pendingRestoreRef.current;
    if (!pending || pending.origin !== currentAppLocation()) return;
    for (const [id, snapshot] of Object.entries(pending.snapshots)) {
      const restorer = restorersRef.current.get(id);
      if (!restorer) continue;
      restorer.restore(snapshot, { focusKey: pending.focusKey });
      delete pending.snapshots[id];
    }
    if (Object.keys(pending.snapshots).length === 0) {
      pendingRestoreRef.current = undefined;
    }
  }, [pathname, restoreEpoch, searchParams]);

  React.useLayoutEffect(() => {
    const marker = pendingHistoryMarkerRef.current;
    if (!marker || marker.token !== token) return;
    window.history.replaceState(
      { ...window.history.state, __scholensNavigationCurrent: marker },
      "",
    );
    pendingHistoryMarkerRef.current = undefined;
  }, [pathname, searchParams, token]);

  const registerRestorer = React.useCallback(
    (id: string, restorer: NavigationRestorer) => {
      restorersRef.current.set(id, restorer);
      const pending = pendingRestoreRef.current;
      const snapshot = pending?.snapshots[id];
      if (pending && snapshot && pending.origin === currentAppLocation()) {
        restorer.restore(snapshot, { focusKey: pending.focusKey });
        delete pending.snapshots[id];
        if (Object.keys(pending.snapshots).length === 0) {
          pendingRestoreRef.current = undefined;
        }
      }
      return () => restorersRef.current.delete(id);
    },
    [],
  );

  const openContextualRoute = React.useCallback(
    ({ destination, focusKey, originKind }: OpenContextualRouteOptions) => {
      if (!actorId) {
        router.push(destination as Route);
        return;
      }
      const nextToken = createNavigationToken();
      const snapshots = Object.fromEntries(
        Array.from(restorersRef.current, ([id, restorer]) => [
          id,
          restorer.capture(),
        ]),
      );
      const origin = currentAppLocation();
      saveNavigationContext({
        actorId,
        createdAt: Date.now(),
        destination,
        focusKey,
        origin,
        originKind,
        snapshots,
        token: nextToken,
        version: 1,
      });
      window.history.replaceState(
        { ...window.history.state, __scholensNavigationOrigin: nextToken },
        "",
      );
      const href = withNavigationToken(destination, nextToken);
      pendingHistoryMarkerRef.current = { depth: 1, token: nextToken };
      router.push(href, { scroll: false });
    },
    [actorId, router],
  );

  const returnFromContext = React.useCallback(
    (fallback: string) => {
      if (!context) {
        router.push(fallback as Route);
        return;
      }
      queueRestore(context);
      const marker = currentContextHistoryMarker();
      if (marker?.token === context.token) {
        window.history.go(-marker.depth);
      } else {
        router.replace(context.origin as Route, { scroll: false });
      }
    },
    [context, queueRestore, router],
  );

  const updateContextRoute = React.useCallback(
    (
      destination: string,
      { history = "replace", scroll = false }: ContextRouteOptions = {},
    ) => {
      const href = context
        ? withNavigationToken(destination, context.token)
        : (destination as Route);
      const currentMarker = currentContextHistoryMarker();
      if (context && currentMarker?.token === context.token) {
        pendingHistoryMarkerRef.current = {
          depth: currentMarker.depth + (history === "push" ? 1 : 0),
          token: context.token,
        };
      }
      if (history === "push") router.push(href, { scroll });
      else router.replace(href, { scroll });
    },
    [context, router],
  );

  const rememberedHref = React.useCallback(
    (destination: RememberedWorkspaceDestination, fallback: string) =>
      actorId
        ? readWorkspaceDestination(actorId, destination, fallback)
        : (fallback as Route),
    [actorId],
  );

  const value = React.useMemo<WorkspaceNavigationValue>(
    () => ({
      context,
      globalSearchOpen,
      initializeSidebar,
      openContextualRoute,
      registerRestorer,
      rememberedHref,
      returnFromContext,
      setGlobalSearchOpen,
      setSidebarCollapsed,
      sidebarCollapsed,
      updateContextRoute,
    }),
    [
      context,
      globalSearchOpen,
      initializeSidebar,
      openContextualRoute,
      registerRestorer,
      rememberedHref,
      returnFromContext,
      setGlobalSearchOpen,
      setSidebarCollapsed,
      sidebarCollapsed,
      updateContextRoute,
    ],
  );

  return (
    <WorkspaceNavigationContext.Provider value={value}>
      {children}
    </WorkspaceNavigationContext.Provider>
  );
}

export function useWorkspaceNavigation() {
  const value = React.useContext(WorkspaceNavigationContext);
  if (!value) {
    throw new Error(
      "useWorkspaceNavigation must be used inside WorkspaceNavigationProvider",
    );
  }
  return value;
}

export function useOptionalWorkspaceNavigation() {
  return React.useContext(WorkspaceNavigationContext);
}

export function useNavigationRestorer(
  id: string,
  restorer: NavigationRestorer,
) {
  const navigation = useOptionalWorkspaceNavigation();
  const registerRestorer = navigation?.registerRestorer;
  const captureRef = React.useRef(restorer.capture);
  const restoreRef = React.useRef(restorer.restore);

  React.useLayoutEffect(() => {
    captureRef.current = restorer.capture;
    restoreRef.current = restorer.restore;
  }, [restorer.capture, restorer.restore]);

  React.useLayoutEffect(() => {
    if (!registerRestorer) return;
    return registerRestorer(id, {
      capture: () => captureRef.current(),
      restore: (snapshot, options) => restoreRef.current(snapshot, options),
    });
  }, [id, registerRestorer]);
}

export function useNavigationScrollRestorer(
  id: string,
  {
    getScroller,
    rootRef,
  }: {
    getScroller?: () => HTMLElement | null;
    rootRef: React.RefObject<HTMLElement | null>;
  },
) {
  useNavigationRestorer(id, {
    capture: () => ({
      scrollTop:
        (getScroller?.() ?? rootRef.current?.closest("main"))?.scrollTop ?? 0,
    }),
    restore: (snapshot, { focusKey }) => {
      window.requestAnimationFrame(() => {
        const scroller = getScroller?.() ?? rootRef.current?.closest("main");
        if (scroller && typeof snapshot.scrollTop === "number") {
          scroller.scrollTop = snapshot.scrollTop;
        }
        if (!focusKey) return;
        const targets = rootRef.current?.querySelectorAll<HTMLElement>(
          `[data-navigation-focus="${CSS.escape(focusKey)}"]`,
        );
        const target = Array.from(targets ?? []).find(
          (candidate) => candidate.getClientRects().length > 0,
        );
        (target ?? targets?.[0])?.focus({ preventScroll: true });
      });
    },
  });
}
