"use client";

import type { Route } from "next";
import Link from "next/link";
import * as React from "react";

import { useOptionalWorkspaceNavigation } from "./workspace-navigation-provider";
import type { NavigationOriginKind } from "./navigation-state";

function isPlainPrimaryClick(event: React.MouseEvent<HTMLAnchorElement>) {
  return (
    event.button === 0 &&
    !event.altKey &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.shiftKey &&
    !event.defaultPrevented
  );
}

export const ContextualLink = React.forwardRef<
  HTMLAnchorElement,
  Omit<React.ComponentProps<typeof Link>, "href"> & {
    focusKey?: string;
    href: Route | string;
    onPrimaryNavigate?: () => void;
    originKind: NavigationOriginKind;
  }
>(function ContextualLink(
  { focusKey, href, onClick, onPrimaryNavigate, originKind, target, ...props },
  ref,
) {
  const navigation = useOptionalWorkspaceNavigation();
  return (
    <Link
      {...props}
      data-navigation-focus={focusKey}
      href={href as Route}
      onClick={(event) => {
        onClick?.(event);
        if (!isPlainPrimaryClick(event) || (target && target !== "_self"))
          return;
        onPrimaryNavigate?.();
        if (!navigation) return;
        event.preventDefault();
        navigation.openContextualRoute({
          destination: String(href),
          focusKey,
          originKind,
        });
      }}
      ref={ref}
      target={target}
    />
  );
});

export const ContextRouteLink = React.forwardRef<
  HTMLAnchorElement,
  Omit<React.ComponentProps<typeof Link>, "href"> & {
    history?: "push" | "replace";
    href: Route | string;
  }
>(function ContextRouteLink(
  { history = "push", href, onClick, target, ...props },
  ref,
) {
  const navigation = useOptionalWorkspaceNavigation();
  return (
    <Link
      {...props}
      href={href as Route}
      onClick={(event) => {
        onClick?.(event);
        if (
          !navigation ||
          !isPlainPrimaryClick(event) ||
          (target && target !== "_self")
        )
          return;
        event.preventDefault();
        navigation.updateContextRoute(String(href), { history });
      }}
      ref={ref}
      target={target}
    />
  );
});
