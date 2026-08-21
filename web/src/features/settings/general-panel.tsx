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
  keyboardFocusRing,
} from "@/components/ui";
import { useTheme } from "@/design-system/theme";
import {
  themeNames,
  type ColorScheme,
  type ThemeName,
} from "@/design-system/generated/theme-metadata";
import {
  motionPreferences,
  useMotionPreference,
} from "@/design-system/motion/motion-provider";
import { useLocalePreference } from "@/i18n/use-locale-preference";
import { cn } from "@/lib/utilities/cn";
import { SettingsPanelHeader } from "./settings-layout";

const appearanceOptions = ["light", "dark", "system"] as const;

function PreviewPane({
  scheme,
  theme,
}: {
  scheme: ColorScheme;
  theme: ThemeName;
}) {
  return (
    <span
      className="bg-canvas flex h-full min-w-0 flex-1 gap-1.5 rounded-[var(--radius-md)] p-2"
      data-color-scheme={scheme}
      data-theme={theme}
    >
      <span className="bg-subtle h-full w-1/4 rounded-[var(--radius-sm)]" />
      <span className="flex flex-1 flex-col justify-end gap-1.5 py-1">
        <span className="bg-pressed h-1.5 w-3/4 rounded-full" />
        <span className="bg-subtle h-3 w-full rounded-full" />
      </span>
    </span>
  );
}

function AppearancePreview({
  option,
  theme,
}: {
  option: (typeof appearanceOptions)[number];
  theme: ThemeName;
}) {
  return (
    <span className="border-line-subtle bg-surface flex h-20 overflow-hidden rounded-[var(--radius-lg)] border p-1.5">
      {option === "system" ? (
        <>
          <PreviewPane scheme="light" theme={theme} />
          <PreviewPane scheme="dark" theme={theme} />
        </>
      ) : (
        <PreviewPane scheme={option} theme={theme} />
      )}
    </span>
  );
}

export function GeneralPanel() {
  const t = useTranslations("Settings");
  const { locale, pending: localePending, setLocale } = useLocalePreference();
  const {
    ready,
    theme,
    colorScheme,
    colorSchemePreference,
    setTheme,
    setColorSchemePreference,
  } = useTheme();
  const { preference: motionPreference, setPreference: setMotionPreference } =
    useMotionPreference();

  return (
    <div>
      <SettingsPanelHeader
        description={t("general.description")}
        title={t("general.title")}
      />
      <div className="max-w-2xl">
        {themeNames.length > 1 ? (
          <section aria-labelledby="theme-title">
            <h3 className="text-sm font-semibold" id="theme-title">
              {t("general.theme")}
            </h3>
            <p className="text-muted mt-1 max-w-xl text-sm">
              {t("general.themeDescription")}
            </p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 sm:gap-3">
              {themeNames.map((option) => (
                <button
                  aria-pressed={ready && theme === option}
                  className={cn(
                    "motion-control hover:bg-hover rounded-[var(--radius-xl)] p-1.5 text-left sm:p-2",
                    keyboardFocusRing,
                    theme === option && "bg-pressed",
                  )}
                  key={option}
                  onClick={() => setTheme(option)}
                  type="button"
                >
                  <span className="border-line-subtle bg-surface block h-20 overflow-hidden rounded-[var(--radius-lg)] border p-1.5">
                    <PreviewPane scheme={colorScheme} theme={option} />
                  </span>
                  <span className="mt-2 block text-center text-sm font-medium">
                    {t(`theme.options.${option}`)}
                  </span>
                </button>
              ))}
            </div>
          </section>
        ) : null}

        <section
          aria-labelledby="appearance-title"
          className={cn(
            themeNames.length > 1 && "border-line-subtle mt-8 border-t pt-7",
          )}
        >
          <h3 className="text-sm font-semibold" id="appearance-title">
            {t("general.appearance")}
          </h3>
          <div className="mt-3 grid grid-cols-3 gap-2 sm:gap-3">
            {appearanceOptions.map((option) => (
              <button
                aria-pressed={ready && colorSchemePreference === option}
                className={cn(
                  "motion-control hover:bg-hover rounded-[var(--radius-xl)] p-1.5 text-left sm:p-2",
                  keyboardFocusRing,
                  colorSchemePreference === option && "bg-pressed",
                )}
                key={option}
                onClick={() => setColorSchemePreference(option)}
                type="button"
              >
                <AppearancePreview option={option} theme={theme} />
                <span className="mt-2 block text-center text-xs font-medium sm:text-sm">
                  {t(`appearance.${option}`)}
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="border-line-subtle mt-8 border-t pt-7">
          <h3 className="text-sm font-semibold" id="motion-title">
            {t("general.motion")}
          </h3>
          <p className="text-muted mt-1 max-w-xl text-sm">
            {t("general.motionDescription")}
          </p>
          <div
            aria-labelledby="motion-title"
            className="mt-3 grid gap-2 sm:grid-cols-3"
            role="group"
          >
            {motionPreferences.map((option) => (
              <button
                aria-pressed={motionPreference === option}
                className={cn(
                  "motion-control border-line-subtle hover:bg-hover rounded-[var(--radius-lg)] border px-3 py-3 text-left",
                  keyboardFocusRing,
                  motionPreference === option && "bg-pressed border-line",
                )}
                key={option}
                onClick={() => setMotionPreference(option)}
                type="button"
              >
                <span className="block text-sm font-medium">
                  {t(`motion.${option}.label`)}
                </span>
                <span className="text-secondary mt-1 block text-xs leading-5">
                  {t(`motion.${option}.description`)}
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="border-line-subtle mt-8 border-t pt-7">
          <Field className="max-w-sm">
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
        </section>
      </div>
    </div>
  );
}
