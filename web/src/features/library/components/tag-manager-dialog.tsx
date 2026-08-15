"use client";

import {
  EditIcon,
  TagIcon,
  AddIcon,
  DeleteIcon,
} from "@/design-system/icons/semantic-icons";
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
  Checkbox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHandle,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Input,
  OverflowMenuButton,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";

export type LibraryTag = components["schemas"]["LibraryTagResponse"];

export function TagManagerDialog({
  documentIds,
  initialTagIds,
  onCreate,
  onDelete,
  onOpenChange,
  onRename,
  onSave,
  open,
  tags,
}: {
  documentIds: string[];
  initialTagIds: string[];
  onCreate: (name: string) => Promise<LibraryTag>;
  onDelete: (tagId: string) => Promise<void>;
  onOpenChange: (open: boolean) => void;
  onRename: (tagId: string, name: string) => Promise<LibraryTag>;
  onSave: (documentIds: string[], tagIds: string[]) => Promise<void>;
  open: boolean;
  tags: LibraryTag[];
}) {
  const t = useTranslations("Library.papers.tagDialog");
  const common = useTranslations("Library.common");
  const assigning = documentIds.length > 0;
  const [selectedDraft, setSelectedDraft] = React.useState<string[] | null>(
    null,
  );
  const selected = selectedDraft ?? initialTagIds;
  const [newName, setNewName] = React.useState("");
  const [renamingId, setRenamingId] = React.useState<string>();
  const [renameValue, setRenameValue] = React.useState("");
  const [deleteTarget, setDeleteTarget] = React.useState<LibraryTag>();
  const [pendingAction, setPendingAction] = React.useState<
    "create" | "rename" | "delete" | "save"
  >();
  const [error, setError] = React.useState(false);

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      setSelectedDraft(null);
      setNewName("");
      setRenamingId(undefined);
      setRenameValue("");
      setDeleteTarget(undefined);
      setPendingAction(undefined);
      setError(false);
    }
    onOpenChange(nextOpen);
  }

  async function createTag(event: React.FormEvent) {
    event.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setPendingAction("create");
    setError(false);
    try {
      const created = await onCreate(name);
      setNewName("");
      if (assigning) {
        setSelectedDraft((draft) =>
          (draft ?? initialTagIds).includes(created.id)
            ? (draft ?? initialTagIds)
            : [...(draft ?? initialTagIds), created.id],
        );
      }
    } catch {
      setError(true);
    } finally {
      setPendingAction(undefined);
    }
  }

  function beginRename(tag: LibraryTag) {
    setRenamingId(tag.id);
    setRenameValue(tag.name);
    setError(false);
  }

  async function renameTag(event: React.FormEvent) {
    event.preventDefault();
    const name = renameValue.trim();
    if (!renamingId || !name) return;
    setPendingAction("rename");
    setError(false);
    try {
      await onRename(renamingId, name);
      setRenamingId(undefined);
      setRenameValue("");
    } catch {
      setError(true);
    } finally {
      setPendingAction(undefined);
    }
  }

  async function deleteTag() {
    if (!deleteTarget) return;
    setPendingAction("delete");
    setError(false);
    try {
      await onDelete(deleteTarget.id);
      setSelectedDraft((draft) =>
        (draft ?? initialTagIds).filter((id) => id !== deleteTarget.id),
      );
      setDeleteTarget(undefined);
    } catch {
      setError(true);
    } finally {
      setPendingAction(undefined);
    }
  }

  async function saveAssignments() {
    setPendingAction("save");
    setError(false);
    try {
      await onSave(documentIds, selected);
      handleOpenChange(false);
    } catch {
      setError(true);
    } finally {
      setPendingAction(undefined);
    }
  }

  return (
    <>
      <Dialog onOpenChange={handleOpenChange} open={open}>
        <DialogContent
          closeLabel={common("close")}
          placement="responsive-bottom"
        >
          <DialogHandle />
          <DialogHeader>
            <DialogTitle>
              {assigning ? t("title") : t("manageTitle")}
            </DialogTitle>
            <DialogDescription>
              {assigning
                ? t("description", { count: documentIds.length })
                : t("manageDescription")}
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="grid gap-5">
            <form className="flex gap-2" onSubmit={createTag}>
              <Input
                aria-label={t("newLabel")}
                className="min-w-0 flex-1"
                maxLength={64}
                onChange={(event) => setNewName(event.currentTarget.value)}
                placeholder={t("newPlaceholder")}
                value={newName}
              />
              <Button
                disabled={!newName.trim()}
                loading={pendingAction === "create"}
                size="sm"
                type="submit"
                variant="secondary"
              >
                <Icon glyph={AddIcon} size={20} />
                {t("create")}
              </Button>
            </form>

            <div
              aria-label={t("listLabel")}
              className="border-line divide-line divide-y overflow-hidden rounded-[var(--radius-lg)] border"
              role="group"
            >
              {tags.map((tag) =>
                renamingId === tag.id ? (
                  <form
                    className="flex min-h-14 items-center gap-2 p-2"
                    key={tag.id}
                    onSubmit={renameTag}
                  >
                    <Input
                      aria-label={t("renameLabel", { name: tag.name })}
                      autoFocus
                      className="min-w-0 flex-1"
                      maxLength={64}
                      onChange={(event) =>
                        setRenameValue(event.currentTarget.value)
                      }
                      value={renameValue}
                    />
                    <Button
                      disabled={!renameValue.trim()}
                      loading={pendingAction === "rename"}
                      size="sm"
                      type="submit"
                    >
                      {t("saveRename")}
                    </Button>
                    <Button
                      onClick={() => setRenamingId(undefined)}
                      size="sm"
                      type="button"
                      variant="ghost"
                    >
                      {common("cancel")}
                    </Button>
                  </form>
                ) : (
                  <div
                    className="motion-control group/interactive-row hover:bg-hover focus-within:bg-hover active:bg-pressed flex min-h-14 items-center gap-3 px-3"
                    key={tag.id}
                  >
                    {assigning ? (
                      <Checkbox
                        aria-label={tag.name}
                        checked={selected.includes(tag.id)}
                        onCheckedChange={(checked) =>
                          setSelectedDraft((draft) =>
                            checked === true
                              ? (draft ?? initialTagIds).includes(tag.id)
                                ? (draft ?? initialTagIds)
                                : [...(draft ?? initialTagIds), tag.id]
                              : (draft ?? initialTagIds).filter(
                                  (id) => id !== tag.id,
                                ),
                          )
                        }
                      />
                    ) : (
                      <span className="grid size-5 shrink-0 place-items-center">
                        <Icon glyph={TagIcon} size={20} tone="secondary" />
                      </span>
                    )}
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">
                      {tag.name}
                    </span>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <OverflowMenuButton
                          label={t("actionsLabel", { name: tag.name })}
                          visibility="contextual"
                        />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => beginRename(tag)}>
                          <Icon glyph={EditIcon} size={16} tone="secondary" />
                          {t("rename")}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          destructive
                          onSelect={() => setDeleteTarget(tag)}
                        >
                          <Icon glyph={DeleteIcon} size={16} tone="secondary" />
                          {t("delete")}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                ),
              )}
              {tags.length === 0 && (
                <div className="px-5 py-10 text-center">
                  <p className="text-sm font-medium">{t("emptyTitle")}</p>
                  <p className="text-secondary mt-1 text-sm">
                    {t("emptyDescription")}
                  </p>
                </div>
              )}
            </div>
            {assigning && documentIds.length > 1 && (
              <p className="text-secondary text-xs">{t("multiHint")}</p>
            )}
            {error && (
              <p className="text-danger text-sm" role="alert">
                {t("error")}
              </p>
            )}
          </DialogBody>

          <DialogFooter>
            <Button onClick={() => handleOpenChange(false)} variant="ghost">
              {assigning ? common("cancel") : t("done")}
            </Button>
            {assigning && (
              <Button
                loading={pendingAction === "save"}
                onClick={() => void saveAssignments()}
              >
                {t("submit")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        onOpenChange={(nextOpen) => !nextOpen && setDeleteTarget(undefined)}
        open={Boolean(deleteTarget)}
      >
        <AlertDialogContent>
          <AlertDialogTitle>{t("deleteTitle")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t("deleteDescription", { name: deleteTarget?.name ?? "" })}
          </AlertDialogDescription>
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialogCancel asChild>
              <Button variant="ghost">{common("cancel")}</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                loading={pendingAction === "delete"}
                onClick={(event) => {
                  event.preventDefault();
                  void deleteTag();
                }}
                variant="danger"
              >
                {t("deleteConfirm")}
              </Button>
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
