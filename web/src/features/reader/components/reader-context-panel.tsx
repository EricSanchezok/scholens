"use client";

import {
  Check,
  EditPencil,
  List,
  NavArrowDown,
  Pin,
  Plus,
  SidebarCollapse,
  Trash,
} from "iconoir-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import {
  Button,
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
import type { ReaderSelection } from "./pdf-page";
import type {
  ReaderAnnotation,
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
            <Icon glyph={Check} size={16} />
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
            glyph={Pin}
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
            <Icon glyph={NavArrowDown} size={16} tone="secondary" />
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
        <Icon glyph={Plus} size={20} />
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
  onSelect,
  onUpdateColor,
  selectedAnnotation,
  annotationSelection,
}: {
  annotations: ReaderAnnotation[];
  error: boolean;
  onActionError: () => void;
  onCommentCreate: (id: string, content: string) => Promise<void>;
  onCommentDelete: (id: string) => Promise<void>;
  onCommentUpdate: (id: string, content: string) => Promise<void>;
  onCreate: (comment?: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onSelect: (id: string) => void;
  onUpdateColor: (id: string, color: string) => Promise<void>;
  selectedAnnotation?: ReaderAnnotation;
  annotationSelection?: ReaderSelection;
}) {
  const t = useTranslations("Reader.annotations");
  const [selectionComment, setSelectionComment] = React.useState("");
  const [replyContent, setReplyContent] = React.useState("");
  const [editingCommentId, setEditingCommentId] = React.useState<string>();
  const [editingContent, setEditingContent] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  async function perform(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch {
      onActionError();
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return <p className="text-danger p-5 text-sm">{t("error")}</p>;
  }

  return (
    <div className="grid gap-4 p-4">
      {annotationSelection && (
        <section className="border-line bg-subtle rounded-[var(--radius-lg)] border p-3">
          <p className="text-secondary line-clamp-4 text-sm leading-5">
            “{annotationSelection.selected_text}”
          </p>
          <Textarea
            className="mt-3 min-h-20"
            onChange={(event) => setSelectionComment(event.currentTarget.value)}
            placeholder={t("commentPlaceholder")}
            value={selectionComment}
          />
          <Button
            className="mt-2 w-full"
            disabled={busy}
            onClick={() =>
              void perform(async () => {
                await onCreate(selectionComment.trim() || undefined);
                setSelectionComment("");
              })
            }
            size="sm"
          >
            {t("saveSelection")}
          </Button>
        </section>
      )}
      {annotations.length === 0 && !annotationSelection ? (
        <div className="grid min-h-48 place-items-center text-center">
          <div>
            <Icon glyph={List} size={24} tone="secondary" />
            <p className="mt-3 text-sm font-medium">{t("emptyTitle")}</p>
            <p className="text-muted mt-1 max-w-64 text-sm">
              {t("emptyDescription")}
            </p>
          </div>
        </div>
      ) : (
        annotations.map((annotation) => {
          const thread = annotation.highlight_thread;
          if (!thread) return null;
          const active = selectedAnnotation?.id === annotation.id;
          return (
            <article
              className={cn(
                "border-line rounded-[var(--radius-lg)] border p-3",
                active && "bg-subtle",
              )}
              key={annotation.id}
            >
              <button
                className="w-full text-left"
                onClick={() => onSelect(annotation.id)}
                type="button"
              >
                <span className="text-muted text-xs">
                  {t("page", {
                    page: thread.position?.page_number ?? 1,
                  })}
                </span>
                <span className="mt-1 line-clamp-4 block text-sm leading-5">
                  “{thread.quote_text}”
                </span>
              </button>
              <div className="mt-3 flex items-center gap-1">
                {(["yellow", "blue", "green", "neutral"] as const).map(
                  (color) => (
                    <button
                      aria-label={t(`colors.${color}`)}
                      className={cn(
                        "border-control size-6 rounded-full border",
                        color === "yellow" && "bg-state-warning-bg",
                        color === "blue" && "bg-state-info-bg",
                        color === "green" && "bg-state-success-bg",
                        color === "neutral" && "bg-accent",
                        thread.color === color &&
                          "ring-2 ring-[var(--color-border-focus)] ring-offset-1",
                      )}
                      disabled={!annotation.capabilities.edit || busy}
                      key={color}
                      onClick={() =>
                        void perform(() => onUpdateColor(annotation.id, color))
                      }
                      type="button"
                    />
                  ),
                )}
                {annotation.capabilities.delete && (
                  <IconButton
                    className="ml-auto size-8 min-h-8"
                    disabled={busy}
                    label={t("deleteHighlight")}
                    onClick={() => void perform(() => onDelete(annotation.id))}
                    variant="ghost"
                  >
                    <Icon glyph={Trash} size={16} tone="secondary" />
                  </IconButton>
                )}
              </div>
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
                          disabled={!editingContent.trim() || busy}
                          onClick={() =>
                            void perform(async () => {
                              await onCommentUpdate(
                                item.id,
                                editingContent.trim(),
                              );
                              setEditingCommentId(undefined);
                            })
                          }
                          size="sm"
                        >
                          {t("save")}
                        </Button>
                      </div>
                    </>
                  ) : (
                    <>
                      <p className="text-sm leading-5">{item.content}</p>
                      <div className="mt-1 flex justify-end gap-0.5">
                        {item.can_edit && (
                          <IconButton
                            className="size-8 min-h-8"
                            label={t("editComment")}
                            onClick={() => {
                              setEditingCommentId(item.id);
                              setEditingContent(item.content);
                            }}
                            variant="ghost"
                          >
                            <Icon
                              glyph={EditPencil}
                              size={16}
                              tone="secondary"
                            />
                          </IconButton>
                        )}
                        {item.can_delete && (
                          <IconButton
                            className="size-8 min-h-8"
                            label={t("deleteComment")}
                            onClick={() =>
                              void perform(() => onCommentDelete(item.id))
                            }
                            variant="ghost"
                          >
                            <Icon glyph={Trash} size={16} tone="secondary" />
                          </IconButton>
                        )}
                      </div>
                    </>
                  )}
                </div>
              ))}
              {active && (
                <form
                  className="mt-3 flex gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!replyContent.trim()) return;
                    void perform(async () => {
                      await onCommentCreate(annotation.id, replyContent.trim());
                      setReplyContent("");
                    });
                  }}
                >
                  <Textarea
                    className="min-h-16"
                    onChange={(event) =>
                      setReplyContent(event.currentTarget.value)
                    }
                    placeholder={t("replyPlaceholder")}
                    value={replyContent}
                  />
                  <Button
                    disabled={!replyContent.trim() || busy}
                    size="sm"
                    type="submit"
                  >
                    {t("add")}
                  </Button>
                </form>
              )}
            </article>
          );
        })
      )}
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
  onPanelChange,
  onSourceOpen,
  panel,
  reasoningLevel,
  selectedAnnotation,
  annotationSelection,
  pendingTurnContext,
  onTurnContextClear,
  setReasoningLevel,
  title,
}: {
  annotations: ReaderAnnotation[];
  annotationsError: boolean;
  className?: string;
  conversationId?: string;
  conversationSession: ReturnType<typeof useConversationSession>;
  conversations: ReaderConversation[];
  conversationsLoading: boolean;
  document: ReaderDocument | undefined;
  onActionError: () => void;
  onAnnotationDelete: (id: string) => Promise<void>;
  onAnnotationSelect: (id: string) => void;
  onClose: () => void;
  onCommentCreate: (id: string, content: string) => Promise<void>;
  onCommentDelete: (id: string) => Promise<void>;
  onCommentUpdate: (id: string, content: string) => Promise<void>;
  onConversationChange: (id: string) => void;
  onConversationNew: () => void;
  onConversationPin: (id: string, pinned: boolean) => Promise<void>;
  onHighlightCreate: (comment?: string) => Promise<void>;
  onHighlightUpdate: (id: string, color: string) => Promise<void>;
  onPanelChange: (panel: "ask" | "annotations" | "details") => void;
  onSourceOpen: (source: ReaderDocumentSource) => void;
  panel: ReaderContextPanel;
  reasoningLevel: ReasoningLevel;
  selectedAnnotation?: ReaderAnnotation;
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
          <Icon glyph={SidebarCollapse} size={20} />
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
              annotations={annotations}
              error={annotationsError}
              onActionError={onActionError}
              onCommentCreate={onCommentCreate}
              onCommentDelete={onCommentDelete}
              onCommentUpdate={onCommentUpdate}
              onCreate={onHighlightCreate}
              onDelete={onAnnotationDelete}
              onSelect={onAnnotationSelect}
              onUpdateColor={onHighlightUpdate}
              selectedAnnotation={selectedAnnotation}
              annotationSelection={annotationSelection}
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
