"use client";

import {
  ExpandIcon,
  PreviousIcon,
  NextIcon,
  RegenerateIcon,
  WarningIcon,
} from "@/design-system/icons/semantic-icons";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button, IconButton, keyboardFocusRing } from "@/components/ui";
import { CopyActionButton } from "@/components/feedback";
import { Icon } from "@/design-system/icons/icon";
import {
  AnimatePresence,
  m,
  MotionPresence,
  motionTransitions,
  motionVariants,
} from "@/design-system/motion";
import type { components } from "@/lib/api/generated/schema";
import type {
  ConversationFailure,
  ProvisionalAssistantItem,
  ConversationTraceEntry,
  LiveTurn,
} from "../conversation-state";
import type { ComposerValues } from "../schemas";
import type { UseFormReturn } from "react-hook-form";
import {
  ResearchComposer,
  type ReasoningLevel,
  type ResearchContext,
} from "./research-composer";
import { MessageContent } from "./message-content";
import { ConversationWorklog } from "./conversation-worklog";
import { ConversationUserMessage } from "./conversation-user-message";
import {
  ConversationSources,
  isReferenceBundle,
  referenceSourceCount,
} from "./conversation-sources";
import { useConversationAutoScroll } from "../use-conversation-auto-scroll";

export type ConversationTurn =
  components["schemas"]["ConversationTurnResponse"];
export type ConversationResponseVariant =
  components["schemas"]["ConversationResponseVariantResponse"];
export type RetryableConversationTurn = Pick<
  ConversationTurn,
  "id" | "user_query" | "depth"
>;
export type ConversationViewLayout = "workspace" | "side-panel";
export type ConversationEmptyState = {
  description: string;
  title: string;
};
type LibraryPaper = components["schemas"]["LibraryPaperResponse"];
type Project = components["schemas"]["ProjectResponse"];

function FollowUpSuggestions({
  suggestions,
  onUseSuggestion,
}: {
  suggestions: string[];
  onUseSuggestion: (suggestion: string) => void;
}) {
  const t = useTranslations("Home.conversation");

  if (suggestions.length !== 3) return null;

  return (
    <section
      aria-label={t("suggestions")}
      className="settled-content-enter grid justify-items-start gap-2 lg:justify-items-stretch lg:gap-0"
    >
      {suggestions.map((suggestion) => (
        <button
          className={`motion-control bg-subtle hover:bg-hover active:bg-pressed lg:border-line-subtle lg:text-secondary lg:hover:text-foreground lg:focus-visible:text-foreground min-h-11 max-w-full rounded-full px-4 py-2 text-left text-sm leading-5 lg:-mx-3 lg:min-h-10 lg:w-auto lg:rounded-[var(--radius-sm)] lg:border-t lg:bg-transparent lg:px-3 lg:py-2.5 lg:first:border-t-0 ${keyboardFocusRing}`}
          key={suggestion}
          onClick={() => onUseSuggestion(suggestion)}
          type="button"
        >
          {suggestion}
        </button>
      ))}
    </section>
  );
}

function AssistantMessage({
  entries,
  content,
  provisionalItems,
  references,
  sourceTotal,
  state,
  failure,
  historical,
  onActivityOpenChange,
  response,
  suggestions,
  variants,
  canRetry,
  canSwitch,
  onRetryResponse,
  onSelectResponse,
  onUseSuggestion,
  onDocumentSourceOpen,
  durationMs,
  startedAtMs,
}: {
  entries: ConversationTraceEntry[];
  content: string;
  provisionalItems?: ProvisionalAssistantItem[];
  references: unknown;
  sourceTotal: number;
  state: LiveTurn["state"];
  failure?: ConversationFailure | null;
  historical?: boolean;
  onActivityOpenChange?: (open: boolean) => void;
  response?: ConversationResponseVariant;
  suggestions?: string[] | null;
  variants?: ConversationResponseVariant[];
  canRetry?: boolean;
  canSwitch?: boolean;
  onRetryResponse?: () => void;
  onSelectResponse?: (responseId: string) => void;
  onUseSuggestion?: (suggestion: string) => void;
  onDocumentSourceOpen?: (
    source: components["schemas"]["DocumentAnswerSource"],
  ) => void;
  durationMs?: number | null;
  startedAtMs?: number;
}) {
  const t = useTranslations("Home.conversation");
  const [sourcesOpen, setSourcesOpen] = React.useState(false);
  const [selectedSourceKey, setSelectedSourceKey] = React.useState<
    number | undefined
  >();
  const visibleContent = content;
  const presentationState =
    content && state === "streaming" ? "complete" : state;
  const orderedVariants = canSwitch
    ? [...(variants ?? [])]
        .filter((candidate) => candidate.status === "completed")
        .sort((left, right) => left.variant_index - right.variant_index)
    : [];
  const selectedVariantIndex = orderedVariants.findIndex(
    (candidate) => candidate.id === response?.id,
  );
  const completedActionsVisible = Boolean(
    response?.status === "completed" &&
    visibleContent &&
    (state === "ready" || state === "complete"),
  );
  const terminalRetryVisible = Boolean(
    canRetry &&
    onRetryResponse &&
    (response?.status === "failed" ||
      response?.status === "cancelled" ||
      state === "error" ||
      state === "cancelled"),
  );
  return (
    <article aria-label={t("assistantMessage")} className="grid gap-2 lg:gap-3">
      <ConversationWorklog
        entries={entries}
        failure={failure ?? null}
        historical={historical}
        onOpenChange={onActivityOpenChange}
        provisionalItems={provisionalItems ?? []}
        sourceTotal={sourceTotal}
        state={presentationState}
        durationMs={durationMs}
        startedAtMs={startedAtMs}
      />
      {visibleContent && (
        <MessageContent
          annotations={
            isReferenceBundle(references) ? references.annotations : undefined
          }
          content={visibleContent}
          onCitationOpen={(sourceKeys) => {
            setSelectedSourceKey(sourceKeys[0]);
            setSourcesOpen(true);
          }}
        />
      )}
      {(completedActionsVisible || terminalRetryVisible || suggestions) && (
        <footer className="grid gap-2 lg:max-w-2xl lg:gap-1">
          {(completedActionsVisible || terminalRetryVisible) && (
            <div
              className="settled-content-enter flex min-h-11 flex-wrap items-center gap-0 lg:min-h-8 lg:pt-1"
              role="group"
              aria-label={t("answerActions")}
            >
              {completedActionsVisible && (
                <>
                  {canSwitch &&
                    orderedVariants.length > 1 &&
                    selectedVariantIndex >= 0 &&
                    onSelectResponse && (
                      <div className="text-secondary flex h-11 items-center lg:h-8">
                        <IconButton
                          className="size-11 bg-transparent disabled:bg-transparent disabled:opacity-100 lg:size-8 lg:min-h-8"
                          disabled={selectedVariantIndex <= 0}
                          label={t("previousResponse")}
                          onClick={() =>
                            onSelectResponse(
                              orderedVariants[selectedVariantIndex - 1]!.id,
                            )
                          }
                          variant="ghost"
                        >
                          <Icon
                            glyph={PreviousIcon}
                            size={20}
                            tone="secondary"
                          />
                        </IconButton>
                        <span
                          aria-label={t("responseVersion", {
                            current: selectedVariantIndex + 1,
                            total: orderedVariants.length,
                          })}
                          className="text-foreground min-w-10 text-center text-sm font-medium tabular-nums"
                        >
                          {selectedVariantIndex + 1} / {orderedVariants.length}
                        </span>
                        <IconButton
                          className="size-11 bg-transparent disabled:bg-transparent disabled:opacity-100 lg:size-8 lg:min-h-8"
                          disabled={
                            selectedVariantIndex >= orderedVariants.length - 1
                          }
                          label={t("nextResponse")}
                          onClick={() =>
                            onSelectResponse(
                              orderedVariants[selectedVariantIndex + 1]!.id,
                            )
                          }
                          variant="ghost"
                        >
                          <Icon glyph={NextIcon} size={20} tone="secondary" />
                        </IconButton>
                      </div>
                    )}
                  <CopyActionButton
                    className="size-11 bg-transparent lg:size-8 lg:min-h-8"
                    errorLabel={t("copyFailed")}
                    label={t("copy")}
                    pendingLabel={t("copying")}
                    successLabel={t("copied")}
                    value={visibleContent}
                  />
                  <ConversationSources
                    onDocumentOpen={onDocumentSourceOpen}
                    onOpenChange={(open) => {
                      setSourcesOpen(open);
                      if (!open) setSelectedSourceKey(undefined);
                    }}
                    open={sourcesOpen}
                    references={references}
                    selectedSourceKey={selectedSourceKey}
                  />
                </>
              )}
              {canRetry && onRetryResponse && (
                <IconButton
                  className="size-11 bg-transparent lg:size-8 lg:min-h-8"
                  label={t("regenerate")}
                  onClick={onRetryResponse}
                  variant="ghost"
                >
                  <Icon glyph={RegenerateIcon} size={16} tone="secondary" />
                </IconButton>
              )}
            </div>
          )}
          {onUseSuggestion && suggestions && (
            <FollowUpSuggestions
              onUseSuggestion={onUseSuggestion}
              suggestions={suggestions}
            />
          )}
        </footer>
      )}
    </article>
  );
}

function selectedResponse(turn: ConversationTurn) {
  return (
    turn.responses.find(
      (response) => response.id === turn.selected_response_id,
    ) ??
    [...turn.responses].sort(
      (left, right) => right.variant_index - left.variant_index,
    )[0]
  );
}

function MessageHistory({
  turns,
  liveTurn,
  canSend,
  suppressLatestControls,
  onRetryResponse,
  onSelectResponse,
  onEditMessage,
  onSelectBranch,
  onUseSuggestion,
  onDocumentSourceOpen,
}: {
  turns: ConversationTurn[];
  liveTurn: LiveTurn | null;
  canSend: boolean;
  suppressLatestControls: boolean;
  onRetryResponse: (turn: RetryableConversationTurn) => void;
  onSelectResponse: (turnId: string, responseId: string) => void;
  onEditMessage: (turn: ConversationTurn, message: string) => Promise<void>;
  onSelectBranch: (turnId: string) => void;
  onUseSuggestion: (suggestion: string) => void;
  onDocumentSourceOpen?: (
    source: components["schemas"]["DocumentAnswerSource"],
  ) => void;
}) {
  const latestTurnId = turns.at(-1)?.id;
  return (
    <AnimatePresence initial={false}>
      {turns.map((turn) => {
        const response = selectedResponse(turn);
        const isLive = liveTurn?.turnId === turn.id;
        const readyTurn = isLive ? liveTurn?.readyTurn : null;
        const liveResponse = readyTurn
          ? readyTurn.responses.find(
              (candidate) => candidate.id === liveTurn?.responseId,
            )
          : undefined;
        const latestControlsVisible =
          turn.id === latestTurnId && !suppressLatestControls;
        return (
          <MotionPresence
            animate="animate"
            className="grid gap-9 lg:gap-8"
            exit="exit"
            initial="initial"
            key={turn.id}
            layout="position"
            transition={motionTransitions.layout}
            variants={motionVariants.listItem}
          >
            <ConversationUserMessage
              branch={turn.branch}
              canEdit={canSend}
              message={turn.user_query}
              onEdit={(message) => onEditMessage(turn, message)}
              onSelectBranch={onSelectBranch}
            />
            {isLive && liveTurn ? (
              <AssistantMessage
                canRetry={
                  latestControlsVisible &&
                  canSend &&
                  (liveTurn.state === "ready" ||
                    liveTurn.state === "complete" ||
                    liveTurn.state === "error" ||
                    liveTurn.state === "cancelled")
                }
                canSwitch={
                  latestControlsVisible &&
                  Boolean(readyTurn && readyTurn.responses.length > 1)
                }
                content={liveTurn.content}
                entries={liveTurn.entries}
                failure={liveTurn.failure}
                onRetryResponse={() => onRetryResponse(readyTurn ?? turn)}
                onSelectResponse={(responseId) =>
                  onSelectResponse(turn.id, responseId)
                }
                onUseSuggestion={
                  latestControlsVisible ? onUseSuggestion : undefined
                }
                onDocumentSourceOpen={onDocumentSourceOpen}
                provisionalItems={liveTurn.provisionalItems}
                references={liveTurn.references}
                response={liveResponse}
                sourceTotal={
                  liveTurn.trace?.citation_summary?.source_count ??
                  referenceSourceCount(liveTurn.references)
                }
                state={liveTurn.state}
                suggestions={liveTurn.suggestions}
                variants={readyTurn?.responses}
                durationMs={liveTurn.durationMs}
                startedAtMs={liveTurn.startedAtMs}
              />
            ) : response ? (
              <AssistantMessage
                canRetry={latestControlsVisible && canSend}
                canSwitch={latestControlsVisible}
                content={response.content ?? ""}
                entries={response.trace?.entries ?? []}
                historical
                onRetryResponse={() => onRetryResponse(turn)}
                onSelectResponse={(responseId) =>
                  onSelectResponse(turn.id, responseId)
                }
                onUseSuggestion={
                  latestControlsVisible ? onUseSuggestion : undefined
                }
                onDocumentSourceOpen={onDocumentSourceOpen}
                references={response.references}
                response={response}
                sourceTotal={
                  response.trace?.citation_summary?.source_count ??
                  referenceSourceCount(response.references)
                }
                state={
                  response.status === "cancelled"
                    ? "cancelled"
                    : response.status === "failed"
                      ? "error"
                      : response.status === "running"
                        ? "streaming"
                        : "complete"
                }
                suggestions={turn.suggestions}
                failure={null}
                variants={turn.responses}
                durationMs={response.duration_ms}
              />
            ) : null}
          </MotionPresence>
        );
      })}
    </AnimatePresence>
  );
}

export function ConversationView({
  layout,
  turns,
  liveTurn,
  context,
  papers,
  projects,
  reasoningLevel,
  loading,
  error,
  onContextChange,
  onReasoningLevelChange,
  onSubmit,
  onStop,
  onRetry,
  onRetryResponse,
  onSelectResponse,
  onEditMessage,
  onSelectBranch,
  onUseSuggestion,
  canSend,
  submissionPending = false,
  readOnlyReason,
  composerForm,
  showComposer = true,
  contextLocked = false,
  contextLabel,
  turnContextLabel,
  onTurnContextClear,
  onDocumentSourceOpen,
  emptyState,
}: {
  layout: ConversationViewLayout;
  turns: ConversationTurn[];
  liveTurn: LiveTurn | null;
  context: ResearchContext;
  papers: LibraryPaper[];
  projects: Project[];
  reasoningLevel: ReasoningLevel;
  loading?: boolean;
  error?: boolean;
  onContextChange: (context: ResearchContext) => void;
  onReasoningLevelChange: (level: ReasoningLevel) => void;
  onSubmit: (message: string) => Promise<void>;
  onStop: () => void;
  onRetry: () => void;
  onRetryResponse: (turn: RetryableConversationTurn) => void;
  onSelectResponse: (turnId: string, responseId: string) => void;
  onEditMessage: (turn: ConversationTurn, message: string) => Promise<void>;
  onSelectBranch: (turnId: string) => void;
  onUseSuggestion: (suggestion: string) => void;
  canSend: boolean;
  submissionPending?: boolean;
  readOnlyReason?: string | null;
  composerForm?: UseFormReturn<ComposerValues>;
  showComposer?: boolean;
  contextLocked?: boolean;
  contextLabel?: string;
  turnContextLabel?: string;
  onTurnContextClear?: () => void;
  onDocumentSourceOpen?: (
    source: components["schemas"]["DocumentAnswerSource"],
  ) => void;
  emptyState?: ConversationEmptyState;
}) {
  const t = useTranslations("Home.conversation");
  const rootRef = React.useRef<HTMLDivElement>(null);
  const panelScrollRef = React.useRef<HTMLDivElement>(null);
  const visibleTurns = React.useMemo(() => {
    if (!liveTurn || liveTurn.generationKind === "retry") return turns;
    return turns.filter(
      (turn) => turn.depth < liveTurn.depth || turn.id === liveTurn.turnId,
    );
  }, [liveTurn, turns]);
  const liveResponse = liveTurn?.readyTurn?.responses.find(
    (response) => response.id === liveTurn.responseId,
  );
  const suppressLatestControls =
    submissionPending || liveTurn?.state === "streaming";
  const liveTurnRenderedInHistory = visibleTurns.some(
    (turn) => turn.id === liveTurn?.turnId,
  );

  const getScroller = React.useCallback(
    (): HTMLElement | null =>
      layout === "side-panel"
        ? panelScrollRef.current
        : ((rootRef.current?.closest("[data-conversation-scroll-root]") ??
            rootRef.current?.closest("main") ??
            null) as HTMLElement | null),
    [layout],
  );
  const { contentRef, jumpToLatest, pauseFollowing, showJumpToLatest } =
    useConversationAutoScroll({ getScroller });

  return (
    <div
      className={
        layout === "side-panel"
          ? "relative flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden"
          : "mx-auto flex min-h-full w-full max-w-[var(--layout-conversation-lane)] min-w-0 flex-col px-4 min-[390px]:px-5 sm:px-8 lg:px-0"
      }
      ref={rootRef}
    >
      <div
        className={
          layout === "side-panel"
            ? "flex min-h-0 flex-1 flex-col overflow-x-hidden overflow-y-auto px-5 pt-3 pb-6"
            : "flex-1 pt-6 pb-10 lg:py-8"
        }
        data-conversation-scroll-root={
          layout === "side-panel" ? true : undefined
        }
        ref={layout === "side-panel" ? panelScrollRef : undefined}
        data-scrollbar-gutter={layout === "side-panel" ? "stable" : undefined}
      >
        <div
          className={
            layout === "side-panel" ? "flex min-h-full flex-col" : "min-h-full"
          }
          ref={contentRef}
        >
          {loading ? (
            <p className="text-muted py-12 text-center text-sm" role="status">
              {t("loading")}
            </p>
          ) : error ? (
            <div
              className="grid place-items-center py-12 text-center"
              role="alert"
            >
              <Icon glyph={WarningIcon} size={24} tone="secondary" />
              <p className="mt-3 text-sm font-medium">{t("error")}</p>
              <Button
                className="mt-4"
                onClick={onRetry}
                size="sm"
                variant="secondary"
              >
                {t("retry")}
              </Button>
            </div>
          ) : visibleTurns.length === 0 && !liveTurn ? (
            <div
              className={
                layout === "side-panel"
                  ? "m-auto max-w-[20rem] px-4 py-12 text-center"
                  : "py-12 text-center"
              }
            >
              {emptyState ? (
                <>
                  <p className="text-primary text-base font-medium">
                    {emptyState.title}
                  </p>
                  <p className="text-muted mt-2 text-sm leading-6">
                    {emptyState.description}
                  </p>
                </>
              ) : (
                <p className="text-muted text-sm">{t("empty")}</p>
              )}
            </div>
          ) : (
            <div
              className={
                layout === "side-panel" ? "grid gap-7" : "grid gap-9 lg:gap-8"
              }
            >
              <MessageHistory
                canSend={
                  canSend &&
                  !submissionPending &&
                  liveTurn?.state !== "streaming"
                }
                liveTurn={liveTurn}
                onRetryResponse={onRetryResponse}
                onEditMessage={onEditMessage}
                onSelectBranch={onSelectBranch}
                onSelectResponse={onSelectResponse}
                onUseSuggestion={onUseSuggestion}
                onDocumentSourceOpen={onDocumentSourceOpen}
                suppressLatestControls={suppressLatestControls}
                turns={visibleTurns}
              />
              {liveTurn &&
                liveTurn.generationKind !== "retry" &&
                !liveTurnRenderedInHistory && (
                  <m.div
                    animate="animate"
                    className="grid gap-9 lg:gap-8"
                    initial="initial"
                    key={liveTurn.turnId}
                    layout="position"
                    transition={motionTransitions.gentle}
                    variants={motionVariants.focal}
                  >
                    <ConversationUserMessage
                      branch={{ count: 1, index: 1 }}
                      canEdit={false}
                      message={liveTurn.userMessage}
                      onEdit={async () => undefined}
                      onSelectBranch={() => undefined}
                    />
                    <AssistantMessage
                      canRetry={
                        canSend &&
                        !submissionPending &&
                        (liveTurn.state === "ready" ||
                          liveTurn.state === "complete" ||
                          liveTurn.state === "error" ||
                          liveTurn.state === "cancelled")
                      }
                      canSwitch={
                        !submissionPending &&
                        Boolean(
                          liveTurn.readyTurn &&
                          liveTurn.readyTurn.responses.length > 1,
                        )
                      }
                      content={liveTurn.content}
                      entries={liveTurn.entries}
                      key={liveTurn.turnId}
                      onActivityOpenChange={(open) => {
                        if (open) pauseFollowing();
                      }}
                      onRetryResponse={() =>
                        onRetryResponse(
                          liveTurn.readyTurn ?? {
                            id: liveTurn.turnId,
                            user_query: liveTurn.userMessage,
                            depth: liveTurn.depth,
                          },
                        )
                      }
                      onSelectResponse={(responseId) =>
                        onSelectResponse(liveTurn.turnId, responseId)
                      }
                      onUseSuggestion={
                        submissionPending ? undefined : onUseSuggestion
                      }
                      onDocumentSourceOpen={onDocumentSourceOpen}
                      provisionalItems={liveTurn.provisionalItems}
                      references={liveTurn.references}
                      response={liveResponse}
                      sourceTotal={
                        liveTurn.trace?.citation_summary?.source_count ??
                        referenceSourceCount(liveTurn.references)
                      }
                      state={liveTurn.state}
                      suggestions={liveTurn.suggestions}
                      variants={liveTurn.readyTurn?.responses}
                      failure={liveTurn.failure}
                      durationMs={liveTurn.durationMs}
                      startedAtMs={liveTurn.startedAtMs}
                    />
                  </m.div>
                )}
            </div>
          )}
        </div>
      </div>
      {showJumpToLatest && layout === "side-panel" && (
        <div className="pointer-events-none relative z-30 h-0 shrink-0">
          <div className="absolute right-0 bottom-3 left-0 flex justify-center">
            <IconButton
              className="bg-elevated shadow-raised pointer-events-auto size-12 rounded-full"
              label={t("jumpToLatest")}
              onClick={jumpToLatest}
              variant="secondary"
            >
              <Icon glyph={ExpandIcon} size={20} />
            </IconButton>
          </div>
        </div>
      )}
      {showJumpToLatest && layout !== "side-panel" && (
        <div className="pointer-events-none sticky bottom-3 z-10 -mt-15 hidden h-15 justify-center max-lg:flex">
          <IconButton
            className="bg-elevated shadow-raised pointer-events-auto size-12 rounded-full"
            label={t("jumpToLatest")}
            onClick={jumpToLatest}
            variant="secondary"
          >
            <Icon glyph={ExpandIcon} size={20} />
          </IconButton>
        </div>
      )}
      {!loading && !error && !canSend && (
        <div
          className="border-line bg-subtle mx-4 mb-3 rounded-[var(--radius-md)] border px-3 py-2 text-center text-xs"
          role="status"
        >
          {readOnlyReason ? t("readOnlyReason") : t("readOnly")}
        </div>
      )}
      {showComposer && (
        <div
          className={
            layout === "side-panel"
              ? "bg-canvas z-20 shrink-0 px-5 pt-2 pb-4"
              : "pointer-events-none sticky bottom-0 z-20 -mx-4 flex justify-center bg-[linear-gradient(to_top,var(--color-bg-canvas)_78%,transparent)] px-4 pt-5 pb-3 min-[390px]:-mx-5 min-[390px]:px-5 sm:-mx-8 lg:mx-0 lg:px-0 lg:pt-10 lg:pb-6"
          }
        >
          <div
            className={
              layout === "side-panel" ? "w-full" : "pointer-events-auto w-full"
            }
          >
            <ResearchComposer
              busy={submissionPending || liveTurn?.state === "streaming"}
              context={context}
              form={composerForm}
              onContextChange={onContextChange}
              onReasoningLevelChange={onReasoningLevelChange}
              onStop={onStop}
              onSubmit={onSubmit}
              papers={papers}
              projects={projects}
              reasoningLevel={reasoningLevel}
              unavailable={loading || error || !canSend}
              contextLocked={contextLocked}
              contextLabel={contextLabel}
              intent="follow-up"
              onTurnContextClear={onTurnContextClear}
              surface={layout === "side-panel" ? "context-panel" : "workspace"}
              turnContextLabel={turnContextLabel}
            />
          </div>
        </div>
      )}
    </div>
  );
}
