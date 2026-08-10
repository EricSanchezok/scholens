"use client";

import {
  Copy,
  NavArrowDown,
  NavArrowLeft,
  NavArrowRight,
  Refresh,
  WarningTriangle,
} from "iconoir-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import {
  Button,
  IconButton,
  Skeleton,
  keyboardFocusRing,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import type {
  ConversationFailure,
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
import {
  ConversationSources,
  isReferenceBundle,
  referenceSourceCount,
} from "./conversation-sources";

export type ConversationTurn =
  components["schemas"]["ConversationTurnResponse"];
export type ConversationResponseVariant =
  components["schemas"]["ConversationResponseVariantResponse"];
type LibraryPaper = components["schemas"]["LibraryPaperResponse"];
type Project = components["schemas"]["ProjectResponse"];

function FollowUpSuggestions({
  response,
  onUseSuggestion,
}: {
  response: ConversationResponseVariant;
  onUseSuggestion: (suggestion: string) => void;
}) {
  const t = useTranslations("Home.conversation");

  if (response.suggestions_status === "pending") {
    return (
      <section
        aria-label={t("suggestionsPreparing")}
        className="lg:border-line-subtle grid justify-items-start gap-2 pt-3 lg:max-w-2xl lg:justify-items-stretch lg:gap-0 lg:border-t lg:pt-2"
        role="status"
      >
        <Skeleton className="h-11 w-3/4 rounded-full lg:h-10 lg:w-full lg:rounded-none" />
        <Skeleton className="h-11 w-[88%] rounded-full lg:h-10 lg:w-full lg:rounded-none" />
        <Skeleton className="h-11 w-2/3 rounded-full lg:h-10 lg:w-full lg:rounded-none" />
      </section>
    );
  }

  if (response.suggestions_status === "failed") {
    return (
      <p className="text-muted pt-2 text-xs" role="status">
        {t("suggestionsUnavailable")}
      </p>
    );
  }

  if (
    response.suggestions_status !== "completed" ||
    response.suggestions?.length !== 3
  ) {
    return null;
  }

  return (
    <section
      aria-label={t("suggestions")}
      className="lg:border-line-subtle grid justify-items-start gap-2 pt-3 lg:max-w-2xl lg:justify-items-stretch lg:gap-0 lg:border-t lg:pt-2"
    >
      {response.suggestions.map((suggestion) => (
        <button
          className={`bg-subtle hover:bg-hover active:bg-pressed lg:border-line-subtle min-h-11 max-w-full rounded-full px-4 py-2 text-left text-sm leading-5 transition-colors lg:min-h-10 lg:w-full lg:rounded-none lg:border-b lg:bg-transparent lg:px-1 lg:py-2.5 ${keyboardFocusRing}`}
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
  provisionalContent,
  references,
  sourceTotal,
  state,
  failure,
  historical,
  onActivityOpenChange,
  response,
  variants,
  canRetry,
  canSwitch,
  onRetryResponse,
  onSelectResponse,
  onUseSuggestion,
}: {
  entries: ConversationTraceEntry[];
  content: string;
  provisionalContent?: string;
  references: unknown;
  sourceTotal: number;
  state: LiveTurn["state"];
  failure?: ConversationFailure | null;
  historical?: boolean;
  onActivityOpenChange?: (open: boolean) => void;
  response?: ConversationResponseVariant;
  variants?: ConversationResponseVariant[];
  canRetry?: boolean;
  canSwitch?: boolean;
  onRetryResponse?: () => void;
  onSelectResponse?: (responseId: string) => void;
  onUseSuggestion?: (suggestion: string) => void;
}) {
  const t = useTranslations("Home.conversation");
  const [copied, setCopied] = React.useState(false);
  const [sourcesOpen, setSourcesOpen] = React.useState(false);
  const [selectedSourceKey, setSelectedSourceKey] = React.useState<
    number | undefined
  >();
  const visibleContent = content || provisionalContent || "";
  const presentationState =
    content && state === "streaming" ? "complete" : state;
  const orderedVariants = canSwitch
    ? [...(variants ?? [])].sort(
        (left, right) => left.variant_index - right.variant_index,
      )
    : [];
  const selectedVariantIndex = orderedVariants.findIndex(
    (candidate) => candidate.id === response?.id,
  );
  return (
    <article aria-label={t("assistantMessage")} className="grid gap-3">
      <ConversationWorklog
        entries={entries}
        failure={failure ?? null}
        historical={historical}
        onOpenChange={onActivityOpenChange}
        provisionalVisible={Boolean(provisionalContent)}
        sourceTotal={sourceTotal}
        state={presentationState}
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
      {response?.status === "completed" && visibleContent && (
        <div
          className="flex min-h-11 flex-wrap items-center gap-0 pt-1 lg:min-h-8"
          role="group"
          aria-label={t("answerActions")}
        >
          {canSwitch && orderedVariants.length > 1 && onSelectResponse && (
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
                <Icon glyph={NavArrowLeft} size={20} tone="secondary" />
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
                disabled={selectedVariantIndex >= orderedVariants.length - 1}
                label={t("nextResponse")}
                onClick={() =>
                  onSelectResponse(
                    orderedVariants[selectedVariantIndex + 1]!.id,
                  )
                }
                variant="ghost"
              >
                <Icon glyph={NavArrowRight} size={20} tone="secondary" />
              </IconButton>
            </div>
          )}
          <IconButton
            className="size-11 bg-transparent lg:size-8 lg:min-h-8"
            label={copied ? t("copied") : t("copy")}
            onClick={() => {
              void (async () => {
                try {
                  await navigator.clipboard.writeText(visibleContent);
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 1500);
                } catch {
                  // Clipboard access may be denied outside a secure context.
                }
              })();
            }}
            variant="ghost"
          >
            <Icon glyph={Copy} size={20} tone="secondary" />
          </IconButton>
          {canRetry && onRetryResponse && (
            <IconButton
              className="size-11 bg-transparent lg:size-8 lg:min-h-8"
              label={t("regenerate")}
              onClick={onRetryResponse}
              variant="ghost"
            >
              <Icon glyph={Refresh} size={16} tone="secondary" />
            </IconButton>
          )}
          <ConversationSources
            onOpenChange={(open) => {
              setSourcesOpen(open);
              if (!open) setSelectedSourceKey(undefined);
            }}
            open={sourcesOpen}
            references={references}
            selectedSourceKey={selectedSourceKey}
          />
          <span className="sr-only" aria-live="polite">
            {copied ? t("copied") : ""}
          </span>
        </div>
      )}
      {response && onUseSuggestion && (
        <FollowUpSuggestions
          onUseSuggestion={onUseSuggestion}
          response={response}
        />
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
  onRetryResponse,
  onSelectResponse,
  onUseSuggestion,
}: {
  turns: ConversationTurn[];
  liveTurn: LiveTurn | null;
  canSend: boolean;
  onRetryResponse: (turn: ConversationTurn) => void;
  onSelectResponse: (turnId: string, responseId: string) => void;
  onUseSuggestion: (suggestion: string) => void;
}) {
  const latestTurnId = turns.at(-1)?.id;
  return (
    <>
      {turns.map((turn) => {
        const response = selectedResponse(turn);
        const isLive = liveTurn?.turnId === turn.id;
        return (
          <React.Fragment key={turn.id}>
            <div className="flex justify-end">
              <p className="bg-subtle max-w-[86%] rounded-[var(--radius-xl)] px-4 py-3 text-base leading-6 lg:max-w-[80%] lg:rounded-[var(--radius-lg)] lg:text-sm">
                {turn.user_query}
              </p>
            </div>
            {isLive && liveTurn ? (
              <AssistantMessage
                content={liveTurn.content}
                entries={liveTurn.entries}
                failure={liveTurn.failure}
                provisionalContent={liveTurn.provisionalItems
                  .map((item) => item.content)
                  .join("")}
                references={liveTurn.references}
                sourceTotal={
                  liveTurn.trace?.citation_summary?.source_count ??
                  referenceSourceCount(liveTurn.references)
                }
                state={liveTurn.state}
              />
            ) : response ? (
              <AssistantMessage
                canRetry={turn.id === latestTurnId && canSend}
                canSwitch={turn.id === latestTurnId}
                content={response.content ?? ""}
                entries={response.trace?.entries ?? []}
                historical
                onRetryResponse={() => onRetryResponse(turn)}
                onSelectResponse={(responseId) =>
                  onSelectResponse(turn.id, responseId)
                }
                onUseSuggestion={
                  turn.id === latestTurnId ? onUseSuggestion : undefined
                }
                references={response.references}
                response={response}
                sourceTotal={
                  response.trace?.citation_summary?.source_count ??
                  referenceSourceCount(response.references)
                }
                state="complete"
                failure={null}
                variants={turn.responses}
              />
            ) : null}
          </React.Fragment>
        );
      })}
    </>
  );
}

export function ConversationView({
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
  onUseSuggestion,
  canSend,
  readOnlyReason,
  composerForm,
  showComposer = true,
}: {
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
  onRetryResponse: (turn: ConversationTurn) => void;
  onSelectResponse: (turnId: string, responseId: string) => void;
  onUseSuggestion: (suggestion: string) => void;
  canSend: boolean;
  readOnlyReason?: string | null;
  composerForm?: UseFormReturn<ComposerValues>;
  showComposer?: boolean;
}) {
  const t = useTranslations("Home.conversation");
  const rootRef = React.useRef<HTMLDivElement>(null);
  const scrollAnchor = React.useRef<HTMLDivElement>(null);
  const nearBottom = React.useRef(true);
  const [showJumpToLatest, setShowJumpToLatest] = React.useState(false);
  const visibleTurns = React.useMemo(
    () =>
      liveTurn?.generationKind === "initial"
        ? turns.filter((turn) => turn.id !== liveTurn.turnId)
        : turns,
    [liveTurn, turns],
  );
  const worklogSignature = liveTurn?.entries
    .map((entry) =>
      entry.kind === "activity"
        ? `${entry.id}:${entry.state}`
        : `${entry.id}:${entry.content.length}`,
    )
    .join("|");
  const provisionalContent = liveTurn?.provisionalItems
    .map((item) => item.content)
    .join("");

  React.useEffect(() => {
    const scrollRoot = rootRef.current?.closest("main");
    if (!scrollRoot) return;
    const scroller = scrollRoot;
    function updateProximity() {
      const gap =
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      const nextNearBottom = gap < 120;
      nearBottom.current = nextNearBottom;
      setShowJumpToLatest(
        scroller.scrollHeight > scroller.clientHeight + 32 && !nextNearBottom,
      );
    }
    const initialFrame = window.requestAnimationFrame(updateProximity);
    scroller.addEventListener("scroll", updateProximity, { passive: true });
    return () => {
      window.cancelAnimationFrame(initialFrame);
      scroller.removeEventListener("scroll", updateProximity);
    };
  }, []);

  React.useEffect(() => {
    if (!nearBottom.current) {
      setShowJumpToLatest(true);
      return;
    }
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    scrollAnchor.current?.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "end",
    });
  }, [
    worklogSignature,
    liveTurn?.content,
    provisionalContent,
    visibleTurns.length,
  ]);

  function jumpToLatest() {
    nearBottom.current = true;
    setShowJumpToLatest(false);
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    scrollAnchor.current?.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "end",
    });
  }

  return (
    <div
      className="mx-auto flex min-h-full w-full max-w-[848px] min-w-0 flex-col px-4 min-[390px]:px-5 sm:px-8"
      ref={rootRef}
    >
      <div className="flex-1 pt-6 pb-10 lg:py-8 lg:pb-40">
        {loading ? (
          <p className="text-muted py-12 text-center text-sm" role="status">
            {t("loading")}
          </p>
        ) : error ? (
          <div
            className="grid place-items-center py-12 text-center"
            role="alert"
          >
            <Icon glyph={WarningTriangle} size={24} tone="secondary" />
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
          <p className="text-muted py-12 text-center text-sm">{t("empty")}</p>
        ) : (
          <div className="grid gap-9 lg:gap-8">
            <MessageHistory
              canSend={canSend && liveTurn?.state !== "streaming"}
              liveTurn={liveTurn}
              onRetryResponse={onRetryResponse}
              onSelectResponse={onSelectResponse}
              onUseSuggestion={onUseSuggestion}
              turns={visibleTurns}
            />
            {liveTurn?.generationKind === "initial" && (
              <>
                <div className="flex justify-end">
                  <p className="bg-subtle max-w-[86%] rounded-[var(--radius-xl)] px-4 py-3 text-base leading-6 lg:max-w-[80%] lg:rounded-[var(--radius-lg)] lg:text-sm">
                    {liveTurn.userMessage}
                  </p>
                </div>
                <AssistantMessage
                  content={liveTurn.content}
                  entries={liveTurn.entries}
                  key={liveTurn.turnId}
                  onActivityOpenChange={(open) => {
                    if (open) nearBottom.current = false;
                  }}
                  provisionalContent={provisionalContent}
                  references={liveTurn.references}
                  sourceTotal={
                    liveTurn.trace?.citation_summary?.source_count ??
                    referenceSourceCount(liveTurn.references)
                  }
                  state={liveTurn.state}
                  failure={liveTurn.failure}
                />
              </>
            )}
            <div ref={scrollAnchor} />
          </div>
        )}
      </div>
      {showJumpToLatest && (
        <div className="pointer-events-none sticky bottom-3 z-10 -mt-15 hidden h-15 justify-center max-lg:flex">
          <IconButton
            className="bg-elevated shadow-raised pointer-events-auto size-12 rounded-full"
            label={t("jumpToLatest")}
            onClick={jumpToLatest}
            variant="secondary"
          >
            <Icon glyph={NavArrowDown} size={20} />
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
        <div className="pointer-events-none sticky bottom-0 z-20 -mx-4 flex justify-center bg-[linear-gradient(to_top,var(--color-bg-canvas)_78%,transparent)] px-4 pt-5 pb-3 min-[390px]:-mx-5 min-[390px]:px-5 sm:-mx-8 lg:mx-0 lg:px-4 lg:pt-10 lg:pb-6">
          <div className="pointer-events-auto w-full max-w-[720px]">
            <ResearchComposer
              busy={liveTurn?.state === "streaming"}
              compact
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
            />
          </div>
        </div>
      )}
    </div>
  );
}
