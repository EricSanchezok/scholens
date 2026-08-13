"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHandle,
  DialogHeader,
  DialogTitle,
  Field,
  FieldControl,
  FieldLabel,
  FieldMessage,
  Input,
  Textarea,
} from "@/components/ui";

const projectFormSchema = z.object({
  title: z.string().trim().min(1).max(240),
  description: z.string().trim().max(10_000),
});

type ProjectFormValues = z.infer<typeof projectFormSchema>;

export function ProjectFormDialog({
  initialValue,
  mode,
  onOpenChange,
  onSubmit,
  open,
}: {
  initialValue?: ProjectFormValues;
  mode: "create" | "edit";
  onOpenChange: (open: boolean) => void;
  onSubmit: (value: {
    title: string;
    description: string | null;
  }) => Promise<unknown>;
  open: boolean;
}) {
  const t = useTranslations("Projects.form");
  const form = useForm<ProjectFormValues>({
    defaultValues: initialValue ?? { title: "", description: "" },
    resolver: zodResolver(projectFormSchema),
  });

  React.useEffect(() => {
    if (open) form.reset(initialValue ?? { title: "", description: "" });
  }, [form, initialValue, open]);

  async function submit(values: ProjectFormValues) {
    try {
      await onSubmit({
        title: values.title,
        description: values.description || null,
      });
      onOpenChange(false);
    } catch {
      form.setError("root", { message: t("error") });
    }
  }

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent closeLabel={t("close")} placement="responsive-bottom">
        <DialogHandle />
        <DialogHeader>
          <DialogTitle>{t(`${mode}.title`)}</DialogTitle>
          <DialogDescription>{t(`${mode}.description`)}</DialogDescription>
        </DialogHeader>
        <form onSubmit={form.handleSubmit(submit)}>
          <DialogBody className="grid gap-5">
            <Field invalid={Boolean(form.formState.errors.title)}>
              <FieldLabel>{t("fields.title")}</FieldLabel>
              <FieldControl>
                <Input
                  autoComplete="off"
                  maxLength={240}
                  {...form.register("title")}
                />
              </FieldControl>
              {form.formState.errors.title && (
                <FieldMessage>{t("fields.titleError")}</FieldMessage>
              )}
            </Field>
            <Field invalid={Boolean(form.formState.errors.description)}>
              <FieldLabel>{t("fields.description")}</FieldLabel>
              <FieldControl>
                <Textarea
                  maxLength={10_000}
                  {...form.register("description")}
                />
              </FieldControl>
              <FieldMessage>{t("fields.descriptionHint")}</FieldMessage>
            </Field>
            {form.formState.errors.root && (
              <p aria-live="polite" className="text-danger text-sm">
                {form.formState.errors.root.message}
              </p>
            )}
          </DialogBody>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                {t("cancel")}
              </Button>
            </DialogClose>
            <Button loading={form.formState.isSubmitting} type="submit">
              {t(`${mode}.action`)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
