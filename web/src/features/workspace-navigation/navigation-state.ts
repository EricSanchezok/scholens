import type { Route } from "next";

import { validatedReturnTo } from "@/features/authentication";
import {
  readSessionState,
  removeSessionState,
  writeSessionState,
} from "@/lib/browser/session-state";

export const NAVIGATION_QUERY_KEY = "nav";
export const NAVIGATION_STATE_VERSION = 1;
export const MAX_NAVIGATION_CONTEXTS = 64;

export type NavigationOriginKind =
  "activity" | "library" | "project" | "reader" | "search";
export type RememberedWorkspaceDestination = "library" | "me" | "projects";

export type NavigationSnapshot = Record<string, unknown>;

export type NavigationContextV1 = {
  actorId: number;
  createdAt: number;
  destination: string;
  focusKey?: string;
  origin: string;
  originKind: NavigationOriginKind;
  snapshots: Record<string, NavigationSnapshot>;
  token: string;
  version: typeof NAVIGATION_STATE_VERSION;
};

type NavigationRegistryV1 = {
  contexts: NavigationContextV1[];
  version: typeof NAVIGATION_STATE_VERSION;
};

const memoryRegistries = new Map<number, NavigationRegistryV1>();
const memoryDestinations = new Map<number, Record<string, string>>();

function registryKey(actorId: number) {
  return `scholens:navigation:v1:${actorId}`;
}

function destinationKey(actorId: number) {
  return `scholens:navigation-destinations:v1:${actorId}`;
}

function isSnapshot(value: unknown): value is NavigationSnapshot {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function isNavigationOriginKind(value: unknown): value is NavigationOriginKind {
  return (
    value === "activity" ||
    value === "library" ||
    value === "project" ||
    value === "reader" ||
    value === "search"
  );
}

function isNavigationContext(
  value: unknown,
  actorId: number,
): value is NavigationContextV1 {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<NavigationContextV1>;
  return (
    candidate.version === NAVIGATION_STATE_VERSION &&
    candidate.actorId === actorId &&
    typeof candidate.createdAt === "number" &&
    Number.isFinite(candidate.createdAt) &&
    typeof candidate.destination === "string" &&
    Boolean(validatedReturnTo(candidate.destination)) &&
    typeof candidate.origin === "string" &&
    Boolean(validatedReturnTo(candidate.origin)) &&
    isNavigationOriginKind(candidate.originKind) &&
    isSnapshot(candidate.snapshots) &&
    typeof candidate.token === "string" &&
    candidate.token.length > 0 &&
    (candidate.focusKey === undefined || typeof candidate.focusKey === "string")
  );
}

function parseRegistry(value: unknown, actorId: number) {
  if (!value || typeof value !== "object") return undefined;
  const parsed = value as Partial<NavigationRegistryV1>;
  if (
    parsed.version !== NAVIGATION_STATE_VERSION ||
    !Array.isArray(parsed.contexts)
  ) {
    return undefined;
  }
  return {
    contexts: parsed.contexts.filter((context) =>
      isNavigationContext(context, actorId),
    ),
    version: NAVIGATION_STATE_VERSION,
  } satisfies NavigationRegistryV1;
}

function readRegistry(actorId: number): NavigationRegistryV1 {
  const stored = parseRegistry(
    readSessionState<unknown>(registryKey(actorId)),
    actorId,
  );
  if (stored) {
    memoryRegistries.set(actorId, stored);
    return stored;
  }
  return (
    memoryRegistries.get(actorId) ?? {
      contexts: [],
      version: NAVIGATION_STATE_VERSION,
    }
  );
}

function writeRegistry(actorId: number, registry: NavigationRegistryV1) {
  memoryRegistries.set(actorId, registry);
  writeSessionState(registryKey(actorId), registry);
}

export function saveNavigationContext(context: NavigationContextV1) {
  const current = readRegistry(context.actorId).contexts.filter(
    (item) => item.token !== context.token,
  );
  const contexts = [...current, context].slice(-MAX_NAVIGATION_CONTEXTS);
  writeRegistry(context.actorId, {
    contexts,
    version: NAVIGATION_STATE_VERSION,
  });
}

export function readNavigationContext(actorId: number, token?: string | null) {
  if (!token) return undefined;
  return readRegistry(actorId).contexts.find((item) => item.token === token);
}

export function clearNavigationSession(actorId: number) {
  memoryRegistries.delete(actorId);
  memoryDestinations.delete(actorId);
  removeSessionState(registryKey(actorId));
  removeSessionState(destinationKey(actorId));
}

export function withNavigationToken(href: string, token: string): Route {
  const target = new URL(href, "https://scholens.local");
  target.searchParams.set(NAVIGATION_QUERY_KEY, token);
  return `${target.pathname}${target.search}${target.hash}` as Route;
}

export function withoutNavigationToken(href: string): Route {
  const target = new URL(href, "https://scholens.local");
  target.searchParams.delete(NAVIGATION_QUERY_KEY);
  return `${target.pathname}${target.search}${target.hash}` as Route;
}

export function currentAppLocation(fallback: string = "/"): Route {
  if (typeof window === "undefined") return fallback as Route;
  return `${window.location.pathname}${window.location.search}${window.location.hash}` as Route;
}

function parseDestinations(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return undefined;
  return Object.fromEntries(
    Object.entries(value).filter(
      (entry): entry is [string, string] =>
        typeof entry[1] === "string" && Boolean(validatedReturnTo(entry[1])),
    ),
  );
}

function readDestinations(actorId: number) {
  const stored = parseDestinations(
    readSessionState<unknown>(destinationKey(actorId)),
  );
  if (stored) {
    memoryDestinations.set(actorId, stored);
    return stored;
  }
  return memoryDestinations.get(actorId) ?? {};
}

export function rememberWorkspaceDestination(
  actorId: number,
  destination: RememberedWorkspaceDestination,
  href: string,
) {
  const safeHref = validatedReturnTo(href);
  if (!safeHref) return;
  const destinations = {
    ...readDestinations(actorId),
    [destination]: safeHref,
  };
  memoryDestinations.set(actorId, destinations);
  writeSessionState(destinationKey(actorId), destinations);
}

export function readWorkspaceDestination(
  actorId: number,
  destination: RememberedWorkspaceDestination,
  fallback: string,
): Route {
  return (readDestinations(actorId)[destination] ?? fallback) as Route;
}

export function workspaceDestinationForPath(
  pathname: string,
): RememberedWorkspaceDestination | undefined {
  if (pathname === "/library") return "library";
  if (pathname === "/projects") return "projects";
  if (pathname === "/me") return "me";
  return undefined;
}

export function createNavigationToken() {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  );
}
