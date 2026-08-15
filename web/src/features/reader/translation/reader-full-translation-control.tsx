"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import {
  Button,
  Label,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  Switch,
  Textarea,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { TranslationIcon } from "@/design-system/icons/semantic-icons";
import { cn } from "@/lib/utilities/cn";
import { useDesktopReaderToolbar } from "../hooks/use-reader-layout";
import type { TranslationPreferences } from "./api";
import { TranslationLanguageSelect } from "./reader-translation-panel";

export type FullTranslationStatus =
  "idle" | "translating" | "partial" | "complete";

function SettingRow({
  checked,
  description,
  disabled,
  label,
  onCheckedChange,
}: {
  checked: boolean;
  description?: string;
  disabled: boolean;
  label: string;
  onCheckedChange: (checked: boolean) => void;
}) {
  const id = React.useId();
  return (
    <div className="flex items-start justify-between gap-5 py-2">
      <div className="min-w-0">
        <Label htmlFor={id}>{label}</Label>
        {description ? (
          <p className="text-muted mt-0.5 text-xs leading-5">{description}</p>
        ) : null}
      </div>
      <Switch
        checked={checked}
        className="mt-0.5 shrink-0"
        disabled={disabled}
        id={id}
        onCheckedChange={onCheckedChange}
      />
    </div>
  );
}

function TranslationSettings({
  enabled,
  onEnabledChange,
  onPreferencesChange,
  preferences,
  saving,
}: {
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  onPreferencesChange: (
    patch: Partial<TranslationPreferences>,
  ) => Promise<unknown>;
  preferences?: TranslationPreferences;
  saving: boolean;
}) {
  const t = useTranslations("Reader.fullTranslation");
  const [instructions, setInstructions] = React.useState(
    preferences?.custom_instructions ?? "",
  );

  const update = React.useCallback(
    (patch: Partial<TranslationPreferences>) => {
      void onPreferencesChange(patch).catch(() => undefined);
    },
    [onPreferencesChange],
  );
  const disabled = saving || !preferences;

  return (
    <div className="grid gap-3">
      <SettingRow
        checked={enabled}
        description={t("enableDescription")}
        disabled={disabled}
        label={t("enable")}
        onCheckedChange={onEnabledChange}
      />

      <div className="border-line grid gap-4 border-t pt-4">
        <TranslationLanguageSelect
          disabled={disabled}
          label={t("targetLanguage")}
          onChange={(target_language) => update({ target_language })}
          value={preferences?.target_language ?? "zh-CN"}
        />

        <div className="grid gap-2">
          <Label>{t("display.label")}</Label>
          <Select
            disabled={disabled}
            onValueChange={(value) =>
              update({
                full_translation_display: value as
                  "bilingual" | "translation_only",
              })
            }
            value={preferences?.full_translation_display ?? "bilingual"}
          >
            <SelectTrigger aria-label={t("display.label")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="bilingual">
                {t("display.bilingual")}
              </SelectItem>
              <SelectItem value="translation_only">
                {t("display.translationOnly")}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <SettingRow
          checked={preferences?.translate_references ?? false}
          disabled={disabled}
          label={t("translateReferences")}
          onCheckedChange={(translate_references) =>
            update({ translate_references })
          }
        />
        <SettingRow
          checked={preferences?.show_translation_marker ?? true}
          disabled={disabled}
          label={t("showMarker")}
          onCheckedChange={(show_translation_marker) =>
            update({ show_translation_marker })
          }
        />

        <details className="border-line border-t pt-3">
          <summary className="cursor-pointer text-sm font-medium">
            {t("instructions.title")}
          </summary>
          <div className="mt-3 grid gap-3">
            <Textarea
              aria-label={t("instructions.label")}
              className="min-h-20"
              maxLength={2_000}
              onChange={(event) => setInstructions(event.currentTarget.value)}
              placeholder={t("instructions.placeholder")}
              value={instructions}
            />
            <Button
              className="justify-self-start"
              disabled={
                disabled ||
                instructions.trim() === (preferences?.custom_instructions ?? "")
              }
              onClick={() =>
                update({ custom_instructions: instructions.trim() || null })
              }
              size="sm"
              variant="secondary"
            >
              {t("instructions.save")}
            </Button>
          </div>
        </details>
      </div>
    </div>
  );
}

export function ReaderFullTranslationControl({
  enabled,
  onEnabledChange,
  onPreferencesChange,
  preferences,
  saving,
  status,
}: {
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  onPreferencesChange: (
    patch: Partial<TranslationPreferences>,
  ) => Promise<unknown>;
  preferences?: TranslationPreferences;
  saving: boolean;
  status: FullTranslationStatus;
}) {
  const t = useTranslations("Reader.fullTranslation");
  const desktop = useDesktopReaderToolbar();
  const [open, setOpen] = React.useState(false);
  const statusLabel = t(`status.${status}`);
  const trigger = (
    <Button
      aria-label={`${t("title")}: ${statusLabel}`}
      aria-pressed={enabled}
      className="relative gap-2 px-2.5"
      onClick={() => setOpen(true)}
      size="sm"
      variant={enabled ? "secondary" : "ghost"}
    >
      <Icon glyph={TranslationIcon} size={20} />
      <span className="hidden xl:inline">{t("title")}</span>
      {enabled && status !== "idle" ? (
        <span
          aria-hidden
          className={cn(
            "absolute top-1 right-1 size-1.5 rounded-full",
            status === "partial" ? "bg-danger" : "bg-success",
            status === "translating" && "animate-pulse",
          )}
        />
      ) : null}
    </Button>
  );

  const settings = (
    <TranslationSettings
      enabled={enabled}
      key={preferences?.custom_instructions ?? "default-instructions"}
      onEnabledChange={onEnabledChange}
      onPreferencesChange={onPreferencesChange}
      preferences={preferences}
      saving={saving}
    />
  );

  if (desktop) {
    return (
      <Popover onOpenChange={setOpen} open={open}>
        <PopoverTrigger asChild>{trigger}</PopoverTrigger>
        <PopoverContent
          align="end"
          aria-label={t("title")}
          className="w-[22rem] p-4"
        >
          <div className="mb-3">
            <p className="font-medium">{t("title")}</p>
            <p className="text-muted mt-0.5 text-xs leading-5">{statusLabel}</p>
          </div>
          {settings}
        </PopoverContent>
      </Popover>
    );
  }

  return (
    <Sheet onOpenChange={setOpen} open={open}>
      {trigger}
      <SheetContent
        className="inset-x-0 top-auto bottom-0 h-auto max-h-[88dvh] w-full max-w-none overflow-y-auto rounded-t-[var(--radius-xl)] border-t border-l-0 px-5 pt-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]"
        closeLabel={t("close")}
      >
        <SheetTitle className="pr-12 text-lg font-semibold">
          {t("title")}
        </SheetTitle>
        <SheetDescription className="text-muted mt-1 text-sm">
          {statusLabel}
        </SheetDescription>
        <div className="mt-4">{settings}</div>
      </SheetContent>
    </Sheet>
  );
}
