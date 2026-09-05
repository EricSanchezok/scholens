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

import { Button, focusSurfaceVariants, IconButton } from "@/components/ui";
import { CopyActionButton } from "@/components/feedback";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import type {
  ConversationFailure,
  ConversationPhase,
  ProvisionalAssistantItem,
  ConversationTraceEntry,
  LiveTurn,
} from "../conversation-state";
import {
  conversationFailureFromValue,
  isActiveConversationPhase,
} from "../conversation-state";
import {
  ConversationLiveStore,
  type ConversationLiveMetadata,
} from "../conversation-live-store";
import type { ComposerValues } from "../schemas";
import type { UseFormReturn } from "react-hook-form";
import {
  ResearchComposer,
  type ReasoningLevel,
  type ResearchContext,
  type ResearchContextPaperOption,
  type ResearchContextProjectOption,
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

function LiveConversationWorklog({
  availableSourceTotal,
  historical,
  onOpenChange,
  sourceTotal,
  store,
}: {
  availableSourceTotal: number;
  historical?: boolean;
  onOpenChange?: (open: boolean) => void;
  sourceTotal: number;
  store: ConversationLiveStore;
}) {
  const snapshot = React.useSyncExternalStore(
    store.subscribeWorklog,
    store.getWorklogSnapshot,
    store.getWorklogSnapshot,
  );
  if (!snapshot) return null;
  return (
    <ConversationWorklog
      connectionState={snapshot.connectionState}
      durationMs={snapshot.durationMs}
      entries={snapshot.entries}
      failure={snapshot.failure}
      historical={historical}
      onOpenChange={onOpenChange}
      phase={snapshot.phase}
      provisionalItems={snapshot.provisionalItems}
      sourceTotal={sourceTotal}
      availableSourceTotal={availableSourceTotal}
      startedAtMs={snapshot.startedAtMs}
      stopFailure={snapshot.stopFailure}
    />
  );
}

function LiveMessageContent({
  onContentVisible,
  onCitationOpen,
  store,
}: {
  onContentVisible?: () => void;
  onCitationOpen: (sourceKeys: number[]) => void;
  store: ConversationLiveStore;
}) {
  const snapshot = React.useSyncExternalStore(
    store.subscribeContent,
    store.getContentSnapshot,
    store.getContentSnapshot,
  );
  const visibleContent = snapshot
    ? snapshot.content || snapshot.answerCandidate?.content || ""
    : "";
  React.useEffect(() => {
    if (!visibleContent || !onContentVisible) return;
    const frame = window.requestAnimationFrame(onContentVisible);
    return () => window.cancelAnimationFrame(frame);
  }, [onContentVisible, visibleContent]);
  if (!snapshot || !visibleContent) return null;
  return (
    <MessageContent
      annotations={
        isReferenceBundle(snapshot.references)
          ? snapshot.references.annotations
          : undefined
      }
      content={visibleContent}
      onCitationOpen={onCitationOpen}
      streaming={isActiveConversationPhase(snapshot.phase)}
    />
  );
}

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
          className={`motion-control bg-subtle hover:bg-hover active:bg-pressed lg:border-line-subtle lg:text-secondary lg:hover:text-foreground lg:focus-visible:text-foreground min-h-11 max-w-full rounded-full px-4 py-2 text-left text-sm leading-5 lg:-mx-3 lg:min-h-10 lg:w-auto lg:rounded-[var(--radius-sm)] lg:border-t lg:bg-transparent lg:px-3 lg:py-2.5 lg:first:border-t-0 ${focusSurfaceVariants({ intent: "neutral" })}`}
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
  answerCandidate,
  provisionalItems,
  references,
  citationSummary,
  sourceTotal,
  phase,
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
  connectionState,
  stopFailure,
  liveStore,
  onContentVisible,
}: {
  entries: ConversationTraceEntry[];
  content: string;
  answerCandidate?: ProvisionalAssistantItem | null;
  provisionalItems?: ProvisionalAssistantItem[];
  references: unknown;
  citationSummary?: components["schemas"]["ConversationCitationSummary"] | null;
  sourceTotal: number;
  phase: ConversationPhase;
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
  connectionState?: LiveTurn["connectionState"];
  stopFailure?: boolean;
  liveStore?: ConversationLiveStore;
  onContentVisible?: () => void;
}) {
  const t = useTranslations("Home.conversation");
  const [sourcesOpen, setSourcesOpen] = React.useState(false);
  const [selectedSourceKey, setSelectedSourceKey] = React.useState<
    number | undefined
  >();
  const visibleContent = content || answerCandidate?.content || "";
  const orderedVariants = canSwitch
    ? [...(variants ?? [])]
        .filter((candidate) => candidate.status === "completed")
        .sort((left, right) => left.variant_index - right.variant_index)
    : [];
  const selectedVariantIndex = orderedVariants.findIndex(
    (candidate) => candidate.id === response?.id,
  );
  const completedActionsVisible = Boolean(
    response?.status === "completed" && visibleContent && phase === "ready",
  );
  const terminalRetryVisible = Boolean(
    canRetry &&
    onRetryResponse &&
    (response?.status === "failed" ||
      response?.status === "cancelled" ||
      phase === "error" ||
      phase === "cancelled"),
  );
  React.useEffect(() => {
    if (liveStore || !visibleContent || !onContentVisible) return;
    const frame = window.requestAnimationFrame(onContentVisible);
    return () => window.cancelAnimationFrame(frame);
  }, [liveStore, onContentVisible, visibleContent]);
  return (
    <article
      aria-label={t("assistantMessage")}
      aria-busy={isActiveConversationPhase(phase)}
      className="grid min-w-0 gap-2 lg:gap-3"
    >
      {liveStore ? (
        <LiveConversationWorklog
          availableSourceTotal={
            citationSummary?.available_source_count ?? sourceTotal
          }
          historical={historical}
          onOpenChange={onActivityOpenChange}
          sourceTotal={sourceTotal}
          store={liveStore}
        />
      ) : (
        <ConversationWorklog
          availableSourceTotal={
            citationSummary?.available_source_count ?? sourceTotal
          }
          entries={entries}
          failure={failure ?? null}
          historical={historical}
          onOpenChange={onActivityOpenChange}
          provisionalItems={provisionalItems ?? []}
          sourceTotal={sourceTotal}
          phase={phase}
          durationMs={durationMs}
          startedAtMs={startedAtMs}
          connectionState={connectionState}
          stopFailure={stopFailure}
        />
      )}
      {liveStore ? (
        <LiveMessageContent
          onContentVisible={onContentVisible}
          onCitationOpen={(sourceKeys) => {
            setSelectedSourceKey(sourceKeys[0]);
            setSourcesOpen(true);
          }}
          store={liveStore}
        />
      ) : visibleContent ? (
        <MessageContent
          annotations={
            isReferenceBundle(references) ? references.annotations : undefined
          }
          content={visibleContent}
          onCitationOpen={(sourceKeys) => {
            setSelectedSourceKey(sourceKeys[0]);
            setSourcesOpen(true);
          }}
          streaming={false}
        />
      ) : null}
      {(completedActionsVisible || terminalRetryVisible || suggestions) && (
        <footer className="grid gap-2 lg:gap-1">
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
              {completedActionsVisible && (
                <ConversationSources
                  citationSummary={citationSummary}
                  onDocumentOpen={onDocumentSourceOpen}
                  onOpenChange={(open) => {
                    setSourcesOpen(open);
                    if (!open) setSelectedSourceKey(undefined);
                  }}
                  open={sourcesOpen}
                  references={references}
                  selectedSourceKey={selectedSourceKey}
                />
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

const HistoricalTurnRow = React.memo(function HistoricalTurnRow({
  canSend,
  latestControlsVisible,
  onDocumentSourceOpen,
  onEditMessage,
  onRetryResponse,
  onSelectBranch,
  onSelectResponse,
  onUseSuggestion,
  onContentVisible,
  turn,
}: {
  canSend: boolean;
  latestControlsVisible: boolean;
  onDocumentSourceOpen?: (
    source: components["schemas"]["DocumentAnswerSource"],
  ) => void;
  onEditMessage: (turn: ConversationTurn, message: string) => Promise<void>;
  onRetryResponse: (turn: RetryableConversationTurn) => void;
  onSelectBranch: (turnId: string) => void;
  onSelectResponse: (turnId: string, responseId: string) => void;
  onUseSuggestion: (suggestion: string) => void;
  onContentVisible?: (responseId: string) => void;
  turn: ConversationTurn;
}) {
  const response = selectedResponse(turn);
  return (
    <div className="settled-content-enter grid gap-9 [contain-intrinsic-size:auto_20rem] [content-visibility:auto] lg:gap-8">
      <ConversationUserMessage
        branch={turn.branch}
        canEdit={canSend}
        message={turn.user_query}
        onEdit={(message) => onEditMessage(turn, message)}
        onSelectBranch={onSelectBranch}
      />
      {response ? (
        <AssistantMessage
          canRetry={latestControlsVisible && canSend}
          canSwitch={latestControlsVisible}
          content={response.content ?? ""}
          durationMs={response.duration_ms}
          entries={response.trace?.entries ?? []}
          failure={
            response.failure
              ? conversationFailureFromValue(response.failure)
              : null
          }
          historical
          onDocumentSourceOpen={onDocumentSourceOpen}
          onContentVisible={() => onContentVisible?.(response.id)}
          onRetryResponse={() => onRetryResponse(turn)}
          onSelectResponse={(responseId) =>
            onSelectResponse(turn.id, responseId)
          }
          onUseSuggestion={latestControlsVisible ? onUseSuggestion : undefined}
          phase={
            response.status === "cancelled"
              ? "cancelled"
              : response.status === "failed"
                ? "error"
                : response.status === "running"
                  ? "working"
                  : "ready"
          }
          references={response.references}
          citationSummary={response.trace?.citation_summary}
          response={response}
          sourceTotal={
            response.trace?.citation_summary?.source_count ??
            referenceSourceCount(response.references)
          }
          suggestions={turn.suggestions}
          variants={turn.responses}
        />
      ) : null}
    </div>
  );
});

function MessageHistory({
  turns,
  liveTurn,
  liveStore,
  canSend,
  suppressLatestControls,
  onRetryResponse,
  onSelectResponse,
  onEditMessage,
  onSelectBranch,
  onUseSuggestion,
  onLiveContentVisible,
  onDocumentSourceOpen,
}: {
  turns: ConversationTurn[];
  liveTurn: ConversationLiveMetadata | null;
  liveStore: ConversationLiveStore;
  canSend: boolean;
  suppressLatestControls: boolean;
  onRetryResponse: (turn: RetryableConversationTurn) => void;
  onSelectResponse: (turnId: string, responseId: string) => void;
  onEditMessage: (turn: ConversationTurn, message: string) => Promise<void>;
  onSelectBranch: (turnId: string) => void;
  onUseSuggestion: (suggestion: string) => void;
  onLiveContentVisible?: (responseId: string) => void;
  onDocumentSourceOpen?: (
    source: components["schemas"]["DocumentAnswerSource"],
  ) => void;
}) {
  const latestTurnId = turns.at(-1)?.id;
  return (
    <>
      {turns.map((turn) => {
        const isLive = liveTurn?.turnId === turn.id;
        const latestControlsVisible =
          turn.id === latestTurnId && !suppressLatestControls;
        if (!isLive || !liveTurn) {
          return (
            <HistoricalTurnRow
              canSend={canSend}
              key={turn.id}
              latestControlsVisible={latestControlsVisible}
              onDocumentSourceOpen={onDocumentSourceOpen}
              onEditMessage={onEditMessage}
              onRetryResponse={onRetryResponse}
              onSelectBranch={onSelectBranch}
              onSelectResponse={onSelectResponse}
              onUseSuggestion={onUseSuggestion}
              onContentVisible={onLiveContentVisible}
              turn={turn}
            />
          );
        }
        const readyTurn = isLive ? liveTurn?.readyTurn : null;
        const liveResponse = readyTurn
          ? readyTurn.responses.find(
              (candidate) => candidate.id === liveTurn?.responseId,
            )
          : undefined;
        return (
          <div
            className="settled-content-enter grid gap-9 [contain-intrinsic-size:auto_20rem] [content-visibility:auto] lg:gap-8"
            key={turn.id}
          >
            <ConversationUserMessage
              branch={turn.branch}
              canEdit={canSend}
              message={turn.user_query}
              onEdit={(message) => onEditMessage(turn, message)}
              onSelectBranch={onSelectBranch}
            />
            <AssistantMessage
              canRetry={
                latestControlsVisible &&
                canSend &&
                (liveTurn.phase === "ready" ||
                  liveTurn.phase === "error" ||
                  liveTurn.phase === "cancelled")
              }
              canSwitch={
                latestControlsVisible &&
                Boolean(readyTurn && readyTurn.responses.length > 1)
              }
              content={liveResponse?.content ?? ""}
              entries={liveResponse?.trace?.entries ?? []}
              failure={liveTurn.failure}
              liveStore={liveStore}
              onRetryResponse={() => onRetryResponse(readyTurn ?? turn)}
              onSelectResponse={(responseId) =>
                onSelectResponse(turn.id, responseId)
              }
              onUseSuggestion={
                latestControlsVisible ? onUseSuggestion : undefined
              }
              onDocumentSourceOpen={onDocumentSourceOpen}
              onContentVisible={() =>
                onLiveContentVisible?.(liveTurn.responseId)
              }
              references={liveTurn.references}
              citationSummary={liveTurn.citationSummary}
              response={liveResponse}
              sourceTotal={
                liveTurn.trace?.citation_summary?.source_count ??
                referenceSourceCount(liveTurn.references)
              }
              phase={liveTurn.phase}
              suggestions={liveTurn.suggestions}
              variants={readyTurn?.responses}
              durationMs={liveTurn.durationMs}
              startedAtMs={liveTurn.startedAtMs}
              connectionState={liveTurn.connectionState}
              stopFailure={liveTurn.stopFailure}
            />
          </div>
        );
      })}
    </>
  );
}

export function ConversationView({
  layout,
  turns,
  liveTurn: liveTurnSource,
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
  onLiveContentVisible,
  canSend,
  completionAnnouncementId,
  submissionPending = false,
  stopAvailable,
  readOnlyReason,
  composerForm,
  showComposer = true,
  turnContextLabel,
  onTurnContextClear,
  onDocumentSourceOpen,
  emptyState,
}: {
  layout: ConversationViewLayout;
  turns: ConversationTurn[];
  liveTurn: ConversationLiveStore;
  context: ResearchContext;
  papers: ResearchContextPaperOption[];
  projects: ResearchContextProjectOption[];
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
  onLiveContentVisible?: (responseId: string) => void;
  canSend: boolean;
  completionAnnouncementId?: string;
  submissionPending?: boolean;
  stopAvailable: boolean;
  readOnlyReason?: string | null;
  composerForm?: UseFormReturn<ComposerValues>;
  showComposer?: boolean;
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
  const liveStore = liveTurnSource;
  const liveTurn = React.useSyncExternalStore(
    liveStore.subscribeMetadata,
    liveStore.getMetadataSnapshot,
    liveStore.getMetadataSnapshot,
  );
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
    submissionPending ||
    (liveTurn ? isActiveConversationPhase(liveTurn.phase) : false);
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
          : "mx-auto flex min-h-full w-full max-w-[var(--layout-conversation-lane)] min-w-0 flex-col overflow-x-clip px-4 min-[390px]:px-5 sm:px-8 lg:px-0"
      }
      ref={rootRef}
    >
      {completionAnnouncementId ? (
        <span
          aria-atomic="true"
          aria-live="polite"
          className="sr-only"
          key={completionAnnouncementId}
          role="status"
        >
          {t("completed")}
        </span>
      ) : null}
      <div
        className={
          layout === "side-panel"
            ? `flex min-h-0 flex-1 flex-col overflow-x-hidden overflow-y-auto px-5 pt-3 pb-6 ${focusSurfaceVariants({ intent: "scroll" })}`
            : "flex-1 pt-6 pb-10 lg:py-8"
        }
        data-conversation-scroll-root={
          layout === "side-panel" ? true : undefined
        }
        ref={layout === "side-panel" ? panelScrollRef : undefined}
        data-scrollbar-gutter={layout === "side-panel" ? "stable" : undefined}
        tabIndex={layout === "side-panel" ? 0 : undefined}
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
                  !(liveTurn && isActiveConversationPhase(liveTurn.phase))
                }
                liveTurn={liveTurn}
                liveStore={liveStore}
                onRetryResponse={onRetryResponse}
                onEditMessage={onEditMessage}
                onSelectBranch={onSelectBranch}
                onSelectResponse={onSelectResponse}
                onUseSuggestion={onUseSuggestion}
                onLiveContentVisible={onLiveContentVisible}
                onDocumentSourceOpen={onDocumentSourceOpen}
                suppressLatestControls={suppressLatestControls}
                turns={visibleTurns}
              />
              {liveTurn &&
                liveTurn.generationKind !== "retry" &&
                !liveTurnRenderedInHistory && (
                  <div
                    className="settled-content-enter grid gap-9 lg:gap-8"
                    key={liveTurn.turnId}
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
                        (liveTurn.phase === "ready" ||
                          liveTurn.phase === "error" ||
                          liveTurn.phase === "cancelled")
                      }
                      canSwitch={
                        !submissionPending &&
                        Boolean(
                          liveTurn.readyTurn &&
                          liveTurn.readyTurn.responses.length > 1,
                        )
                      }
                      content={liveResponse?.content ?? ""}
                      entries={liveResponse?.trace?.entries ?? []}
                      key={liveTurn.turnId}
                      liveStore={liveStore}
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
                      onContentVisible={() =>
                        onLiveContentVisible?.(liveTurn.responseId)
                      }
                      references={liveTurn.references}
                      citationSummary={liveTurn.citationSummary}
                      response={liveResponse}
                      sourceTotal={
                        liveTurn.trace?.citation_summary?.source_count ??
                        referenceSourceCount(liveTurn.references)
                      }
                      phase={liveTurn.phase}
                      suggestions={liveTurn.suggestions}
                      variants={liveTurn.readyTurn?.responses}
                      failure={liveTurn.failure}
                      durationMs={liveTurn.durationMs}
                      startedAtMs={liveTurn.startedAtMs}
                      connectionState={liveTurn.connectionState}
                      stopFailure={liveTurn.stopFailure}
                    />
                  </div>
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
              busy={
                submissionPending ||
                Boolean(liveTurn && isActiveConversationPhase(liveTurn.phase))
              }
              context={context}
              form={composerForm}
              onContextChange={onContextChange}
              onReasoningLevelChange={onReasoningLevelChange}
              onStop={onStop}
              stopAvailable={stopAvailable}
              onSubmit={onSubmit}
              papers={papers}
              projects={projects}
              reasoningLevel={reasoningLevel}
              unavailable={loading || error || !canSend}
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
