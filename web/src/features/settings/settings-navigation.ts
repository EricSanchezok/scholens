"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

export const settingsSections = [
  "account",
  "general",
  "usage",
  "access-keys",
  "connections",
  "translation",
] as const;
export type SettingsSection = (typeof settingsSections)[number];

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
