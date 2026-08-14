"use client";

import type { Components } from "react-markdown";
import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button, Switch } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import type { DocumentReflowBlock } from "./api";
import type { ReflowBlockTranslationState } from "./use-reflow-translations";

export type ReaderReflowLabels = {
  document: string;
  figurePlaceholder: string;
  fullTranslation: string;
  fullTranslationDescription: string;
  openPdfPage: (page: number) => string;
  original: string;
  retryTranslation: string;
  translated: string;
  translating: string;
  translationFailed: string;
};

const createMarkdownComponents = (figurePlaceholder: string): Components => ({
  a: ({ children, href }) => (
    <a
      className="decoration-line-strong hover:decoration-foreground underline underline-offset-4"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-line-strong text-secondary border-l-2 pl-5 italic">
      {children}
    </blockquote>
  ),
  code: ({ children, className }) => (
    <code
      className={
        className ??
        "bg-subtle rounded-[var(--radius-xs)] px-1.5 py-0.5 text-[0.9em] [overflow-wrap:anywhere]"
      }
    >
      {children}
    </code>
  ),
  h1: ({ children }) => (
    <h1 className="text-3xl leading-tight font-semibold tracking-[-0.025em] text-balance sm:text-4xl">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-12 text-2xl leading-tight font-semibold tracking-[-0.02em]">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-10 text-xl leading-snug font-semibold">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="mt-8 text-lg leading-snug font-semibold">{children}</h4>
  ),
  img: ({ alt }) => (
    <span className="border-line bg-subtle text-secondary block rounded-[var(--radius-lg)] border px-5 py-10 text-center text-sm">
      {alt || figurePlaceholder}
    </span>
  ),
  ol: ({ children }) => (
    <ol className="marker:text-secondary list-decimal space-y-2 pl-6">
      {children}
    </ol>
  ),
  p: ({ children }) => <p>{children}</p>,
  pre: ({ children }) => (
    <pre className="bg-subtle max-w-full overflow-x-auto rounded-[var(--radius-lg)] p-4 text-sm leading-6">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div
      className="border-line max-w-full overflow-x-auto rounded-[var(--radius-lg)] border"
      tabIndex={0}
    >
      <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
        {children}
      </table>
    </div>
  ),
  td: ({ children }) => (
    <td className="border-line border-b px-3 py-2 align-top">{children}</td>
  ),
  th: ({ children }) => (
    <th className="bg-subtle border-line border-b px-3 py-2 font-medium">
      {children}
    </th>
  ),
  ul: ({ children }) => (
    <ul className="marker:text-secondary list-disc space-y-2 pl-6">
      {children}
    </ul>
  ),
});

function MarkdownBlock({
  figurePlaceholder,
  markdown,
}: {
  figurePlaceholder: string;
  markdown: string;
}) {
  const components = React.useMemo(
    () => createMarkdownComponents(figurePlaceholder),
    [figurePlaceholder],
  );
  return (
    <div className="min-w-0 [overflow-wrap:anywhere] [&>*+*]:mt-5">
      <ReactMarkdown components={components} remarkPlugins={[remarkGfm]}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

function ReflowBlock({
  block,
  fullTranslationEnabled,
  labels,
  onOpenPdfPage,
  onRequestTranslation,
  onRetryTranslation,
  targetLanguage,
  translation,
}: {
  block: DocumentReflowBlock;
  fullTranslationEnabled: boolean;
  labels: ReaderReflowLabels;
  onOpenPdfPage?: (page: number) => void;
  onRequestTranslation: (blockId: string) => void;
  onRetryTranslation: (blockId: string) => void;
  targetLanguage: string;
  translation?: ReflowBlockTranslationState;
}) {
  const ref = React.useRef<HTMLElement>(null);

  React.useEffect(() => {
    const element = ref.current;
    if (!element || !fullTranslationEnabled || translation) return;
    if (typeof IntersectionObserver === "undefined") {
      if (block.index < 3) onRequestTranslation(block.id);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          onRequestTranslation(block.id);
          observer.disconnect();
        }
      },
      { rootMargin: "700px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [
    block.id,
    block.index,
    fullTranslationEnabled,
    onRequestTranslation,
    translation,
  ]);

  return (
    <section
      aria-busy={
        translation?.status === "queued" ||
        translation?.status === "streaming" ||
        undefined
      }
      className={cn(
        "min-w-0 scroll-mt-28",
        block.kind === "authors" && "text-secondary text-base leading-7",
        block.kind !== "title" &&
          block.kind !== "authors" &&
          !["heading", "references"].includes(block.kind) &&
          "text-[1.0625rem] leading-8 sm:text-lg sm:leading-9",
      )}
      data-reflow-block={block.id}
      ref={ref}
    >
      <div className="group relative">
        <span className="sr-only">{labels.original}</span>
        <MarkdownBlock
          figurePlaceholder={labels.figurePlaceholder}
          markdown={block.source_markdown}
        />
        {block.page_number &&
        onOpenPdfPage &&
        ["title", "heading", "references"].includes(block.kind) ? (
          <button
            className="text-muted hover:text-foreground mt-2 text-xs opacity-100 transition-opacity sm:absolute sm:top-0 sm:-right-16 sm:mt-0 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
            onClick={() => onOpenPdfPage(block.page_number!)}
            type="button"
          >
            {labels.openPdfPage(block.page_number)}
          </button>
        ) : null}
      </div>

      {fullTranslationEnabled && translation ? (
        <div
          aria-label={labels.translated}
          className="border-line text-secondary mt-4 border-l pl-4 sm:pl-6"
          lang={targetLanguage}
        >
          {translation.status === "error" ? (
            <div className="grid gap-3">
              {translation.text ? (
                <MarkdownBlock
                  figurePlaceholder={labels.figurePlaceholder}
                  markdown={translation.text}
                />
              ) : null}
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span>{labels.translationFailed}</span>
                {translation.retryable ? (
                  <Button
                    onClick={() => onRetryTranslation(block.id)}
                    size="sm"
                    variant="secondary"
                  >
                    {labels.retryTranslation}
                  </Button>
                ) : null}
              </div>
            </div>
          ) : translation.text ? (
            <MarkdownBlock
              figurePlaceholder={labels.figurePlaceholder}
              markdown={translation.text}
            />
          ) : (
            <span className="text-muted animate-pulse text-sm">
              {labels.translating}
            </span>
          )}
        </div>
      ) : null}
    </section>
  );
}

export function ReaderReflowView({
  blocks,
  className,
  fullTranslationEnabled,
  labels,
  onFullTranslationEnabledChange,
  onOpenPdfPage,
  onRequestTranslation,
  onRetryTranslation,
  title,
  targetLanguage,
  translations,
}: {
  blocks: DocumentReflowBlock[];
  className?: string;
  fullTranslationEnabled: boolean;
  labels: ReaderReflowLabels;
  onFullTranslationEnabledChange: (enabled: boolean) => void;
  onOpenPdfPage?: (page: number) => void;
  onRequestTranslation: (blockId: string) => void;
  onRetryTranslation: (blockId: string) => void;
  title: string;
  targetLanguage: string;
  translations: Record<string, ReflowBlockTranslationState>;
}) {
  return (
    <div className={cn("bg-canvas min-h-0 flex-1 overflow-y-auto", className)}>
      <header className="border-line bg-canvas/95 sticky top-0 z-10 border-b backdrop-blur">
        <div className="mx-auto flex max-w-[52rem] items-center justify-between gap-4 px-5 py-3 sm:px-10">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">
              {labels.fullTranslation}
            </p>
            <p className="text-muted hidden truncate text-xs sm:block">
              {labels.fullTranslationDescription}
            </p>
          </div>
          <Switch
            aria-label={labels.fullTranslation}
            checked={fullTranslationEnabled}
            className="relative after:absolute after:inset-x-0 after:-inset-y-2.5"
            onCheckedChange={onFullTranslationEnabledChange}
          />
        </div>
      </header>
      <article
        aria-label={labels.document}
        className="mx-auto grid w-full max-w-[52rem] min-w-0 grid-cols-[minmax(0,1fr)] gap-7 px-5 pt-12 pb-[max(5rem,env(safe-area-inset-bottom))] sm:gap-8 sm:px-10 sm:pt-16"
      >
        <span className="sr-only">{title}</span>
        {blocks.map((block) => (
          <ReflowBlock
            block={block}
            fullTranslationEnabled={fullTranslationEnabled}
            key={block.id}
            labels={labels}
            onOpenPdfPage={onOpenPdfPage}
            onRequestTranslation={onRequestTranslation}
            onRetryTranslation={onRetryTranslation}
            targetLanguage={targetLanguage}
            translation={translations[block.id]}
          />
        ))}
      </article>
    </div>
  );
}
