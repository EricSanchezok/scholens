"use client";

import { Page } from "iconoir-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHandle,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  keyboardFocusRing,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";

export type ReferenceBundle = components["schemas"]["ReferenceBundle"];
type AnswerSource = NonNullable<ReferenceBundle["sources"]>[number];

export function isReferenceBundle(value: unknown): value is ReferenceBundle {
  return Boolean(
    value &&
    typeof value === "object" &&
    Array.isArray((value as { sources?: unknown }).sources),
  );
}

export function referenceSourceCount(references: unknown) {
  return isReferenceBundle(references) ? (references.sources?.length ?? 0) : 0;
}

function sourceTitle(source: AnswerSource, fallback: string): string {
  return "title" in source && source.title ? source.title : fallback;
}

function sourceMeta(source: AnswerSource) {
  if (source.kind === "external") {
    try {
      return new URL(source.url).hostname.replace(/^www\./, "");
    } catch {
      return source.url;
    }
  }
  if (source.kind === "document" && source.authors?.length) {
    return source.authors.slice(0, 3).join(", ");
  }
  return null;
}

function SourceRow({
  source,
  selected,
  fallbackTitle,
  onDocumentOpen,
}: {
  source: AnswerSource;
  selected: boolean;
  fallbackTitle: string;
  onDocumentOpen?: (
    source: components["schemas"]["DocumentAnswerSource"],
  ) => void;
}) {
  const t = useTranslations("Home.conversation");
  const meta = sourceMeta(source);
  const content = (
    <>
      <span className="bg-subtle grid size-8 shrink-0 place-items-center rounded-full text-xs font-medium">
        {source.key}
      </span>
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 block text-sm font-medium">
          {sourceTitle(source, fallbackTitle)}
        </span>
        {meta && (
          <span className="text-caption text-muted mt-0.5 block truncate">
            {meta}
          </span>
        )}
        <span className="text-muted mt-1 line-clamp-2 block text-sm leading-5">
          {source.reference}
        </span>
      </span>
    </>
  );
  const className = cn(
    "border-line hover:bg-hover flex min-h-20 w-full items-start gap-3 border-b px-5 py-4 text-left transition-colors last:border-b-0 lg:px-6",
    source.kind === "external" && keyboardFocusRing,
    selected && "bg-subtle",
  );

  if (source.kind === "external") {
    return (
      <a
        aria-label={t("openSource", {
          title: sourceTitle(source, fallbackTitle),
        })}
        className={className}
        href={source.url}
        rel="noreferrer"
        target="_blank"
      >
        {content}
      </a>
    );
  }
  if (source.kind === "document" && onDocumentOpen) {
    return (
      <button
        className={cn(className, keyboardFocusRing)}
        onClick={() => onDocumentOpen(source)}
        type="button"
      >
        {content}
      </button>
    );
  }
  return <div className={className}>{content}</div>;
}

export function ConversationSources({
  references,
  open,
  onOpenChange,
  selectedSourceKey,
  onDocumentOpen,
}: {
  references: unknown;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selectedSourceKey?: number;
  onDocumentOpen?: (
    source: components["schemas"]["DocumentAnswerSource"],
  ) => void;
}) {
  const t = useTranslations("Home.conversation");
  if (!isReferenceBundle(references) || !references.sources?.length) {
    return null;
  }
  const sources = references.sources;

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogTrigger asChild>
        <button
          className={cn(
            "bg-subtle hover:bg-hover active:bg-pressed ml-auto flex min-h-11 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-colors lg:min-h-8",
            keyboardFocusRing,
          )}
          type="button"
        >
          <Icon glyph={Page} size={16} tone="secondary" />
          {t("sourceSummary", { count: sources.length })}
        </button>
      </DialogTrigger>
      <DialogContent
        aria-describedby="conversation-sources-description"
        closeLabel={t("closeSources")}
        placement="responsive-bottom"
      >
        <DialogHandle />
        <DialogHeader>
          <DialogTitle>
            {t("sourcePanelTitle", { count: sources.length })}
          </DialogTitle>
          <DialogDescription id="conversation-sources-description">
            {t("sourcePanelDescription")}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="p-0 lg:p-0">
          {sources.map((source, index) => (
            <SourceRow
              fallbackTitle={t("reference", { number: index + 1 })}
              key={`${source.kind}-${source.key}`}
              onDocumentOpen={
                onDocumentOpen
                  ? (documentSource) => {
                      onOpenChange(false);
                      onDocumentOpen(documentSource);
                    }
                  : undefined
              }
              selected={source.key === selectedSourceKey}
              source={source}
            />
          ))}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
