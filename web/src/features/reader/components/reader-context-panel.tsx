"use client";

import {
  ConfirmIcon,
  CommentIcon,
  EditIcon,
  ExpandIcon,
  FilterIcon,
  HighlightColorIcon,
  MoreIcon,
  NextIcon,
  PinIcon,
  PreviousIcon,
  ReopenIcon,
  NewConversationIcon,
  ClosePanelIcon,
  DeleteIcon,
} from "@/design-system/icons/semantic-icons";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import * as React from "react";

import {
  Button,
  Badge,
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  IconButton,
  keyboardFocusRing,
  Popover,
  PopoverContent,
  PopoverTrigger,
  SearchField,
  Textarea,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  ConversationView,
  useConversationSession,
  type ReasoningLevel,
} from "@/features/conversation";
import { cn } from "@/lib/utilities/cn";
import {
  readerHighlightColors,
  readerHighlightColorValue,
  readReaderHighlightColor,
  type ReaderHighlightColor,
} from "../reader-highlight-colors";
import type { ReaderSelection } from "./pdf-page";
import type {
  ReaderAnnotation,
  ReaderAnnotationSummary,
  ReaderAnnotationAudience,
  ReaderAnnotationAudienceFilter,
  ReaderAnnotationMode,
  ReaderAnnotationStatus,
  ReaderConversation,
  ReaderContextPanel,
  ReaderDocument,
  ReaderDocumentSource,
} from "../reader-types";

export function formatReaderFileSize(size: number, locale: string) {
  if (!Number.isFinite(size) || size < 0) return "—";
  const units = ["B", "KB", "MB", "GB"] as const;
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${new Intl.NumberFormat(locale, {
    maximumFractionDigits: unit === 0 ? 0 : 1,
  }).format(value)} ${units[unit]}`;
}

export function ReaderConversationSwitcher({
  activeId,
  conversations,
  loading,
  onChange,
  onNew,
  onPin,
  onPinError,
}: {
  activeId?: string;
  conversations: ReaderConversation[];
  loading: boolean;
  onChange: (id: string) => void;
  onNew: () => void;
  onPin: (id: string, pinned: boolean) => Promise<void>;
  onPinError: () => void;
}) {
  const t = useTranslations("Reader.conversations");
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

  function renderConversation(conversation: ReaderConversation) {
    return (
      <div
        className={cn(
          "hover:bg-hover flex min-w-0 items-center rounded-[var(--radius-sm)]",
          activeId === conversation.id && "bg-accent",
        )}
        key={conversation.id}
      >
        <button
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
        <IconButton
          className="size-8 min-h-8"
          label={conversation.pinned_at ? t("unpin") : t("pin")}
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
      </div>
    );
  }

  return (
    <div className="flex shrink-0 items-center gap-1 px-3 pt-3 pb-1">
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
              {activeConversation?.title ?? t("newDraft")}
            </span>
            <Icon glyph={ExpandIcon} size={16} tone="secondary" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          aria-label={t("switcher")}
          className="w-[min(21rem,calc(100vw-2rem))] p-2"
        >
          <SearchField
            autoFocus
            className="h-9"
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder={t("search")}
            value={query}
          />
          <div className="mt-2 max-h-[min(22rem,50vh)] overflow-y-auto">
            {loading ? (
              <span className="text-muted block px-2 py-3 text-xs">
                {t("loading")}
              </span>
            ) : visible.length === 0 ? (
              <span className="text-muted block px-2 py-3 text-xs">
                {t("empty")}
              </span>
            ) : (
              <div className="grid gap-3">
                {pinnedConversations.length > 0 ? (
                  <section>
                    <p className="text-muted px-2 pb-1 text-xs font-medium">
                      {t("pinned")}
                    </p>
                    <div className="grid gap-0.5">
                      {pinnedConversations.map(renderConversation)}
                    </div>
                  </section>
                ) : null}
                {recentConversations.length > 0 ? (
                  <section>
                    <p className="text-muted px-2 pb-1 text-xs font-medium">
                      {t("recent")}
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
        label={t("new")}
        onClick={onNew}
        variant="ghost"
      >
        <Icon glyph={NewConversationIcon} size={20} />
      </IconButton>
    </div>
  );
}

export function ReaderAnnotationPanel({
  annotations,
  error,
  onActionError,
  onCommentCreate,
  onCommentDelete,
  onCommentUpdate,
  onCreate,
  onDelete,
  onStatusChange,
  onStatusFilterChange,
  modeFilter,
  onModeFilterChange,
  onSelect,
  onUpdateColor,
  audienceFilter,
  onAudienceFilterChange,
  projectContext,
  statusFilter,
  selectedAnnotation,
  selectedAnnotationId,
  selectedAnnotationLoading,
  selectedAnnotationUnavailable,
  annotationSelection,
}: {
  annotations: ReaderAnnotationSummary[];
  error: boolean;
  onActionError: (error?: unknown) => void;
  onCommentCreate: (id: string, content: string) => Promise<void>;
  onCommentDelete: (id: string) => Promise<void>;
  onCommentUpdate: (id: string, content: string) => Promise<void>;
  onCreate: (
    comment: string,
    color: ReaderHighlightColor,
    audience: ReaderAnnotationAudience,
  ) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onStatusChange: (id: string, status: ReaderAnnotationStatus) => Promise<void>;
  onStatusFilterChange: (status: ReaderAnnotationStatus) => void;
  modeFilter: ReaderAnnotationMode;
  onModeFilterChange: (mode: ReaderAnnotationMode) => void;
  onSelect: (id: string) => void;
  onUpdateColor: (id: string, color: ReaderHighlightColor) => Promise<void>;
  selectedAnnotation?: ReaderAnnotation;
  selectedAnnotationId?: string;
  selectedAnnotationLoading?: boolean;
  selectedAnnotationUnavailable?: boolean;
  annotationSelection?: ReaderSelection;
  audienceFilter: ReaderAnnotationAudienceFilter;
  onAudienceFilterChange: (filter: ReaderAnnotationAudienceFilter) => void;
  projectContext?: { id: string; title: string };
  statusFilter: ReaderAnnotationStatus;
}) {
  const t = useTranslations("Reader.annotations");
  const format = useFormatter();
  const [selectionComment, setSelectionComment] = React.useState("");
  const [replyDrafts, setReplyDrafts] = React.useState<Record<string, string>>(
    {},
  );
  const [editingCommentId, setEditingCommentId] = React.useState<string>();
  const [editingContent, setEditingContent] = React.useState("");
  const [busyAction, setBusyAction] = React.useState<string>();
  const [replyBusyId, setReplyBusyId] = React.useState<string>();
  const [pendingDelete, setPendingDelete] = React.useState<
    { id: string; kind: "comment" | "thread" } | undefined
  >();
  const [selectionColor, setSelectionColor] =
    React.useState<ReaderHighlightColor>("yellow");
  const [selectionAudience, setSelectionAudience] =
    React.useState<ReaderAnnotationAudience>(
      projectContext ? "project" : "personal",
    );

  async function perform(key: string, action: () => Promise<void>) {
    setBusyAction(key);
    try {
      await action();
    } catch (actionError) {
      onActionError(actionError);
    } finally {
      setBusyAction(undefined);
    }
  }

  async function submitReply(annotation: ReaderAnnotation) {
    const content = replyDrafts[annotation.id]?.trim() ?? "";
    if (!content || replyBusyId) return;
    setReplyBusyId(annotation.id);
    try {
      await onCommentCreate(annotation.id, content);
      setReplyDrafts((current) => ({ ...current, [annotation.id]: "" }));
    } catch (actionError) {
      onActionError(actionError);
    } finally {
      setReplyBusyId(undefined);
    }
  }

  if (error) {
    return <p className="text-danger p-5 text-sm">{t("error")}</p>;
  }

  const selectedIndex = annotations.findIndex(
    ({ id }) => id === selectedAnnotationId,
  );

  return (
    <div className="grid gap-3 p-3">
      <div className="flex min-h-9 items-center gap-1">
        <p className="min-w-0 flex-1 text-sm font-medium">
          {t("summaryCount", { count: annotations.length })}
        </p>
        <IconButton
          className="size-9 min-h-9"
          disabled={selectedIndex <= 0}
          label={t("previous")}
          onClick={() => {
            const previous = annotations[selectedIndex - 1];
            if (previous) onSelect(previous.id);
          }}
          variant="ghost"
        >
          <Icon glyph={PreviousIcon} size={20} />
        </IconButton>
        <IconButton
          className="size-9 min-h-9"
          disabled={
            selectedIndex < 0 || selectedIndex >= annotations.length - 1
          }
          label={t("next")}
          onClick={() => {
            const next = annotations[selectedIndex + 1];
            if (next) onSelect(next.id);
          }}
          variant="ghost"
        >
          <Icon glyph={NextIcon} size={20} />
        </IconButton>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button className="h-9 min-h-9 px-2" size="sm" variant="secondary">
              <Icon glyph={FilterIcon} size={20} tone="secondary" />
              {t("filters.label")}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>{t("filters.scope")}</DropdownMenuLabel>
            {(["all", "personal", "project"] as const).map((filter) =>
              filter === "project" && !projectContext ? null : (
                <DropdownMenuItem
                  key={filter}
                  onSelect={() => onAudienceFilterChange(filter)}
                >
                  <span className="w-4">
                    {audienceFilter === filter ? (
                      <Icon glyph={ConfirmIcon} size={16} />
                    ) : null}
                  </span>
                  {t(`filters.${filter}`)}
                </DropdownMenuItem>
              ),
            )}
            <DropdownMenuSeparator />
            <DropdownMenuLabel>{t("filters.type")}</DropdownMenuLabel>
            {(["all", "highlight", "note", "discussion"] as const).map(
              (mode) => (
                <DropdownMenuItem
                  key={mode}
                  onSelect={() => onModeFilterChange(mode)}
                >
                  <span className="w-4">
                    {modeFilter === mode ? (
                      <Icon glyph={ConfirmIcon} size={16} />
                    ) : null}
                  </span>
                  {t(`modes.${mode}`)}
                </DropdownMenuItem>
              ),
            )}
            {projectContext ? (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>{t("filters.state")}</DropdownMenuLabel>
                {(["open", "resolved"] as const).map((status) => (
                  <DropdownMenuItem
                    key={status}
                    onSelect={() => onStatusFilterChange(status)}
                  >
                    <span className="w-4">
                      {statusFilter === status ? (
                        <Icon glyph={ConfirmIcon} size={16} />
                      ) : null}
                    </span>
                    {t(`statusFilter.${status}`)}
                  </DropdownMenuItem>
                ))}
              </>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {annotationSelection ? (
        <section
          className="border-line bg-subtle rounded-[var(--radius-lg)] border p-3"
          key={`${annotationSelection.document_id}:${annotationSelection.page_number}:${projectContext?.id ?? "personal"}`}
        >
          <p className="text-secondary line-clamp-4 text-sm leading-5">
            “{annotationSelection.selected_text}”
          </p>
          <Textarea
            className="mt-3 min-h-20"
            onChange={(event) => setSelectionComment(event.currentTarget.value)}
            placeholder={t("commentPlaceholder")}
            value={selectionComment}
          />
          {projectContext ? (
            <div className="bg-canvas border-line mt-3 grid grid-cols-2 rounded-[var(--radius-md)] border p-0.5 text-xs">
              {(["personal", "project"] as const).map((audience) => (
                <button
                  aria-pressed={selectionAudience === audience}
                  className={cn(
                    "rounded-[calc(var(--radius-md)-2px)] px-2 py-1.5",
                    selectionAudience === audience &&
                      "bg-surface shadow-raised",
                    keyboardFocusRing,
                  )}
                  key={audience}
                  onClick={() => setSelectionAudience(audience)}
                  type="button"
                >
                  {t(`audience.${audience}`)}
                </button>
              ))}
            </div>
          ) : null}
          <div className="mt-3 flex gap-1.5">
            {readerHighlightColors.map((color) => (
              <button
                aria-label={t(`colors.${color}`)}
                className={cn(
                  "border-control size-6 rounded-full border",
                  selectionColor === color &&
                    "ring-2 ring-[var(--color-focus-ring)] ring-offset-2 ring-offset-[var(--color-bg-surface)]",
                  keyboardFocusRing,
                )}
                key={color}
                onClick={() => setSelectionColor(color)}
                style={{ backgroundColor: readerHighlightColorValue(color) }}
                type="button"
              />
            ))}
          </div>
          <Button
            className="mt-3 w-full"
            loading={busyAction === "create"}
            onClick={() =>
              void perform("create", async () => {
                await onCreate(
                  selectionComment.trim(),
                  selectionColor,
                  selectionAudience,
                );
                setSelectionComment("");
              })
            }
            size="sm"
          >
            {selectionComment.trim() ? t("saveSelection") : t("saveHighlight")}
          </Button>
        </section>
      ) : null}

      {annotations.length === 0 && !annotationSelection ? (
        <div className="grid min-h-48 place-items-center px-6 text-center">
          <div>
            <p className="text-sm font-medium">{t("emptyTitle")}</p>
            <p className="text-muted mt-1 max-w-64 text-sm">
              {t("emptyDescription")}
            </p>
          </div>
        </div>
      ) : (
        annotations.map((annotation) => {
          const active = selectedAnnotationId === annotation.id;
          const thread = active
            ? selectedAnnotation?.annotation_thread
            : undefined;
          const currentColor = readReaderHighlightColor(annotation.color);
          const replyDraft = replyDrafts[annotation.id] ?? "";
          const replyPrompt =
            annotation.mode === "highlight"
              ? annotation.audience.kind === "project"
                ? t("startDiscussion")
                : t("addNote")
              : t("replyPlaceholder");
          return (
            <article
              className={cn(
                "border-line overflow-hidden rounded-[var(--radius-lg)] border transition-colors",
                active && "bg-subtle",
              )}
              key={annotation.id}
            >
              <button
                className={cn("w-full p-3 text-left", keyboardFocusRing)}
                onClick={() => onSelect(annotation.id)}
                type="button"
              >
                <span className="flex items-center gap-2">
                  <span
                    aria-hidden
                    className="size-2.5 shrink-0 rounded-full"
                    style={{
                      backgroundColor: readerHighlightColorValue(currentColor),
                    }}
                  />
                  <span className="text-muted text-xs">
                    {t("page", { page: annotation.position?.page_number ?? 1 })}
                  </span>
                  <span className="text-muted ml-auto text-xs">
                    {format.relativeTime(new Date(annotation.last_activity_at))}
                  </span>
                </span>
                <span
                  className={cn(
                    "mt-1.5 block text-sm leading-5",
                    active ? "line-clamp-6" : "line-clamp-3",
                  )}
                >
                  “{annotation.quote_text}”
                </span>
                <span className="mt-2 flex flex-wrap items-center gap-1.5">
                  <Badge>
                    {annotation.audience.kind === "project"
                      ? (projectContext?.title ?? t("audience.project"))
                      : t("audience.personal")}
                  </Badge>
                  <Badge>{t(`modes.${annotation.mode}`)}</Badge>
                  {annotation.mode === "discussion" ? (
                    <Badge
                      tone={
                        annotation.status === "resolved" ? "neutral" : "info"
                      }
                    >
                      {t(`status.${annotation.status}`)}
                    </Badge>
                  ) : null}
                  {annotation.comment_count > 0 ? (
                    <span className="text-muted inline-flex items-center gap-1 text-xs">
                      <Icon glyph={CommentIcon} size={16} />
                      {annotation.comment_count}
                    </span>
                  ) : null}
                  <span className="text-muted text-xs">
                    {annotation.created_by.display_name ?? t("unknownAuthor")}
                  </span>
                </span>
              </button>

              {active ? (
                <div className="border-line-subtle border-t px-3 pb-3">
                  {selectedAnnotationUnavailable ? (
                    <div className="py-5 text-center">
                      <p className="font-medium">{t("unavailableThread")}</p>
                      <p className="text-muted mt-1 text-sm">
                        {t("unavailableThreadDescription")}
                      </p>
                    </div>
                  ) : selectedAnnotationLoading || !thread ? (
                    <p className="text-muted py-5 text-center text-sm">
                      {t("loadingThread")}
                    </p>
                  ) : (
                    <>
                      <div className="flex items-center gap-1 py-2">
                        {thread.capabilities.resolve ? (
                          <Button
                            className="mr-auto"
                            loading={busyAction === "resolve"}
                            onClick={() =>
                              void perform("resolve", () =>
                                onStatusChange(annotation.id, "resolved"),
                              )
                            }
                            size="sm"
                            variant="ghost"
                          >
                            <Icon glyph={ConfirmIcon} size={16} />
                            {t("resolve")}
                          </Button>
                        ) : thread.capabilities.reopen ? (
                          <Button
                            className="mr-auto"
                            loading={busyAction === "reopen"}
                            onClick={() =>
                              void perform("reopen", () =>
                                onStatusChange(annotation.id, "open"),
                              )
                            }
                            size="sm"
                            variant="secondary"
                          >
                            <Icon glyph={ReopenIcon} size={16} />
                            {t("reopen")}
                          </Button>
                        ) : (
                          <span className="mr-auto" />
                        )}
                        {thread.capabilities.recolor ||
                        thread.capabilities.delete ? (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <IconButton
                                className="size-9 min-h-9"
                                label={t("moreActions")}
                                variant="ghost"
                              >
                                <Icon
                                  glyph={MoreIcon}
                                  size={20}
                                  tone="secondary"
                                />
                              </IconButton>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              {thread.capabilities.recolor ? (
                                <DropdownMenuSub>
                                  <DropdownMenuSubTrigger>
                                    <Icon
                                      glyph={HighlightColorIcon}
                                      size={16}
                                      tone="secondary"
                                    />
                                    {t("changeColor")}
                                  </DropdownMenuSubTrigger>
                                  <DropdownMenuSubContent className="min-w-0 p-2">
                                    <div className="flex gap-2">
                                      {readerHighlightColors.map((color) => (
                                        <button
                                          aria-label={t(`colors.${color}`)}
                                          className={cn(
                                            "border-control size-7 rounded-full border",
                                            keyboardFocusRing,
                                            currentColor === color &&
                                              "ring-2 ring-[var(--color-focus-ring)] ring-offset-2 ring-offset-[var(--color-bg-elevated)]",
                                          )}
                                          key={color}
                                          onClick={() =>
                                            void perform("color", () =>
                                              onUpdateColor(
                                                annotation.id,
                                                color,
                                              ),
                                            )
                                          }
                                          style={{
                                            backgroundColor:
                                              readerHighlightColorValue(color),
                                          }}
                                          type="button"
                                        />
                                      ))}
                                    </div>
                                  </DropdownMenuSubContent>
                                </DropdownMenuSub>
                              ) : null}
                              {thread.capabilities.delete ? (
                                <DropdownMenuItem
                                  destructive
                                  onSelect={() =>
                                    setPendingDelete({
                                      id: annotation.id,
                                      kind: "thread",
                                    })
                                  }
                                >
                                  <Icon glyph={DeleteIcon} size={16} />
                                  {t("deleteHighlight")}
                                </DropdownMenuItem>
                              ) : null}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        ) : null}
                      </div>

                      {thread.status === "resolved" && thread.resolved_at ? (
                        <p className="text-muted border-line-subtle border-b pb-3 text-xs">
                          {t("resolvedBy", {
                            author:
                              thread.resolved_by?.display_name ??
                              t("unknownAuthor"),
                            time: format.relativeTime(
                              new Date(thread.resolved_at),
                            ),
                          })}
                        </p>
                      ) : null}

                      {thread.comments.length === 0 ? (
                        <p className="text-muted py-3 text-sm">
                          {t("noComments")}
                        </p>
                      ) : null}
                      {thread.comments.map((item) => (
                        <div
                          className="border-line-subtle mt-3 border-t pt-3"
                          key={item.id}
                        >
                          {editingCommentId === item.id ? (
                            <>
                              <Textarea
                                className="min-h-16"
                                onChange={(event) =>
                                  setEditingContent(event.currentTarget.value)
                                }
                                value={editingContent}
                              />
                              <div className="mt-2 flex justify-end gap-1">
                                <Button
                                  onClick={() => setEditingCommentId(undefined)}
                                  size="sm"
                                  variant="ghost"
                                >
                                  {t("cancel")}
                                </Button>
                                <Button
                                  disabled={!editingContent.trim()}
                                  loading={busyAction === `edit:${item.id}`}
                                  onClick={() =>
                                    void perform(
                                      `edit:${item.id}`,
                                      async () => {
                                        await onCommentUpdate(
                                          item.id,
                                          editingContent.trim(),
                                        );
                                        setEditingCommentId(undefined);
                                      },
                                    )
                                  }
                                  size="sm"
                                >
                                  {t("save")}
                                </Button>
                              </div>
                            </>
                          ) : (
                            <>
                              <div className="mb-1 flex items-center gap-1.5 text-xs">
                                <span className="font-medium">
                                  {item.created_by.display_name ??
                                    t("unknownAuthor")}
                                </span>
                                <span className="text-muted">
                                  {format.relativeTime(
                                    new Date(item.created_at),
                                  )}
                                </span>
                              </div>
                              <p className="text-sm leading-5">
                                {item.content}
                              </p>
                              {item.can_edit || item.can_delete ? (
                                <div className="mt-1 flex justify-end">
                                  <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                      <IconButton
                                        className="size-8 min-h-8"
                                        label={t("commentActions")}
                                        variant="ghost"
                                      >
                                        <Icon
                                          glyph={MoreIcon}
                                          size={16}
                                          tone="secondary"
                                        />
                                      </IconButton>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                      {item.can_edit ? (
                                        <DropdownMenuItem
                                          onSelect={() => {
                                            setEditingCommentId(item.id);
                                            setEditingContent(item.content);
                                          }}
                                        >
                                          <Icon
                                            glyph={EditIcon}
                                            size={16}
                                            tone="secondary"
                                          />
                                          {t("editComment")}
                                        </DropdownMenuItem>
                                      ) : null}
                                      {item.can_delete ? (
                                        <DropdownMenuItem
                                          destructive
                                          onSelect={() =>
                                            setPendingDelete({
                                              id: item.id,
                                              kind: "comment",
                                            })
                                          }
                                        >
                                          <Icon glyph={DeleteIcon} size={16} />
                                          {t("deleteComment")}
                                        </DropdownMenuItem>
                                      ) : null}
                                    </DropdownMenuContent>
                                  </DropdownMenu>
                                </div>
                              ) : null}
                            </>
                          )}
                        </div>
                      ))}

                      {thread.capabilities.reply ? (
                        <form
                          className="border-line-subtle mt-3 border-t pt-3"
                          onSubmit={(event) => {
                            event.preventDefault();
                            if (selectedAnnotation) {
                              void submitReply(selectedAnnotation);
                            }
                          }}
                        >
                          <Textarea
                            className="min-h-20"
                            disabled={replyBusyId === annotation.id}
                            onChange={(event) =>
                              setReplyDrafts((current) => ({
                                ...current,
                                [annotation.id]: event.currentTarget.value,
                              }))
                            }
                            onKeyDown={(event) => {
                              if (
                                (event.metaKey || event.ctrlKey) &&
                                event.key === "Enter"
                              ) {
                                event.preventDefault();
                                if (selectedAnnotation) {
                                  void submitReply(selectedAnnotation);
                                }
                              }
                            }}
                            placeholder={replyPrompt}
                            value={replyDraft}
                          />
                          <div className="mt-2 flex items-center justify-between gap-3">
                            <span className="text-muted text-xs">
                              {t("submitShortcut")}
                            </span>
                            <Button
                              disabled={!replyDraft.trim()}
                              loading={replyBusyId === annotation.id}
                              size="sm"
                              type="submit"
                            >
                              {annotation.mode === "highlight"
                                ? annotation.audience.kind === "project"
                                  ? t("start")
                                  : t("add")
                                : t("reply")}
                            </Button>
                          </div>
                        </form>
                      ) : null}
                    </>
                  )}
                </div>
              ) : null}
            </article>
          );
        })
      )}

      <AlertDialog
        onOpenChange={(open) => {
          if (!open) setPendingDelete(undefined);
        }}
        open={Boolean(pendingDelete)}
      >
        <AlertDialogContent>
          <AlertDialogTitle>
            {t(
              pendingDelete?.kind === "comment"
                ? "deleteCommentTitle"
                : "deleteThreadTitle",
            )}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t(
              pendingDelete?.kind === "comment"
                ? "deleteCommentDescription"
                : "deleteThreadDescription",
            )}
          </AlertDialogDescription>
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialogCancel asChild>
              <Button variant="secondary">{t("cancel")}</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                loading={busyAction === "delete"}
                onClick={() => {
                  if (!pendingDelete) return;
                  const target = pendingDelete;
                  void perform("delete", async () => {
                    if (target.kind === "comment") {
                      await onCommentDelete(target.id);
                    } else {
                      await onDelete(target.id);
                    }
                    setPendingDelete(undefined);
                  });
                }}
                variant="danger"
              >
                {t("delete")}
              </Button>
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export function ReaderDetailsPanel({
  document,
  title,
}: {
  document?: ReaderDocument;
  title: string;
}) {
  const locale = useLocale();
  const t = useTranslations("Reader.details");
  const metadata = [
    [t("title"), title],
    [t("authors"), document?.authors?.join(", ")],
    [t("abstract"), document?.abstract],
    [t("summary"), document?.summary],
    [t("doi"), document?.doi],
    [t("journal"), document?.journal],
    [t("publisher"), document?.publisher],
    [t("institutions"), document?.institutions?.join(", ")],
    [t("published"), document?.publish_date],
    [t("status"), document && t(`statuses.${document.processing_status}`)],
    [t("quality"), document?.parser_quality],
    [t("warning"), document?.parser_warning_code],
  ] as const;

  return (
    <dl className="grid gap-5 p-5 text-sm">
      {metadata.map(([label, value]) => (
        <div key={label}>
          <dt className="text-muted">{label}</dt>
          <dd className="mt-1 leading-6">{value || t("unknown")}</dd>
        </div>
      ))}
      <div>
        <dt className="text-muted">{t("file")}</dt>
        <dd className="mt-1 grid gap-0.5">
          <span>{document?.original_filename || t("unknown")}</span>
          {document && (
            <span className="text-secondary">
              {document.mime_type} ·{" "}
              {formatReaderFileSize(document.size_bytes, locale)}
            </span>
          )}
        </dd>
      </div>
      <div className="border-line bg-subtle rounded-[var(--radius-md)] border p-3">
        <dt className="font-medium">{t("unavailable")}</dt>
        <dd className="text-muted mt-1">{t("unavailableDescription")}</dd>
      </div>
    </dl>
  );
}

export function ReaderContextPanel({
  annotations,
  annotationsError,
  className,
  conversationId,
  conversationSession,
  conversations,
  conversationsLoading,
  document,
  onActionError,
  onAnnotationDelete,
  onAnnotationSelect,
  onClose,
  onCommentCreate,
  onCommentDelete,
  onCommentUpdate,
  onConversationChange,
  onConversationNew,
  onConversationPin,
  onHighlightCreate,
  onHighlightUpdate,
  onAnnotationStatusChange,
  annotationAudienceFilter,
  onAnnotationAudienceFilterChange,
  annotationModeFilter,
  onAnnotationModeFilterChange,
  annotationStatusFilter,
  onAnnotationStatusFilterChange,
  onPanelChange,
  onSourceOpen,
  panel,
  projectContext,
  reasoningLevel,
  selectedAnnotation,
  selectedAnnotationId,
  selectedAnnotationLoading,
  selectedAnnotationUnavailable,
  annotationSelection,
  pendingTurnContext,
  onTurnContextClear,
  setReasoningLevel,
  title,
}: {
  annotations: ReaderAnnotationSummary[];
  annotationsError: boolean;
  className?: string;
  conversationId?: string;
  conversationSession: ReturnType<typeof useConversationSession>;
  conversations: ReaderConversation[];
  conversationsLoading: boolean;
  document: ReaderDocument | undefined;
  onActionError: (error?: unknown) => void;
  onAnnotationDelete: (id: string) => Promise<void>;
  onAnnotationSelect: (id: string) => void;
  onClose: () => void;
  onCommentCreate: (id: string, content: string) => Promise<void>;
  onCommentDelete: (id: string) => Promise<void>;
  onCommentUpdate: (id: string, content: string) => Promise<void>;
  onConversationChange: (id: string) => void;
  onConversationNew: () => void;
  onConversationPin: (id: string, pinned: boolean) => Promise<void>;
  onHighlightCreate: (
    comment: string,
    color: ReaderHighlightColor,
    audience: ReaderAnnotationAudience,
  ) => Promise<void>;
  onHighlightUpdate: (id: string, color: ReaderHighlightColor) => Promise<void>;
  onAnnotationStatusChange: (
    id: string,
    status: ReaderAnnotationStatus,
  ) => Promise<void>;
  annotationAudienceFilter: ReaderAnnotationAudienceFilter;
  onAnnotationAudienceFilterChange: (
    filter: ReaderAnnotationAudienceFilter,
  ) => void;
  annotationModeFilter: ReaderAnnotationMode;
  onAnnotationModeFilterChange: (mode: ReaderAnnotationMode) => void;
  annotationStatusFilter: ReaderAnnotationStatus;
  onAnnotationStatusFilterChange: (status: ReaderAnnotationStatus) => void;
  onPanelChange: (panel: "ask" | "annotations" | "details") => void;
  onSourceOpen: (source: ReaderDocumentSource) => void;
  panel: ReaderContextPanel;
  projectContext?: { id: string; title: string };
  reasoningLevel: ReasoningLevel;
  selectedAnnotation?: ReaderAnnotation;
  selectedAnnotationId?: string;
  selectedAnnotationLoading?: boolean;
  selectedAnnotationUnavailable?: boolean;
  annotationSelection?: ReaderSelection;
  pendingTurnContext?: ReaderSelection;
  onTurnContextClear: () => void;
  setReasoningLevel: (level: ReasoningLevel) => void;
  title: string;
}) {
  const t = useTranslations("Reader");
  const activePanel = panel;

  return (
    <aside
      aria-label={t("contextPanel")}
      className={cn(
        "border-line bg-canvas h-full w-full shrink-0 flex-col overflow-hidden border-l max-lg:pt-[env(safe-area-inset-top)] max-lg:pb-[env(safe-area-inset-bottom)] lg:w-[clamp(23rem,34vw,31.25rem)]",
        className ?? "flex",
      )}
    >
      <div className="border-line flex h-14 shrink-0 items-center gap-1 border-b px-3">
        {(["ask", "annotations", "details"] as const).map((item) => (
          <Button
            className={cn(
              "h-9 min-h-9 px-2",
              activePanel === item && "bg-hover",
            )}
            key={item}
            onClick={() => onPanelChange(item)}
            size="sm"
            variant="ghost"
            aria-current={activePanel === item ? "page" : undefined}
            data-active={activePanel === item || undefined}
          >
            {t(`panels.${item}`)}
          </Button>
        ))}
        <IconButton
          className="ml-auto"
          label={t("closePanel")}
          onClick={onClose}
          variant="ghost"
        >
          <Icon glyph={ClosePanelIcon} size={20} />
        </IconButton>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        {activePanel === "details" ? (
          <div className="h-full overflow-y-auto" tabIndex={0}>
            <ReaderDetailsPanel document={document} title={title} />
          </div>
        ) : activePanel === "annotations" ? (
          <div className="h-full overflow-y-auto" tabIndex={0}>
            <ReaderAnnotationPanel
              key={projectContext?.id ?? "personal"}
              audienceFilter={annotationAudienceFilter}
              modeFilter={annotationModeFilter}
              annotations={annotations}
              error={annotationsError}
              onActionError={onActionError}
              onCommentCreate={onCommentCreate}
              onCommentDelete={onCommentDelete}
              onCommentUpdate={onCommentUpdate}
              onCreate={onHighlightCreate}
              onDelete={onAnnotationDelete}
              onAudienceFilterChange={onAnnotationAudienceFilterChange}
              onModeFilterChange={onAnnotationModeFilterChange}
              onSelect={onAnnotationSelect}
              onStatusChange={onAnnotationStatusChange}
              onStatusFilterChange={onAnnotationStatusFilterChange}
              onUpdateColor={onHighlightUpdate}
              projectContext={projectContext}
              selectedAnnotation={selectedAnnotation}
              selectedAnnotationId={selectedAnnotationId}
              selectedAnnotationLoading={selectedAnnotationLoading}
              selectedAnnotationUnavailable={selectedAnnotationUnavailable}
              annotationSelection={annotationSelection}
              statusFilter={annotationStatusFilter}
            />
          </div>
        ) : (
          <div className="flex h-full min-h-0 flex-col">
            <ReaderConversationSwitcher
              activeId={conversationId}
              conversations={conversations}
              loading={conversationsLoading}
              onChange={onConversationChange}
              onNew={onConversationNew}
              onPin={onConversationPin}
              onPinError={onActionError}
            />
            <ConversationView
              layout="side-panel"
              canSend={conversationSession.canSend}
              composerForm={conversationSession.composerForm}
              context={conversationSession.context}
              contextLabel={title}
              contextLocked
              error={conversationSession.turnsQuery.isError}
              emptyState={{
                description: t("conversations.emptyDescription"),
                title: t("conversations.emptyTitle"),
              }}
              liveTurn={conversationSession.liveTurn}
              loading={
                conversationSession.turnsQuery.isPending &&
                Boolean(conversationId)
              }
              onContextChange={() => undefined}
              onDocumentSourceOpen={onSourceOpen}
              onReasoningLevelChange={setReasoningLevel}
              onRetry={() => void conversationSession.turnsQuery.refetch()}
              onRetryResponse={(turn) =>
                void conversationSession.retryResponse(turn)
              }
              onSelectResponse={(turnId, responseId) =>
                void conversationSession.selectResponse(turnId, responseId)
              }
              onStop={conversationSession.stop}
              onSubmit={conversationSession.sendMessage}
              onUseSuggestion={conversationSession.useSuggestion}
              onTurnContextClear={onTurnContextClear}
              papers={[]}
              projects={[]}
              reasoningLevel={reasoningLevel}
              readOnlyReason={
                conversationSession.conversationQuery.data?.read_only_reason
              }
              submissionPending={conversationSession.submissionPending}
              turnContextLabel={
                pendingTurnContext
                  ? t("selection.context", {
                      page: pendingTurnContext.page_number,
                    })
                  : selectedAnnotation
                    ? t("annotations.context")
                    : undefined
              }
              turns={conversationSession.turnsQuery.data?.items ?? []}
            />
          </div>
        )}
      </div>
    </aside>
  );
}
