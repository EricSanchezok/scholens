"use client";

import type { components } from "@/lib/api/generated/schema";
import * as React from "react";

import {
  IconButton,
  keyboardFocusRing,
  Popover,
  PopoverContent,
  PopoverTrigger,
  SearchField,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  ConfirmIcon,
  ExpandIcon,
  NewConversationIcon,
  PinIcon,
} from "@/design-system/icons/semantic-icons";
import { cn } from "@/lib/utilities/cn";

export type ConversationSummary =
  components["schemas"]["ConversationSummaryResponse"];

export type ConversationSwitcherLabels = {
  empty: string;
  loading: string;
  new: string;
  newDraft: string;
  pin: string;
  pinned: string;
  recent: string;
  search: string;
  switcher: string;
  unpin: string;
};

export function ConversationSwitcher({
  activeId,
  className,
  conversations,
  labels,
  loading,
  onChange,
  onNew,
  onPin,
  onPinError,
  trailingAction,
}: {
  activeId?: string;
  className?: string;
  conversations: ConversationSummary[];
  labels: ConversationSwitcherLabels;
  loading: boolean;
  onChange: (id: string) => void;
  onNew: () => void;
  onPin: (id: string, pinned: boolean) => Promise<void>;
  onPinError: () => void;
  trailingAction?: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visible = conversations.filter((conversation) =>
    conversation.title.toLocaleLowerCase().includes(normalizedQuery),
  );
  const pinnedConversations = visible.filter(
    (conversation) => conversation.pinned_at,
  );
  const recentConversations = visible.filter(
    (conversation) => !conversation.pinned_at,
  );
  const activeConversation = conversations.find(
    (conversation) => conversation.id === activeId,
  );

  function renderConversation(conversation: ConversationSummary) {
    return (
      <div
        className={cn(
          "hover:bg-hover flex min-w-0 items-center rounded-[var(--radius-sm)]",
          activeId === conversation.id && "bg-pressed",
        )}
        key={conversation.id}
      >
        <button
          aria-current={activeId === conversation.id ? "true" : undefined}
          className="flex min-w-0 flex-1 items-center gap-2 px-2 py-2 text-left text-sm"
          onClick={() => {
            onChange(conversation.id);
            setOpen(false);
          }}
          type="button"
        >
          <span className="min-w-0 flex-1 truncate">{conversation.title}</span>
          {activeId === conversation.id ? (
            <Icon glyph={ConfirmIcon} size={16} />
          ) : null}
        </button>
        {conversation.capabilities.pin ? (
          <IconButton
            className="size-8 min-h-8"
            label={conversation.pinned_at ? labels.unpin : labels.pin}
            onClick={() => {
              void onPin(conversation.id, !conversation.pinned_at).catch(
                onPinError,
              );
            }}
            variant="ghost"
          >
            <Icon
              glyph={PinIcon}
              size={16}
              tone={conversation.pinned_at ? undefined : "secondary"}
            />
          </IconButton>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex shrink-0 items-center gap-1 px-3 pt-3 pb-1",
        className,
      )}
      data-conversation-switcher
    >
      <Popover
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
          if (!nextOpen) setQuery("");
        }}
        open={open}
      >
        <PopoverTrigger asChild>
          <button
            aria-expanded={open}
            className={cn(
              "hover:bg-hover flex h-10 min-w-0 flex-1 items-center gap-2 rounded-[var(--radius-md)] border border-transparent px-2.5 text-left text-sm transition-colors",
              keyboardFocusRing,
            )}
            type="button"
          >
            <span className="min-w-0 flex-1 truncate font-medium">
              {activeConversation?.title ?? labels.newDraft}
            </span>
            <Icon glyph={ExpandIcon} size={16} tone="secondary" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          aria-label={labels.switcher}
          className="shadow-raised w-[min(21rem,calc(100vw-2rem))] p-2"
        >
          <SearchField
            autoFocus
            className="h-9"
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder={labels.search}
            value={query}
          />
          <div className="mt-2 max-h-[min(22rem,50dvh)] overflow-y-auto">
            {loading ? (
              <span className="text-muted block px-2 py-3 text-xs">
                {labels.loading}
              </span>
            ) : visible.length === 0 ? (
              <span className="text-muted block px-2 py-3 text-xs">
                {labels.empty}
              </span>
            ) : (
              <div className="grid gap-3">
                {pinnedConversations.length > 0 ? (
                  <section aria-label={labels.pinned}>
                    <p className="text-muted px-2 pb-1 text-xs font-medium">
                      {labels.pinned}
                    </p>
                    <div className="grid gap-0.5">
                      {pinnedConversations.map(renderConversation)}
                    </div>
                  </section>
                ) : null}
                {recentConversations.length > 0 ? (
                  <section aria-label={labels.recent}>
                    <p className="text-muted px-2 pb-1 text-xs font-medium">
                      {labels.recent}
                    </p>
                    <div className="grid gap-0.5">
                      {recentConversations.map(renderConversation)}
                    </div>
                  </section>
                ) : null}
              </div>
            )}
          </div>
        </PopoverContent>
      </Popover>
      <IconButton
        className="size-10 min-h-10"
        label={labels.new}
        onClick={onNew}
        variant="ghost"
      >
        <Icon glyph={NewConversationIcon} size={20} />
      </IconButton>
      {trailingAction}
    </div>
  );
}
