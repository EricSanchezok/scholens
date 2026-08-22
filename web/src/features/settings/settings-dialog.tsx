"use client";

import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  keyboardFocusRing,
} from "@/components/ui";
import { Icon, type IconGlyph } from "@/design-system/icons/icon";
import {
  AccountIcon,
  AppearanceIcon,
  IntegrationIcon,
  KeyIcon,
  LanguageIcon,
  UsageIcon,
} from "@/design-system/icons/semantic-icons";
import { clientEnvironment } from "@/lib/env/client";
import { cn } from "@/lib/utilities/cn";
import { useDesktopLayout } from "@/lib/utilities/use-desktop-layout";
import { mobileSettingsRedirectHref } from "./account-hub-routes";
import { AccessKeysPanel } from "./access-keys-panel";
import { AccountPanel } from "./account-panel";
import { ConnectionsPanel } from "./connections-panel";
import { GeneralPanel } from "./general-panel";
import {
  settingsSections,
  useSettingsNavigation,
  type SettingsSection,
} from "./settings-navigation";
import { TranslationPanel } from "./translation-panel";
import { UsagePanel } from "./usage-panel";

const sectionIcons: Record<SettingsSection, IconGlyph> = {
  general: AppearanceIcon,
  account: AccountIcon,
  usage: UsageIcon,
  "access-keys": KeyIcon,
  connections: IntegrationIcon,
  translation: LanguageIcon,
};

function Panel({
  accountCenterUrl,
  section,
}: {
  accountCenterUrl?: string;
  section: SettingsSection;
}) {
  if (section === "account") {
    return <AccountPanel accountCenterUrl={accountCenterUrl} />;
  }
  if (section === "usage") return <UsagePanel />;
  if (section === "access-keys") return <AccessKeysPanel />;
  if (section === "connections") return <ConnectionsPanel />;
  if (section === "translation") return <TranslationPanel />;
  return <GeneralPanel />;
}

export function SettingsDialogSurface({
  accountCenterUrl = clientEnvironment.NEXT_PUBLIC_ACCOUNT_CENTER_URL,
  onSectionChange,
  section,
}: {
  accountCenterUrl?: string;
  onSectionChange: (section: SettingsSection | undefined) => void;
  section: SettingsSection | undefined;
}) {
  const t = useTranslations("Settings");
  const active = section ?? "general";

  return (
    <Dialog
      onOpenChange={(open) => {
        if (!open) onSectionChange(undefined);
      }}
      open={Boolean(section)}
    >
      <DialogContent
        closeLabel={t("actions.close")}
        className="lg:h-[min(88dvh,46rem)] lg:w-[min(92vw,68rem)] lg:rounded-[var(--radius-2xl)]"
        placement="responsive-full"
      >
        <DialogTitle className="sr-only">{t("title")}</DialogTitle>
        <DialogDescription className="sr-only">
          {t("description")}
        </DialogDescription>
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <aside className="border-line-subtle bg-subtle shrink-0 border-b px-4 py-4 lg:w-60 lg:border-r lg:border-b-0 lg:px-3 lg:py-6">
            <h1 className="mb-4 px-3 text-xl font-semibold tracking-[-0.015em]">
              {t("title")}
            </h1>
            <div className="lg:hidden">
              <Select
                onValueChange={(value) =>
                  onSectionChange(value as SettingsSection)
                }
                value={active}
              >
                <SelectTrigger aria-label={t("sectionPicker")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {settingsSections.map((item) => (
                    <SelectItem key={item} value={item}>
                      {t(`navigation.${item}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <nav
              aria-label={t("navigationLabel")}
              className="hidden gap-1 lg:grid"
            >
              {settingsSections.map((item) => (
                <button
                  aria-current={active === item ? "page" : undefined}
                  className={cn(
                    "motion-control hover:bg-hover flex h-10 w-full items-center gap-3 rounded-[var(--radius-lg)] px-3 text-left text-sm font-medium",
                    keyboardFocusRing,
                    active === item && "bg-hover",
                  )}
                  key={item}
                  onClick={() => onSectionChange(item)}
                  type="button"
                >
                  <span className="grid size-6 shrink-0 place-items-center">
                    <Icon
                      glyph={sectionIcons[item]}
                      size={20}
                      tone={active === item ? "primary" : "secondary"}
                    />
                  </span>
                  {t(`navigation.${item}`)}
                </button>
              ))}
            </nav>
          </aside>
          <main className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pt-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] sm:px-7 lg:px-10 lg:py-9">
            <div className="settled-content-enter" key={active}>
              <Panel accountCenterUrl={accountCenterUrl} section={active} />
            </div>
          </main>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function SettingsDialog({
  accountCenterUrl = clientEnvironment.NEXT_PUBLIC_ACCOUNT_CENTER_URL,
}: {
  accountCenterUrl?: string;
}) {
  const { section, setSection } = useSettingsNavigation();
  const desktop = useDesktopLayout();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();

  React.useEffect(() => {
    if (!section || desktop) return;
    router.replace(
      mobileSettingsRedirectHref(
        section,
        pathname,
        new URLSearchParams(searchParams.toString()),
      ) as Route,
      { scroll: false },
    );
  }, [desktop, pathname, router, searchParams, section]);

  if (section && !desktop) return null;

  return (
    <SettingsDialogSurface
      accountCenterUrl={accountCenterUrl}
      onSectionChange={setSection}
      section={section}
    />
  );
}
