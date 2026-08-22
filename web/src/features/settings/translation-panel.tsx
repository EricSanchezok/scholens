"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import { AsyncBoundary } from "@/components/feedback";
import {
  Button,
  Field,
  FieldControl,
  FieldDescription,
  FieldLabel,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
} from "@/components/ui";
import {
  translationPreferenceKeys,
  translationPreferenceQuery,
  updateTranslationPreferences,
} from "@/features/translation-preferences";
import {
  SettingsCard,
  SettingsCardBody,
  SettingsCardHeader,
  SettingsPanelHeader,
} from "./settings-layout";

const languages = [
  "auto",
  "en",
  "zh-CN",
  "ja",
  "ko",
  "de",
  "fr",
  "es",
] as const;
const translationSchema = z.object({
  source_language: z.string().min(2).max(32),
  target_language: z.string().min(2).max(32),
  full_translation_display: z.enum(["bilingual", "translation_only"]),
  auto_translate_selection: z.boolean(),
  translate_references: z.boolean(),
  show_translation_marker: z.boolean(),
  custom_instructions: z.string().max(4000),
});
type TranslationValues = z.infer<typeof translationSchema>;

export function TranslationPanel({
  showHeader = true,
}: {
  showHeader?: boolean;
}) {
  const t = useTranslations("Settings");
  const queryClient = useQueryClient();
  const preferences = useQuery(translationPreferenceQuery());
  const form = useForm<TranslationValues>({
    defaultValues: {
      source_language: "auto",
      target_language: "zh-CN",
      full_translation_display: "bilingual",
      auto_translate_selection: false,
      translate_references: false,
      show_translation_marker: true,
      custom_instructions: "",
    },
    resolver: zodResolver(translationSchema),
  });
  React.useEffect(() => {
    if (preferences.data) {
      form.reset({
        ...preferences.data,
        custom_instructions: preferences.data.custom_instructions ?? "",
      });
    }
  }, [form, preferences.data]);
  const mutation = useMutation({
    mutationFn: (values: TranslationValues) =>
      updateTranslationPreferences({
        ...values,
        custom_instructions: values.custom_instructions.trim() || null,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(translationPreferenceKeys.current(), data);
      form.reset({
        ...data,
        custom_instructions: data.custom_instructions ?? "",
      });
    },
  });

  return (
    <div>
      {showHeader ? (
        <SettingsPanelHeader
          description={t("translation.description")}
          title={t("translation.title")}
        />
      ) : null}
      <AsyncBoundary
        data={preferences.data}
        error={preferences.error}
        loading={preferences.isLoading}
        retry={() => void preferences.refetch()}
      >
        {() => (
          <form
            className="grid gap-5"
            onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          >
            <SettingsCard>
              <SettingsCardHeader
                description={t("translation.languagesDescription")}
                title={t("translation.languages")}
              />
              <SettingsCardBody>
                <div className="grid gap-5 sm:grid-cols-2">
                  {(["source_language", "target_language"] as const).map(
                    (name) => (
                      <Field key={name}>
                        <FieldLabel>{t(`translation.${name}`)}</FieldLabel>
                        <Controller
                          control={form.control}
                          name={name}
                          render={({ field }) => (
                            <Select
                              onValueChange={field.onChange}
                              value={field.value}
                            >
                              <FieldControl>
                                <SelectTrigger>
                                  <SelectValue />
                                </SelectTrigger>
                              </FieldControl>
                              <SelectContent>
                                {languages
                                  .filter(
                                    (language) =>
                                      name === "source_language" ||
                                      language !== "auto",
                                  )
                                  .map((language) => (
                                    <SelectItem key={language} value={language}>
                                      {t(`translation.language.${language}`)}
                                    </SelectItem>
                                  ))}
                              </SelectContent>
                            </Select>
                          )}
                        />
                      </Field>
                    ),
                  )}
                  <Field>
                    <FieldLabel>{t("translation.display")}</FieldLabel>
                    <Controller
                      control={form.control}
                      name="full_translation_display"
                      render={({ field }) => (
                        <Select
                          onValueChange={field.onChange}
                          value={field.value}
                        >
                          <FieldControl>
                            <SelectTrigger>
                              <SelectValue />
                            </SelectTrigger>
                          </FieldControl>
                          <SelectContent>
                            <SelectItem value="bilingual">
                              {t("translation.bilingual")}
                            </SelectItem>
                            <SelectItem value="translation_only">
                              {t("translation.translationOnly")}
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      )}
                    />
                  </Field>
                </div>
              </SettingsCardBody>
            </SettingsCard>

            <SettingsCard>
              <SettingsCardHeader title={t("translation.behavior")} />
              <SettingsCardBody>
                <div className="divide-line divide-y">
                  {(
                    [
                      "auto_translate_selection",
                      "translate_references",
                      "show_translation_marker",
                    ] as const
                  ).map((name) => (
                    <Controller
                      control={form.control}
                      key={name}
                      name={name}
                      render={({ field }) => (
                        <label className="flex min-h-16 items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
                          <span>
                            <span className="block text-sm font-medium">
                              {t(`translation.${name}`)}
                            </span>
                            <span className="text-secondary mt-1 block text-sm">
                              {t(`translation.${name}Description`)}
                            </span>
                          </span>
                          <Switch
                            checked={field.value}
                            onCheckedChange={field.onChange}
                          />
                        </label>
                      )}
                    />
                  ))}
                </div>
              </SettingsCardBody>
            </SettingsCard>

            <SettingsCard>
              <SettingsCardHeader title={t("translation.instructions")} />
              <SettingsCardBody>
                <Field>
                  <FieldLabel>{t("translation.customInstructions")}</FieldLabel>
                  <FieldControl>
                    <Textarea
                      rows={5}
                      {...form.register("custom_instructions")}
                    />
                  </FieldControl>
                  <FieldDescription>
                    {t("translation.instructionsDescription")}
                  </FieldDescription>
                </Field>
              </SettingsCardBody>
            </SettingsCard>
            {mutation.isError ? (
              <p className="text-danger text-sm" role="alert">
                {t("errors.save")}
              </p>
            ) : null}
            <div className="flex justify-end">
              <Button
                disabled={!form.formState.isDirty}
                loading={mutation.isPending}
                type="submit"
              >
                {t("actions.save")}
              </Button>
            </div>
          </form>
        )}
      </AsyncBoundary>
    </div>
  );
}
