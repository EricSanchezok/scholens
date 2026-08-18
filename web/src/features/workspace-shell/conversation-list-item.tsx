"use client";

import Link from "next/link";
import type { Route } from "next";
import { useTranslations } from "next-intl";
import * as React from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  IconButton,
  Input,
  isImeComposing,
  keyboardFocusRing,
  OverflowMenuButton,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  ConfirmIcon,
  DeleteIcon,
  DismissIcon,
  EditIcon,
  LinkIcon,
  PinIcon,
} from "@/design-system/icons/semantic-icons";
import { conversationTitleSchema } from "@/features/conversation";
import type { components } from "@/lib/api/generated/schema";
import { useRelativeTimeNow } from "@/i18n/use-relative-time-now";
import { cn } from "@/lib/utilities/cn";

type ConversationSummary = components["schemas"]["ConversationSummaryResponse"];

export function ConversationListItem({
  conversation,
  current,
  href,
  mobile = false,
  pending,
  onDelete,
  onNavigate,
  onRename,
  onRequestMobileRename,
  onTogglePinned,
}: {
  conversation: ConversationSummary;
  current: boolean;
  href: string;
  mobile?: boolean;
  pending: boolean;
  onDelete: (returnFocus: HTMLButtonElement | null) => void;
  onNavigate?: () => void;
  onRename: (title: string) => Promise<void>;
  onRequestMobileRename: (returnFocus: HTMLButtonElement | null) => void;
  onTogglePinned: () => Promise<void>;
}) {
  const t = useTranslations("WorkspaceShell.sidebar");
  const formatRelativeTime = useRelativeTimeNow();
  const [editing, setEditing] = React.useState(false);
  const [title, setTitle] = React.useState(conversation.title);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const formRef = React.useRef<HTMLFormElement>(null);
  const overflowButtonRef = React.useRef<HTMLButtonElement>(null);
  const restoreInputFocusRef = React.useRef(false);
  const restoreOverflowFocusRef = React.useRef(false);

  React.useEffect(() => {
    if (!editing) return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [editing]);

  React.useEffect(() => {
    if (!editing || pending || !restoreInputFocusRef.current) return;
    inputRef.current?.focus();
    restoreInputFocusRef.current = false;
  }, [editing, pending]);

  React.useLayoutEffect(() => {
    if (editing || pending || !restoreOverflowFocusRef.current) return;
    const trigger = overflowButtonRef.current;
    if (!trigger) return;
    trigger.focus();
    restoreOverflowFocusRef.current = false;
  }, [editing, pending]);

  const parsedTitle = conversationTitleSchema.safeParse(title);
  const unchanged =
    parsedTitle.success && parsedTitle.data === conversation.title.trim();

  async function submitRename(event: React.FormEvent) {
    event.preventDefault();
    if (!parsedTitle.success || unchanged || pending) return;
    try {
      await onRename(parsedTitle.data);
      restoreOverflowFocusRef.current = true;
      setEditing(false);
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

  function cancelRename(restoreFocus = true) {
    if (pending) return;
    restoreInputFocusRef.current = false;
    setTitle(conversation.title);
    restoreOverflowFocusRef.current = restoreFocus;
    setEditing(false);
  }

  const actions = (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <OverflowMenuButton
          disabled={pending}
          label={t("openActions", { title: conversation.title })}
          ref={overflowButtonRef}
          visibility={mobile ? "always" : "contextual"}
        />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuItem asChild>
          <Link href={href as Route} rel="noopener noreferrer" target="_blank">
            <Icon glyph={LinkIcon} size={16} tone="secondary" />
            {t("openNewTab")}
          </Link>
        </DropdownMenuItem>
        {conversation.capabilities.rename && (
          <DropdownMenuItem
            onSelect={() => {
              if (mobile) onRequestMobileRename(overflowButtonRef.current);
              else {
                setTitle(conversation.title);
                setEditing(true);
              }
            }}
          >
            <Icon glyph={EditIcon} size={16} tone="secondary" />
            {t("rename")}
          </DropdownMenuItem>
        )}
        {conversation.capabilities.pin && (
          <DropdownMenuItem onSelect={() => void onTogglePinned()}>
            <Icon glyph={PinIcon} size={16} tone="secondary" />
            {conversation.pinned_at ? t("unpin") : t("pin")}
          </DropdownMenuItem>
        )}
        {conversation.capabilities.delete && (
          <DropdownMenuItem
            destructive
            onSelect={() => onDelete(overflowButtonRef.current)}
          >
            <Icon glyph={DeleteIcon} size={16} tone="danger" />
            {t("delete")}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );

  if (!mobile && editing) {
    return (
      <form
        className="group/interactive-row bg-hover flex min-h-9 min-w-0 items-center gap-1 rounded-[var(--radius-lg)] px-1"
        onBlur={() => {
          requestAnimationFrame(() => {
            if (!formRef.current?.contains(document.activeElement)) {
              cancelRename(false);
            }
          });
        }}
        onSubmit={(event) => void submitRename(event)}
        ref={formRef}
      >
        <Input
          aria-label={t("renameLabel")}
          className="text-sidebar-label bg-surface h-8 min-h-8 min-w-0 border-transparent px-2"
          disabled={pending}
          maxLength={240}
          onChange={(event) => setTitle(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && isImeComposing(event)) {
              event.preventDefault();
            } else if (event.key === "Escape") {
              event.preventDefault();
              cancelRename();
            }
          }}
          ref={inputRef}
          value={title}
        />
        <IconButton
          className="size-8 min-h-8 shrink-0"
          disabled={pending}
          label={t("cancelRename")}
          onClick={() => cancelRename()}
          type="button"
          variant="ghost"
        >
          <Icon glyph={DismissIcon} size={16} />
        </IconButton>
        <IconButton
          className="size-8 min-h-8 shrink-0"
          disabled={!parsedTitle.success || unchanged || pending}
          label={t("saveRename")}
          type="submit"
          variant="ghost"
        >
          <Icon glyph={ConfirmIcon} size={16} />
        </IconButton>
      </form>
    );
  }

  return (
    <div
      className={cn(
        "motion-control group/interactive-row hover:bg-hover focus-within:bg-hover active:bg-pressed flex min-w-0 items-center rounded-[var(--radius-lg)]",
        mobile ? "min-h-16 px-1 py-1" : "min-h-9 px-1",
        current && (mobile ? "bg-surface" : "bg-hover"),
      )}
      data-current={current ? "" : undefined}
      data-conversation-row={conversation.id}
    >
      <Link
        aria-current={current ? "page" : undefined}
        className={cn(
          "min-w-0 flex-1 rounded-[var(--radius-md)]",
          keyboardFocusRing,
          mobile
            ? "flex min-h-14 items-center px-2 py-2"
            : "text-sidebar-label flex h-8 items-center gap-2 px-1",
        )}
        href={href as Route}
        onClick={onNavigate}
      >
        {!mobile && conversation.pinned_at && (
          <Icon glyph={PinIcon} size={16} tone="secondary" />
        )}
        <span className="min-w-0 flex-1">
          <span
            className={cn("block truncate", mobile && "text-base leading-6")}
          >
            {conversation.title}
          </span>
          {mobile && (
            <span className="text-secondary block truncate text-xs leading-5">
              {formatRelativeTime(conversation.updated_at)}
              {conversation.scope_label && ` · ${conversation.scope_label}`}
            </span>
          )}
        </span>
        {!mobile && conversation.scope_label && (
          <span className="text-caption text-secondary max-w-[4rem] truncate">
            {conversation.scope_label}
          </span>
        )}
      </Link>
      {actions}
    </div>
  );
}
