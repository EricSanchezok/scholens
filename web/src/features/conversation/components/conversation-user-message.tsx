"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm, useWatch } from "react-hook-form";

import { CopyActionButton } from "@/components/feedback";
import {
  Button,
  focusSurfaceVariants,
  IconButton,
  isImeComposing,
  useTextControlFocus,
} from "@/components/ui";
import {
  EditIcon,
  NextIcon,
  PreviousIcon,
} from "@/design-system/icons/semantic-icons";
import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { composerSchema, type ComposerValues } from "../schemas";

export type PromptBranch = {
  index: number;
  count: number;
  previous_turn_id?: string | null;
  next_turn_id?: string | null;
};

export function ConversationUserMessage({
  branch,
  canEdit,
  message,
  onEdit,
  onSelectBranch,
}: {
  branch: PromptBranch;
  canEdit: boolean;
  message: string;
  onEdit: (message: string) => Promise<void>;
  onSelectBranch: (turnId: string) => void;
}) {
  const t = useTranslations("Home.conversation");
  const [editing, setEditing] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [saveFailed, setSaveFailed] = React.useState(false);
  const form = useForm<ComposerValues>({
    defaultValues: { message },
    mode: "onChange",
    resolver: zodResolver(composerSchema),
  });
  const messageRegistration = form.register("message");
  const value = useWatch({ control: form.control, name: "message" });
  const { focusHandlers, focusOrigin } =
    useTextControlFocus<HTMLTextAreaElement>({
      onBlur: messageRegistration.onBlur,
    });

  React.useEffect(() => {
    if (!editing) form.reset({ message });
  }, [editing, form, message]);

  React.useEffect(() => {
    if (editing) form.setFocus("message");
  }, [editing, form]);

  React.useEffect(() => {
    if (editing && saveFailed && !saving) form.setFocus("message");
  }, [editing, form, saveFailed, saving]);

  function cancel() {
    form.reset({ message });
    setEditing(false);
    setSaveFailed(false);
  }

  async function save(values: ComposerValues) {
    const nextMessage = values.message.trim();
    if (nextMessage === message.trim()) return;
    setSaving(true);
    setSaveFailed(false);
    try {
      await onEdit(nextMessage);
      setEditing(false);
    } catch {
      setSaveFailed(true);
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <form
        aria-label={t("editMessageForm")}
        className={cn(
          "border-line bg-subtle ml-auto flex w-full flex-col gap-3 rounded-[var(--radius-2xl)] border px-4 pt-3 pb-2 lg:max-w-[80%]",
          focusSurfaceVariants({ intent: "neutral" }),
        )}
        data-focus-surface
        onSubmit={form.handleSubmit(save)}
      >
        <textarea
          aria-label={t("editMessageLabel")}
          className="placeholder:text-muted [field-sizing:content] max-h-72 min-h-12 w-full resize-none overflow-y-auto border-0 bg-transparent p-0 text-base leading-6 lg:text-sm"
          data-focus-delegate="surface"
          data-focus-origin={focusOrigin ?? undefined}
          disabled={saving}
          maxLength={20_000}
          onKeyDown={(event) => {
            if (event.key === "Escape" && !isImeComposing(event)) {
              event.preventDefault();
              if (!saving) cancel();
            }
            if (
              event.key === "Enter" &&
              (event.metaKey || event.ctrlKey) &&
              !isImeComposing(event)
            ) {
              event.preventDefault();
              void form.handleSubmit(save)();
            }
          }}
          {...messageRegistration}
          {...focusHandlers}
        />
        {saveFailed ? (
          <p aria-live="polite" className="text-danger text-sm" role="alert">
            {t("editMessageFailed")}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button
            className="rounded-full px-4"
            disabled={saving}
            onClick={cancel}
            size="sm"
            type="button"
            variant="ghost"
          >
            {t("cancelEdit")}
          </Button>
          <Button
            className="rounded-full px-4"
            disabled={
              saving ||
              !form.formState.isValid ||
              value.trim() === message.trim()
            }
            size="sm"
            type="submit"
          >
            {t(saving ? "savingEdit" : "saveEdit")}
          </Button>
        </div>
      </form>
    );
  }

  const hasBranches = branch.count > 1;
  return (
    <article
      aria-label={t("userMessage")}
      className="group/user-message ml-auto w-fit max-w-[86%] lg:max-w-[80%]"
    >
      <p className="bg-subtle rounded-[var(--radius-xl)] px-4 py-3 text-base leading-6 [overflow-wrap:anywhere] lg:rounded-[var(--radius-lg)] lg:text-sm">
        {message}
      </p>
      <footer
        aria-label={t("userMessageActions")}
        className="flex min-h-11 items-center justify-end lg:min-h-8"
        role="group"
      >
        <div
          className="motion-control flex [@media(hover:hover)]:lg:opacity-0 [@media(hover:hover)]:lg:group-focus-within/user-message:opacity-100 [@media(hover:hover)]:lg:group-hover/user-message:opacity-100"
          data-user-message-controls
        >
          {canEdit ? (
            <IconButton
              className="size-11 bg-transparent lg:size-8 lg:min-h-8"
              label={t("editMessage")}
              onClick={() => setEditing(true)}
              variant="ghost"
            >
              <Icon glyph={EditIcon} size={16} tone="secondary" />
            </IconButton>
          ) : null}
          <CopyActionButton
            className="size-11 bg-transparent lg:size-8 lg:min-h-8"
            errorLabel={t("copyMessageFailed")}
            label={t("copyMessage")}
            pendingLabel={t("copyingMessage")}
            successLabel={t("messageCopied")}
            value={message}
          />
        </div>
        {hasBranches ? (
          <div className="text-secondary flex h-11 items-center lg:h-8">
            <IconButton
              className="size-11 bg-transparent disabled:bg-transparent disabled:opacity-100 lg:size-8 lg:min-h-8"
              disabled={!branch.previous_turn_id}
              label={t("previousPrompt")}
              onClick={() =>
                branch.previous_turn_id &&
                onSelectBranch(branch.previous_turn_id)
              }
              variant="ghost"
            >
              <Icon glyph={PreviousIcon} size={20} tone="secondary" />
            </IconButton>
            <span
              aria-label={t("promptVersion", {
                current: branch.index,
                total: branch.count,
              })}
              className="text-foreground min-w-10 text-center text-sm font-medium tabular-nums"
            >
              {branch.index} / {branch.count}
            </span>
            <IconButton
              className="size-11 bg-transparent disabled:bg-transparent disabled:opacity-100 lg:size-8 lg:min-h-8"
              disabled={!branch.next_turn_id}
              label={t("nextPrompt")}
              onClick={() =>
                branch.next_turn_id && onSelectBranch(branch.next_turn_id)
              }
              variant="ghost"
            >
              <Icon glyph={NextIcon} size={20} tone="secondary" />
            </IconButton>
          </div>
        ) : null}
      </footer>
    </article>
  );
}
