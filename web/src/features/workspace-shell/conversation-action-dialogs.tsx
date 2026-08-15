"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHandle,
  DialogHeader,
  DialogTitle,
  Input,
  isImeComposing,
} from "@/components/ui";
import { conversationTitleSchema } from "@/features/conversation";
import type { components } from "@/lib/api/generated/schema";
import type { ConversationListController } from "./use-conversation-list-controller";

type ConversationSummary = components["schemas"]["ConversationSummaryResponse"];

export type ConversationDialogTarget = {
  conversation: ConversationSummary;
  returnFocus: HTMLButtonElement | null;
};

function RenameConversationDialog({
  controller,
  onClose,
  target,
}: {
  controller: ConversationListController;
  onClose: () => void;
  target: ConversationDialogTarget;
}) {
  const t = useTranslations("WorkspaceShell.sidebar");
  const [title, setTitle] = React.useState(target.conversation.title);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const restoreInputFocusRef = React.useRef(false);
  const parsedTitle = conversationTitleSchema.safeParse(title);
  const unchanged =
    parsedTitle.success &&
    parsedTitle.data === target.conversation.title.trim();
  const renaming = controller.updatingConversationId === target.conversation.id;

  React.useEffect(() => {
    if (renaming || !restoreInputFocusRef.current) return;
    inputRef.current?.focus();
    restoreInputFocusRef.current = false;
  }, [renaming]);

  async function submitRename(event: React.FormEvent) {
    event.preventDefault();
    if (!parsedTitle.success || unchanged || renaming) return;
    try {
      await controller.renameConversation(
        target.conversation,
        parsedTitle.data,
      );
      onClose();
    } catch {
      restoreInputFocusRef.current = true;
      requestAnimationFrame(() => {
        if (inputRef.current && !inputRef.current.disabled) {
          inputRef.current.focus();
          restoreInputFocusRef.current = false;
        }
      });
    }
  }

  return (
    <Dialog
      onOpenChange={(open) => {
        if (!open && !renaming) onClose();
      }}
      open
    >
      <DialogContent
        closeLabel={t("closeRename")}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          target.returnFocus?.focus();
        }}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          inputRef.current?.focus();
          inputRef.current?.select();
        }}
        placement="responsive-bottom"
      >
        <DialogHandle />
        <form
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(event) => void submitRename(event)}
        >
          <DialogHeader>
            <DialogTitle>{t("renameTitle")}</DialogTitle>
            <DialogDescription>{t("renameDescription")}</DialogDescription>
          </DialogHeader>
          <DialogBody>
            <Input
              aria-label={t("renameLabel")}
              disabled={renaming}
              maxLength={240}
              onChange={(event) => setTitle(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && isImeComposing(event)) {
                  event.preventDefault();
                }
              }}
              ref={inputRef}
              value={title}
            />
          </DialogBody>
          <DialogFooter>
            <Button
              disabled={renaming}
              onClick={onClose}
              type="button"
              variant="ghost"
            >
              {t("cancelRename")}
            </Button>
            <Button
              disabled={!parsedTitle.success || unchanged}
              loading={renaming}
              type="submit"
            >
              {t("saveRename")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ConversationActionDialogs({
  controller,
  deleteTarget,
  onDeleteTargetChange,
  onRenameTargetChange,
  renameTarget,
}: {
  controller: ConversationListController;
  deleteTarget?: ConversationDialogTarget;
  onDeleteTargetChange: (target?: ConversationDialogTarget) => void;
  onRenameTargetChange: (target?: ConversationDialogTarget) => void;
  renameTarget?: ConversationDialogTarget;
}) {
  const t = useTranslations("WorkspaceShell.sidebar");
  const deleteButtonRef = React.useRef<HTMLButtonElement>(null);
  const restoreDeleteFocusRef = React.useRef(false);
  const deleting =
    controller.deletingConversationId === deleteTarget?.conversation.id;

  React.useEffect(() => {
    if (deleting || !restoreDeleteFocusRef.current) return;
    deleteButtonRef.current?.focus();
    restoreDeleteFocusRef.current = false;
  }, [deleting]);

  async function confirmDelete() {
    if (!deleteTarget || deleting) return;
    try {
      await controller.deleteConversation(deleteTarget.conversation);
      onDeleteTargetChange(undefined);
    } catch {
      // The controller preserves the row and reports the failure.
      restoreDeleteFocusRef.current = true;
      requestAnimationFrame(() => {
        if (deleteButtonRef.current && !deleteButtonRef.current.disabled) {
          deleteButtonRef.current.focus();
          restoreDeleteFocusRef.current = false;
        }
      });
    }
  }

  return (
    <>
      {renameTarget ? (
        <RenameConversationDialog
          controller={controller}
          key={renameTarget.conversation.id}
          onClose={() => onRenameTargetChange(undefined)}
          target={renameTarget}
        />
      ) : null}

      <AlertDialog
        onOpenChange={(open) => {
          if (!open && !deleting) onDeleteTargetChange(undefined);
        }}
        open={Boolean(deleteTarget)}
      >
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            deleteTarget?.returnFocus?.focus();
          }}
        >
          <AlertDialogTitle>{t("deleteTitle")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t("deleteDescription", {
              title: deleteTarget?.conversation.title ?? "",
            })}
          </AlertDialogDescription>
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialogCancel asChild>
              <Button disabled={deleting} variant="ghost">
                {t("cancelDelete")}
              </Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                loading={deleting}
                onClick={(event) => {
                  event.preventDefault();
                  void confirmDelete();
                }}
                ref={deleteButtonRef}
                variant="danger"
              >
                {t("confirmDelete")}
              </Button>
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
