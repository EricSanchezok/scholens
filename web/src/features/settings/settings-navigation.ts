"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { useDesktopLayout } from "@/lib/utilities/use-desktop-layout";
import {
  mobileSettingsHref,
  type MobileSettingsSection,
} from "./account-hub-routes";

export const settingsSections = [
  "account",
  "general",
  "usage",
  "access-keys",
  "connections",
  "translation",
] as const;
export type SettingsSection = (typeof settingsSections)[number];

type Section = SettingsSection & MobileSettingsSection;

function isSettingsSection(value: string | null): value is SettingsSection {
  return settingsSections.includes(value as SettingsSection);
}

export function useSettingsNavigation() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const sectionValue = searchParams.get("settings");
  const section = isSettingsSection(sectionValue) ? sectionValue : undefined;

  const setSection = React.useCallback(
    (next: SettingsSection | undefined) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next) params.set("settings", next);
      else params.delete("settings");
      const query = params.toString();
      router.replace(`${pathname}${query ? `?${query}` : ""}` as Route, {
        scroll: false,
      });
    },
    [pathname, router, searchParams],
  );

  return { section, setSection };
}

export function useSettingsLauncher() {
  const desktop = useDesktopLayout();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { setSection } = useSettingsNavigation();

  const openSection = React.useCallback(
    (section: Section) => {
      if (desktop) {
        setSection(section);
        return;
      }
      const returnParams = new URLSearchParams(searchParams.toString());
      returnParams.delete("settings");
      const query = returnParams.toString();
      const returnTo = `${pathname}${query ? `?${query}` : ""}`;
      router.push(mobileSettingsHref(section, { returnTo }) as Route, {
        scroll: false,
      });
    },
    [desktop, pathname, router, searchParams, setSection],
  );

  return { openSection };
}
