"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm, useWatch } from "react-hook-form";

import { CopyActionButton } from "@/components/feedback";
import { Button, IconButton, keyboardFocusRing } from "@/components/ui";
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
  const value = useWatch({ control: form.control, name: "message" });

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
        className="border-line bg-subtle ml-auto grid w-full gap-3 rounded-[var(--radius-xl)] border p-3 sm:p-4 lg:max-w-[80%]"
        onSubmit={form.handleSubmit(save)}
      >
        <textarea
          aria-label={t("editMessageLabel")}
          className={cn(
            "placeholder:text-muted min-h-24 w-full resize-y bg-transparent px-1 py-1 text-base leading-6 outline-none lg:min-h-20 lg:text-sm",
            keyboardFocusRing,
          )}
          disabled={saving}
          maxLength={20_000}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              if (!saving) cancel();
            }
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              void form.handleSubmit(save)();
            }
          }}
          {...form.register("message")}
        />
        {saveFailed ? (
          <p aria-live="polite" className="text-danger text-sm" role="alert">
            {t("editMessageFailed")}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button
            disabled={saving}
            onClick={cancel}
            size="sm"
            type="button"
            variant="ghost"
          >
            {t("cancelEdit")}
          </Button>
          <Button
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
        className="grid min-h-11 grid-cols-[1fr_auto_1fr] items-center lg:min-h-8"
        role="group"
      >
        {hasBranches ? (
          <div className="text-secondary col-start-2 flex h-11 items-center lg:h-8">
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
        <div
          className="col-start-3 flex justify-self-end transition-opacity motion-reduce:transition-none [@media(hover:hover)]:lg:opacity-0 [@media(hover:hover)]:lg:group-focus-within/user-message:opacity-100 [@media(hover:hover)]:lg:group-hover/user-message:opacity-100"
          data-user-message-controls
        >
          <CopyActionButton
            className="size-11 bg-transparent lg:size-8 lg:min-h-8"
            errorLabel={t("copyMessageFailed")}
            label={t("copyMessage")}
            pendingLabel={t("copyingMessage")}
            successLabel={t("messageCopied")}
            value={message}
          />
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
        </div>
      </footer>
    </article>
  );
}
