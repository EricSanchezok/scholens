"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { useCopyActionFeedback } from "@/components/feedback";
import {
  Button,
  Field,
  FieldControl,
  FieldDescription,
  FieldLabel,
  focusSurfaceVariants,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
} from "@/components/ui";
import {
  AddAnnotationIcon,
  CopyIcon,
  RetryIcon,
  TranslationIcon,
} from "@/design-system/icons/semantic-icons";
import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import type { ReaderSelection } from "../reader-selection";
import type { TranslationPreferences } from "./api";
import type { SelectionTranslationState } from "./use-reader-translation";
import { translationErrorMessageKey } from "./translation-errors";

export const translationLanguageCodes = [
  "en",
  "zh-CN",
  "zh-TW",
  "ja",
  "ko",
  "de",
  "fr",
  "es",
] as const;

const instructionsSchema = z.object({
  customInstructions: z.string().max(2_000),
});

type InstructionsValues = z.infer<typeof instructionsSchema>;

export function TranslationLanguageSelect({
  allowAuto,
  disabled,
  label,
  onChange,
  value,
}: {
  allowAuto?: boolean;
  disabled?: boolean;
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const t = useTranslations("Reader.translation");
  const triggerId = React.useId();
  const valueLabel =
    value === "auto"
      ? t("languages.auto")
      : t(`languages.${value as (typeof translationLanguageCodes)[number]}`);
  return (
    <div className="grid gap-2">
      <Label htmlFor={triggerId}>{label}</Label>
      <Select disabled={disabled} onValueChange={onChange} value={value}>
        <SelectTrigger aria-label={label} id={triggerId}>
          <SelectValue>{valueLabel}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {allowAuto ? (
            <SelectItem value="auto">{t("languages.auto")}</SelectItem>
          ) : null}
          {translationLanguageCodes.map((code) => (
            <SelectItem key={code} value={code}>
              {t(`languages.${code}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function TranslationResult({
  onAnnotate,
  onRetry,
  state,
}: {
  onAnnotate: (selection: ReaderSelection, translatedText: string) => void;
  onRetry: () => void;
  state: SelectionTranslationState;
}) {
  const t = useTranslations("Reader.translation");
  const copyFeedback = useCopyActionFeedback({
    labels: {
      idle: t("actions.copy"),
      pending: t("actions.copying"),
      success: t("actions.copied"),
      error: t("actions.copyFailed"),
    },
    value: state.translatedText,
  });
  const selectedTranslation = state.selection;

  if (state.status === "idle") {
    return (
      <div className="grid min-h-56 place-items-center px-7 py-10 text-center">
        <div>
          <span className="bg-subtle mx-auto grid size-11 place-items-center rounded-full">
            <Icon glyph={TranslationIcon} size={20} tone="secondary" />
          </span>
          <p className="mt-4 text-sm font-medium">{t("empty.title")}</p>
          <p className="text-muted mx-auto mt-1 max-w-xs text-sm">
            {t("empty.description")}
          </p>
        </div>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="border-line bg-surface rounded-[var(--radius-lg)] border p-4">
        <p
          aria-atomic="true"
          aria-live="polite"
          className="text-sm font-medium"
          role="status"
        >
          {t("errors.title")}
        </p>
        <p className="text-muted mt-1 text-sm">
          {t(translationErrorMessageKey(state.errorCode))}
        </p>
        {state.retryable ? (
          <Button
            className="mt-4"
            onClick={onRetry}
            size="sm"
            variant="secondary"
          >
            <Icon glyph={RetryIcon} size={16} />
            {t("actions.retry")}
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      <div className="border-line bg-subtle rounded-[var(--radius-lg)] border p-4">
        <p className="text-muted text-xs font-medium tracking-wide uppercase">
          {t("selectedText")}
        </p>
        <p
          className={cn(
            "text-secondary mt-2 max-h-32 overflow-y-auto text-sm leading-6",
            focusSurfaceVariants({ intent: "scroll" }),
          )}
          tabIndex={0}
        >
          {state.selection?.selected_text}
        </p>
      </div>
      {state.status === "ready" ? (
        <div className="border-line bg-surface grid min-h-44 place-items-center rounded-[var(--radius-lg)] border p-6 text-center">
          <div>
            <p className="text-sm font-medium">{t("ready.title")}</p>
            <p className="text-muted mt-1 text-sm">{t("ready.description")}</p>
          </div>
        </div>
      ) : (
        <div
          aria-busy={state.status === "streaming"}
          className="border-line bg-surface min-h-44 rounded-[var(--radius-lg)] border p-4"
        >
          <div className="flex items-center justify-between gap-3">
            <p
              aria-atomic="true"
              aria-live="polite"
              className="text-muted text-xs font-medium tracking-wide uppercase"
              role="status"
            >
              {state.status === "streaming"
                ? t("status.translating")
                : t("status.completed")}
            </p>
            {state.cacheHit ? (
              <span className="text-muted text-xs">{t("status.cached")}</span>
            ) : null}
          </div>
          <p className="mt-3 text-[0.9375rem] leading-7 whitespace-pre-wrap">
            {state.translatedText}
            {state.status === "streaming" ? (
              <span
                aria-hidden
                className="motion-skeleton bg-primary ml-1 inline-block h-4 w-0.5 align-middle"
              />
            ) : null}
          </p>
        </div>
      )}
      {state.status === "completed" ? (
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={copyFeedback.status === "pending"}
            onClick={() => void copyFeedback.copy()}
            size="sm"
            variant="secondary"
          >
            <Icon glyph={CopyIcon} size={16} />
            {copyFeedback.label}
          </Button>
          {selectedTranslation ? (
            <Button
              onClick={() =>
                onAnnotate(selectedTranslation, state.translatedText)
              }
              size="sm"
              variant="secondary"
            >
              <Icon glyph={AddAnnotationIcon} size={16} />
              {t("actions.annotate")}
            </Button>
          ) : null}
          <span aria-live="polite" className="sr-only">
            {copyFeedback.feedbackVisible ? copyFeedback.label : ""}
          </span>
        </div>
      ) : null}
    </div>
  );
}

export function ReaderTranslationPanel({
  className,
  onAnnotate,
  onPreferencesChange,
  onRetry,
  onTranslate,
  preferences,
  preferencesError,
  preferencesLoading,
  preferencesSaving,
  state,
}: {
  className?: string;
  onAnnotate: (selection: ReaderSelection, translatedText: string) => void;
  onPreferencesChange: (
    patch: Partial<TranslationPreferences>,
  ) => Promise<unknown>;
  onRetry: () => void;
  onTranslate: () => void;
  preferences?: TranslationPreferences;
  preferencesError?: unknown;
  preferencesLoading: boolean;
  preferencesSaving: boolean;
  state: SelectionTranslationState;
}) {
  const t = useTranslations("Reader.translation");
  const autoSelectionId = React.useId();
  const form = useForm<InstructionsValues>({
    defaultValues: {
      customInstructions: preferences?.custom_instructions ?? "",
    },
    resolver: zodResolver(instructionsSchema),
  });

  React.useEffect(() => {
    form.reset({ customInstructions: preferences?.custom_instructions ?? "" });
  }, [form, preferences?.custom_instructions]);

  const disabled = preferencesLoading || preferencesSaving || !preferences;
  const savePreferences = React.useCallback(
    (patch: Partial<TranslationPreferences>) => {
      void onPreferencesChange(patch).catch(() => undefined);
    },
    [onPreferencesChange],
  );

  return (
    <div
      className={cn(
        "h-full overflow-y-auto",
        focusSurfaceVariants({ intent: "scroll" }),
        className,
      )}
      tabIndex={0}
    >
      <div className="grid gap-5 p-4 sm:p-5">
        <div className="grid grid-cols-1 gap-3 min-[26rem]:grid-cols-2">
          <TranslationLanguageSelect
            allowAuto
            disabled={disabled}
            label={t("sourceLanguage")}
            onChange={(source_language) => savePreferences({ source_language })}
            value={preferences?.source_language ?? "auto"}
          />
          <TranslationLanguageSelect
            disabled={disabled}
            label={t("targetLanguage")}
            onChange={(target_language) => savePreferences({ target_language })}
            value={preferences?.target_language ?? "zh-CN"}
          />
        </div>

        <div className="border-line flex items-start justify-between gap-4 border-y py-4">
          <div>
            <label className="text-sm font-medium" htmlFor={autoSelectionId}>
              {t("autoSelection.title")}
            </label>
            <p className="text-muted mt-1 text-sm">
              {t("autoSelection.description")}
            </p>
          </div>
          <Switch
            checked={preferences?.auto_translate_selection ?? true}
            disabled={disabled}
            id={autoSelectionId}
            onCheckedChange={(auto_translate_selection) =>
              savePreferences({ auto_translate_selection })
            }
          />
        </div>

        {preferencesError ? (
          <p className="text-danger text-sm" role="alert">
            {t("preferencesError")}
          </p>
        ) : null}

        <TranslationResult
          onAnnotate={onAnnotate}
          onRetry={onRetry}
          state={state}
        />

        {state.status === "ready" ? (
          <Button onClick={onTranslate}>
            <Icon glyph={TranslationIcon} size={20} />
            {t("actions.translate")}
          </Button>
        ) : null}

        <details className="border-line border-t pt-4">
          <summary
            className={cn(
              "cursor-pointer rounded-[var(--radius-sm)] text-sm font-medium",
              focusSurfaceVariants({ intent: "neutral" }),
            )}
          >
            {t("instructions.title")}
          </summary>
          <form
            className="mt-4 grid gap-3"
            onSubmit={form.handleSubmit(async ({ customInstructions }) => {
              await onPreferencesChange({
                custom_instructions: customInstructions.trim() || null,
              }).catch(() => undefined);
            })}
          >
            <Field>
              <FieldLabel>{t("instructions.label")}</FieldLabel>
              <FieldControl>
                <Textarea
                  maxLength={2_000}
                  placeholder={t("instructions.placeholder")}
                  {...form.register("customInstructions")}
                />
              </FieldControl>
              <FieldDescription>
                {t("instructions.description")}
              </FieldDescription>
            </Field>
            <Button
              className="justify-self-start"
              disabled={!form.formState.isDirty}
              loading={preferencesSaving}
              size="sm"
              type="submit"
              variant="secondary"
            >
              {t("instructions.save")}
            </Button>
          </form>
        </details>
      </div>
    </div>
  );
}
