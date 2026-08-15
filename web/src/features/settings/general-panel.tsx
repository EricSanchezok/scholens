"use client";

import { useTranslations } from "next-intl";

import {
  Field,
  FieldControl,
  FieldLabel,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useTheme } from "@/design-system/theme/theme-provider";
import { useLocalePreference } from "@/i18n/use-locale-preference";
import {
  SettingsCard,
  SettingsCardBody,
  SettingsCardHeader,
  SettingsPanelHeader,
} from "./settings-layout";

export function GeneralPanel() {
  const t = useTranslations("Settings");
  const { locale, pending: localePending, setLocale } = useLocalePreference();
  const { preference, setColorSchemePreference } = useTheme();

  return (
    <div>
      <SettingsPanelHeader
        description={t("general.description")}
        title={t("general.title")}
      />
      <SettingsCard>
        <SettingsCardHeader
          description={t("general.preferencesDescription")}
          title={t("general.preferences")}
        />
        <SettingsCardBody>
          <div className="grid max-w-xl gap-5 sm:grid-cols-2">
            <Field>
              <FieldLabel>{t("general.interfaceLanguage")}</FieldLabel>
              <Select
                disabled={localePending}
                onValueChange={(value) => setLocale(value as "en" | "zh-CN")}
                value={locale}
              >
                <FieldControl>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                </FieldControl>
                <SelectContent>
                  <SelectItem value="en">English</SelectItem>
                  <SelectItem value="zh-CN">简体中文</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel>{t("general.appearance")}</FieldLabel>
              <Select
                onValueChange={(value) =>
                  setColorSchemePreference(value as "light" | "dark" | "system")
                }
                value={preference}
              >
                <FieldControl>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                </FieldControl>
                <SelectContent>
                  <SelectItem value="light">{t("appearance.light")}</SelectItem>
                  <SelectItem value="dark">{t("appearance.dark")}</SelectItem>
                  <SelectItem value="system">
                    {t("appearance.system")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>
        </SettingsCardBody>
      </SettingsCard>
    </div>
  );
}
