"use client";

import {
  ConfirmIcon,
  CommentIcon,
  EditIcon,
  FilterIcon,
  HighlightColorIcon,
  NextIcon,
  PreviousIcon,
  ReopenIcon,
  ClosePanelIcon,
  DeleteIcon,
} from "@/design-system/icons/semantic-icons";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import {
  Avatar,
  Button,
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
  DropdownMenuTrigger,
  Frame,
  FramePanel,
  focusSurfaceVariants,
  IconButton,
  Input,
  isImeComposing,
  OverflowMenuButton,
  Textarea,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  AnimatePresence,
  MotionPresence,
  motionVariants,
} from "@/design-system/motion";
import {
  ConversationSwitcher,
  ConversationView,
  ReasoningMenu,
  useConversationSession,
  type ReasoningLevel,
  type ResearchContext,
  type ResearchContextPaperOption,
  type ResearchContextProjectOption,
} from "@/features/conversation";
import { useRelativeTimeNow } from "@/i18n/use-relative-time-now";
import { cn } from "@/lib/utilities/cn";
import {
  readerHighlightColors,
  readerHighlightColorValue,
  readReaderHighlightColor,
  type ReaderHighlightColor,
} from "../reader-highlight-colors";
import { readerPdfPageRange } from "../reader-pdf-position";
import type { ReaderSelection } from "../reader-selection";
import type {
  ReaderAnnotationSummary,
  ReaderAnnotationAudience,
  ReaderAnnotationAudienceFilter,
  ReaderAnnotationMode,
  ReaderAnnotationStatus,
  ReaderContextPanel,
  ReaderConversation,
  ReaderDocument,
  ReaderDocumentSource,
} from "../reader-types";
import { ReaderHighlightColorButton } from "./reader-highlight-color-button";

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
  onPreviewChange,
  onUpdateColor,
  audienceFilter,
  onAudienceFilterChange,
  projectContext,
  statusFilter,
  selectedAnnotationId,
  annotationSelection,
  annotationInitialComment,
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
  onPreviewChange: (id: string | undefined) => void;
  onUpdateColor: (id: string, color: ReaderHighlightColor) => Promise<void>;
  selectedAnnotationId?: string;
  annotationSelection?: ReaderSelection;
  annotationInitialComment?: string;
  audienceFilter: ReaderAnnotationAudienceFilter;
  onAudienceFilterChange: (filter: ReaderAnnotationAudienceFilter) => void;
  projectContext?: { id: string; title: string };
  statusFilter: ReaderAnnotationStatus;
}) {
  const t = useTranslations("Reader.annotations");
  const formatRelativeTime = useRelativeTimeNow();
  const [selectionComment, setSelectionComment] = React.useState(
    annotationInitialComment ?? "",
  );
  const [replyDrafts, setReplyDrafts] = React.useState<Record<string, string>>(
    {},
  );
  const [editingCommentId, setEditingCommentId] = React.useState<string>();
  const [editingContent, setEditingContent] = React.useState("");
  const [busyAction, setBusyAction] = React.useState<string>();
  const [replyBusyId, setReplyBusyId] = React.useState<string>();
  const [colorMenuThreadId, setColorMenuThreadId] = React.useState<string>();
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

  async function submitReply(annotation: ReaderAnnotationSummary) {
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
    <div
      className="grid max-w-full min-w-0 gap-3 overflow-x-hidden p-3"
      data-reader-annotation-panel
    >
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
                    focusSurfaceVariants({ intent: "selection" }),
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
          <div
            className="mt-3 grid grid-cols-4 gap-2"
            data-reader-highlight-palette=""
          >
            {readerHighlightColors.map((color) => (
              <ReaderHighlightColorButton
                color={color}
                key={color}
                label={t(`colors.${color}`)}
                onClick={() => setSelectionColor(color)}
                selected={selectionColor === color}
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
          const currentColor = readReaderHighlightColor(annotation.color);
          const pageRange =
            annotation.position?.kind === "pdf_text"
              ? readerPdfPageRange(annotation.position)
              : undefined;
          const replyDraft = replyDrafts[annotation.id] ?? "";
          const replyPrompt =
            annotation.mode === "highlight"
              ? annotation.audience.kind === "project"
                ? t("startDiscussion")
                : t("addNote")
              : annotation.mode === "note"
                ? t("continueNote")
                : t("replyPlaceholder");
          return (
            <Frame
              className={cn(
                "motion-control group/thread group/interactive-row hover:bg-hover focus-within:bg-hover active:bg-pressed max-w-full",
                active && "border-line-strong",
              )}
              data-reader-annotation-card={annotation.id}
              data-current={active ? "" : undefined}
              key={annotation.id}
              onBlur={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget)) {
                  onPreviewChange(undefined);
                }
              }}
              onFocusCapture={() => onPreviewChange(annotation.id)}
              onMouseEnter={() => onPreviewChange(annotation.id)}
              onMouseLeave={() => onPreviewChange(undefined)}
              role="article"
              spacing="compact"
            >
              <div className="flex items-start gap-1 px-3 pt-2.5">
                <button
                  className={cn(
                    "min-w-0 flex-1 rounded-[var(--radius-sm)] text-left",
                    focusSurfaceVariants({ intent: "neutral" }),
                  )}
                  onClick={() => onSelect(annotation.id)}
                  type="button"
                >
                  <span className="text-secondary flex min-w-0 items-center gap-1.5 text-xs">
                    <span
                      aria-hidden
                      className="h-3 w-1 shrink-0 rounded-full"
                      style={{
                        backgroundColor:
                          readerHighlightColorValue(currentColor),
                      }}
                    />
                    <span className="text-foreground truncate font-medium">
                      {annotation.audience.kind === "project"
                        ? (projectContext?.title ?? t("audience.project"))
                        : t("audience.personal")}
                      {" · "}
                      {t(`modes.${annotation.mode}`)}
                    </span>
                    <span aria-hidden>·</span>
                    <span className="shrink-0">
                      {pageRange && pageRange.start !== pageRange.end
                        ? t("pageRange", pageRange)
                        : t("page", {
                            page: annotation.position?.page_number ?? 1,
                          })}
                    </span>
                    {annotation.mode === "discussion" &&
                    annotation.status === "resolved" ? (
                      <span className="text-success shrink-0">
                        {t("status.resolved")}
                      </span>
                    ) : null}
                  </span>
                  <span
                    className="text-secondary mt-1.5 block truncate border-l pl-2 text-sm leading-5"
                    data-reader-annotation-quote
                    style={{
                      borderColor: readerHighlightColorValue(currentColor),
                    }}
                  >
                    <bdi>{annotation.quote_text}</bdi>
                  </span>
                </button>
                {annotation.capabilities.resolve ? (
                  <IconButton
                    className="-mt-1 size-8 min-h-8 shrink-0"
                    label={t("resolve")}
                    loading={busyAction === `resolve:${annotation.id}`}
                    onClick={() =>
                      void perform(`resolve:${annotation.id}`, () =>
                        onStatusChange(annotation.id, "resolved"),
                      )
                    }
                    variant="ghost"
                  >
                    <Icon glyph={ConfirmIcon} size={16} tone="secondary" />
                  </IconButton>
                ) : annotation.capabilities.reopen ? (
                  <IconButton
                    className="-mt-1 size-8 min-h-8 shrink-0"
                    label={t("reopen")}
                    loading={busyAction === `reopen:${annotation.id}`}
                    onClick={() =>
                      void perform(`reopen:${annotation.id}`, () =>
                        onStatusChange(annotation.id, "open"),
                      )
                    }
                    variant="ghost"
                  >
                    <Icon glyph={ReopenIcon} size={16} tone="secondary" />
                  </IconButton>
                ) : null}
                {annotation.capabilities.recolor ||
                annotation.capabilities.delete ? (
                  <DropdownMenu
                    onOpenChange={(open) => {
                      if (!open) setColorMenuThreadId(undefined);
                    }}
                  >
                    <DropdownMenuTrigger asChild>
                      <OverflowMenuButton
                        className="-mt-1 shrink-0"
                        label={t("moreActions")}
                        visibility="contextual"
                      />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align="end"
                      className="bg-elevated w-48"
                    >
                      {colorMenuThreadId === annotation.id ? (
                        <>
                          <DropdownMenuLabel>
                            {t("changeColor")}
                          </DropdownMenuLabel>
                          {readerHighlightColors.map((color) => (
                            <DropdownMenuItem
                              key={color}
                              onSelect={() =>
                                void perform(`color:${annotation.id}`, () =>
                                  onUpdateColor(annotation.id, color),
                                )
                              }
                            >
                              <span
                                aria-hidden
                                className="border-control size-4 shrink-0 rounded-full border"
                                style={{
                                  backgroundColor:
                                    readerHighlightColorValue(color),
                                }}
                              />
                              <span className="min-w-0 flex-1 truncate">
                                {t(`colors.${color}`)}
                              </span>
                              {currentColor === color ? (
                                <Icon glyph={ConfirmIcon} size={16} />
                              ) : null}
                            </DropdownMenuItem>
                          ))}
                        </>
                      ) : (
                        <>
                          {annotation.capabilities.recolor ? (
                            <DropdownMenuItem
                              onSelect={(event) => {
                                event.preventDefault();
                                setColorMenuThreadId(annotation.id);
                              }}
                            >
                              <Icon
                                glyph={HighlightColorIcon}
                                size={16}
                                tone="secondary"
                              />
                              {t("changeColor")}
                            </DropdownMenuItem>
                          ) : null}
                          {annotation.capabilities.recolor &&
                          annotation.capabilities.delete ? (
                            <DropdownMenuSeparator />
                          ) : null}
                          {annotation.capabilities.delete ? (
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
                        </>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : null}
              </div>

              <FramePanel
                className="overflow-visible"
                spacing="compact"
                variant={active ? "raised" : "flat"}
              >
                <div className="text-secondary mt-1.5 flex items-center gap-1.5 text-xs">
                  <span className="truncate">
                    {annotation.created_by.display_name ?? t("unknownAuthor")}
                  </span>
                  <span aria-hidden>·</span>
                  <span className="shrink-0">
                    {formatRelativeTime(annotation.last_activity_at)}
                  </span>
                  {annotation.comment_count > 0 ? (
                    <span className="ml-auto inline-flex shrink-0 items-center gap-1">
                      <Icon glyph={CommentIcon} size={16} />
                      {annotation.comment_count}
                    </span>
                  ) : null}
                </div>

                {annotation.status === "resolved" && annotation.resolved_at ? (
                  <p className="text-secondary mt-2 text-xs">
                    {t("resolvedBy", {
                      author:
                        annotation.resolved_by?.display_name ??
                        t("unknownAuthor"),
                      time: formatRelativeTime(annotation.resolved_at),
                    })}
                  </p>
                ) : null}

                {annotation.comments.length > 0 ? (
                  <div className="border-line-subtle mt-2 border-t pt-1">
                    {annotation.comments.map((item) => (
                      <div
                        className="motion-control group/comment group/interactive-row hover:bg-hover focus-within:bg-hover relative mt-2.5 grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-2 rounded-[var(--radius-md)]"
                        key={item.id}
                      >
                        {editingCommentId === item.id ? (
                          <>
                            <Avatar
                              className="size-7 text-xs"
                              fallback={(
                                item.created_by.display_name ??
                                t("unknownAuthor")
                              )
                                .trim()
                                .charAt(0)
                                .toLocaleUpperCase()}
                              sizes="28px"
                              source={item.created_by.avatar}
                            />
                            <div className="min-w-0">
                              <Textarea
                                className="min-h-16 text-sm"
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
                            </div>
                          </>
                        ) : (
                          <>
                            <Avatar
                              className="size-7 text-xs"
                              fallback={(
                                item.created_by.display_name ??
                                t("unknownAuthor")
                              )
                                .trim()
                                .charAt(0)
                                .toLocaleUpperCase()}
                              sizes="28px"
                              source={item.created_by.avatar}
                            />
                            <div className="min-w-0">
                              <div className="flex min-h-7 items-center gap-1.5 text-xs">
                                <span className="truncate font-medium">
                                  {item.created_by.display_name ??
                                    t("unknownAuthor")}
                                </span>
                                <span className="text-secondary shrink-0">
                                  {formatRelativeTime(item.created_at)}
                                </span>
                                {item.can_edit || item.can_delete ? (
                                  <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                      <OverflowMenuButton
                                        className="ml-auto"
                                        label={t("commentActions")}
                                        visibility="contextual"
                                      />
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent
                                      align="end"
                                      className="bg-elevated"
                                    >
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
                                ) : null}
                              </div>
                              <p className="text-sm leading-5 break-words whitespace-pre-wrap">
                                {item.content}
                              </p>
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                ) : null}

                {annotation.capabilities.reply ? (
                  <form
                    aria-busy={replyBusyId === annotation.id}
                    className="mt-3"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void submitReply(annotation);
                    }}
                  >
                    <Input
                      className="h-9"
                      disabled={replyBusyId === annotation.id}
                      onChange={(event) => {
                        const value = event.currentTarget.value;
                        setReplyDrafts((current) => ({
                          ...current,
                          [annotation.id]: value,
                        }));
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && !isImeComposing(event)) {
                          event.preventDefault();
                          void submitReply(annotation);
                        }
                      }}
                      placeholder={replyPrompt}
                      value={replyDraft}
                    />
                    <button
                      className="sr-only"
                      disabled={!replyDraft.trim() || Boolean(replyBusyId)}
                      tabIndex={-1}
                      type="submit"
                    >
                      {annotation.mode === "highlight"
                        ? annotation.audience.kind === "project"
                          ? t("start")
                          : t("add")
                        : t("reply")}
                    </button>
                  </form>
                ) : null}
              </FramePanel>
            </Frame>
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

export type ReaderContextPanelProps = {
  annotations: ReaderAnnotationSummary[];
  annotationsError: boolean;
  className?: string;
  conversationId?: string;
  conversationSession: ReturnType<typeof useConversationSession>;
  conversations: ReaderConversation[];
  conversationsLoading: boolean;
  context: ResearchContext;
  onContextChange: (context: ResearchContext) => void;
  papers: ResearchContextPaperOption[];
  projects: ResearchContextProjectOption[];
  document: ReaderDocument | undefined;
  onActionError: (error?: unknown) => void;
  onAnnotationDelete: (id: string) => Promise<void>;
  onAnnotationPreviewChange: (id: string | undefined) => void;
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
  onPanelChange: (panel: ReaderContextPanel) => void;
  onSourceOpen: (source: ReaderDocumentSource) => void;
  panel: ReaderContextPanel;
  projectContext?: { id: string; title: string };
  reasoningLevel: ReasoningLevel;
  selectedAnnotationId?: string;
  annotationSelection?: ReaderSelection;
  annotationInitialComment?: string;
  pendingTurnContext?: ReaderSelection;
  onTurnContextClear: () => void;
  setReasoningLevel: (level: ReasoningLevel) => void;
  title: string;
  insightsPanel?: React.ReactNode;
  translationPanel: React.ReactNode;
};

export function ReaderContextPanel({
  annotations,
  annotationsError,
  className,
  conversationId,
  conversationSession,
  conversations,
  conversationsLoading,
  context,
  onContextChange,
  papers,
  projects,
  document,
  onActionError,
  onAnnotationDelete,
  onAnnotationPreviewChange,
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
  selectedAnnotationId,
  annotationSelection,
  annotationInitialComment,
  pendingTurnContext,
  onTurnContextClear,
  setReasoningLevel,
  title,
  insightsPanel,
  translationPanel,
}: ReaderContextPanelProps) {
  const t = useTranslations("Reader");
  const activePanel = panel;
  let turnContextLabel: string | undefined;
  if (pendingTurnContext) {
    const range = readerPdfPageRange(pendingTurnContext.anchor);
    turnContextLabel =
      range.start === range.end
        ? t("selection.context", { page: range.start })
        : t("selection.contextRange", range);
  } else if (selectedAnnotationId) {
    turnContextLabel = t("annotations.context");
  }

  return (
    <aside
      aria-label={t("contextPanel")}
      className={cn(
        "border-line bg-canvas h-full w-full shrink-0 flex-col overflow-hidden border-l lg:w-[clamp(23rem,34vw,31.25rem)]",
        className ?? "flex",
      )}
    >
      <div className="border-line flex h-14 shrink-0 items-center gap-1 border-b px-3">
        <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto overscroll-x-contain">
          {(
            [
              "ask",
              "annotations",
              "translation",
              "insights",
              "details",
            ] as const
          ).map((item) => (
            <Button
              className={cn(
                "h-9 min-h-9 shrink-0 px-2",
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
        </div>
        <IconButton
          autoFocus
          className="shrink-0"
          label={t("toolbar.closePanel")}
          onClick={onClose}
          variant="ghost"
        >
          <Icon glyph={ClosePanelIcon} size={20} />
        </IconButton>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        <AnimatePresence initial={false} mode="popLayout">
          <MotionPresence
            animate="animate"
            className="h-full min-h-0"
            data-reader-panel-content={activePanel}
            exit="exit"
            initial="initial"
            key={activePanel}
            variants={motionVariants.swap}
          >
            {activePanel === "translation" ? (
              translationPanel
            ) : activePanel === "insights" ? (
              (insightsPanel ?? (
                <div className="grid h-full place-items-center p-5 text-center">
                  <p className="text-secondary max-w-xs text-sm">
                    {t("insights.unavailable")}
                  </p>
                </div>
              ))
            ) : activePanel === "details" ? (
              <div
                className={cn(
                  "h-full overflow-y-auto",
                  focusSurfaceVariants({ intent: "scroll" }),
                )}
                tabIndex={0}
              >
                <ReaderDetailsPanel document={document} title={title} />
              </div>
            ) : activePanel === "annotations" ? (
              <div
                className={cn(
                  "h-full min-w-0 overflow-x-hidden overflow-y-auto",
                  focusSurfaceVariants({ intent: "scroll" }),
                )}
                data-reader-annotations-scroll
                tabIndex={0}
              >
                <ReaderAnnotationPanel
                  key={`${projectContext?.id ?? "personal"}:${annotationSelection?.page_number ?? "none"}:${annotationSelection?.selected_text ?? ""}:${annotationInitialComment ?? ""}`}
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
                  onPreviewChange={onAnnotationPreviewChange}
                  onSelect={onAnnotationSelect}
                  onStatusChange={onAnnotationStatusChange}
                  onStatusFilterChange={onAnnotationStatusFilterChange}
                  onUpdateColor={onHighlightUpdate}
                  projectContext={projectContext}
                  selectedAnnotationId={selectedAnnotationId}
                  annotationSelection={annotationSelection}
                  annotationInitialComment={annotationInitialComment}
                  statusFilter={annotationStatusFilter}
                />
              </div>
            ) : (
              <div className="flex h-full min-h-0 flex-col">
                <ConversationSwitcher
                  activeId={conversationId}
                  beforeNewAction={
                    <ReasoningMenu
                      className="lg:hidden"
                      onChange={setReasoningLevel}
                      value={reasoningLevel}
                      variant="panelHeader"
                    />
                  }
                  conversations={conversations}
                  labels={{
                    empty: t("conversations.empty"),
                    loading: t("conversations.loading"),
                    new: t("conversations.new"),
                    newDraft: t("conversations.newDraft"),
                    pin: t("conversations.pin"),
                    pinned: t("conversations.pinned"),
                    recent: t("conversations.recent"),
                    search: t("conversations.search"),
                    switcher: t("conversations.switcher"),
                    unpin: t("conversations.unpin"),
                  }}
                  loading={conversationsLoading}
                  onChange={onConversationChange}
                  onNew={onConversationNew}
                  onPin={onConversationPin}
                  onPinError={onActionError}
                />
                <ConversationView
                  layout="side-panel"
                  canSend={conversationSession.canSend}
                  completionAnnouncementId={
                    conversationSession.completionAnnouncementId
                  }
                  composerForm={conversationSession.composerForm}
                  context={context}
                  error={
                    !conversationSession.submissionPending &&
                    conversationSession.turnsQuery.isError
                  }
                  emptyState={{
                    description: t("conversations.emptyDescription"),
                    title: t("conversations.emptyTitle"),
                  }}
                  liveTurn={conversationSession.liveTurn}
                  loading={
                    conversationSession.turnsQuery.isPending &&
                    Boolean(conversationId) &&
                    !conversationSession.submissionPending
                  }
                  onContextChange={onContextChange}
                  onDocumentSourceOpen={onSourceOpen}
                  onReasoningLevelChange={setReasoningLevel}
                  onRetry={() => void conversationSession.turnsQuery.refetch()}
                  onRetryResponse={(turn) =>
                    void conversationSession.retryResponse(turn)
                  }
                  onEditMessage={(turn, message) =>
                    conversationSession.editMessage(turn, message)
                  }
                  onLiveContentVisible={conversationSession.markContentVisible}
                  onSelectBranch={(turnId) =>
                    void conversationSession.selectBranch(turnId)
                  }
                  onSelectResponse={(turnId, responseId) =>
                    void conversationSession.selectResponse(turnId, responseId)
                  }
                  onStop={conversationSession.stop}
                  onSubmit={conversationSession.sendMessage}
                  onUseSuggestion={conversationSession.useSuggestion}
                  onTurnContextClear={onTurnContextClear}
                  papers={papers}
                  projects={projects}
                  reasoningLevel={reasoningLevel}
                  readOnlyReason={
                    conversationSession.conversationQuery.data?.read_only_reason
                  }
                  stopAvailable={conversationSession.stopAvailable}
                  submissionPending={conversationSession.submissionPending}
                  turnContextLabel={turnContextLabel}
                  turns={conversationSession.turnsQuery.data?.items ?? []}
                />
              </div>
            )}
          </MotionPresence>
        </AnimatePresence>
      </div>
    </aside>
  );
}
