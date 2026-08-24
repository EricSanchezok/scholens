"use client";

import { useQuery } from "@tanstack/react-query";
import type { Components } from "react-markdown";
import * as React from "react";

import { Button } from "@/components/ui";
import { AcademicMarkdown } from "@/components/ui/academic-markdown";
import {
  academicMarkdownToPlainText,
  sanitizeAcademicMarkdown,
} from "@/lib/content/academic-text";
import { cn } from "@/lib/utilities/cn";
import {
  reflowQueries,
  type DocumentReflowAsset,
  type DocumentReflowBlock,
  type DocumentReflowSourceSpan,
} from "./api";
import type { ReflowBlockTranslationState } from "./use-reflow-translations";

export type ReaderReflowLabels = {
  degradedDescription: string;
  degradedTitle: string;
  document: string;
  figurePlaceholder: string;
  openPdfPage: (page: number) => string;
  original: string;
  paperInformation: string;
  repaired: string;
  retryTranslation: string;
  translated: string;
  translationFailed: string;
  translationMarker: string;
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
    <h1 className="text-3xl leading-[1.14] font-semibold tracking-[-0.025em] text-balance sm:text-4xl">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-2xl leading-tight font-semibold tracking-[-0.02em]">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-xl leading-snug font-semibold">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="text-lg leading-snug font-semibold">{children}</h4>
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
    <pre className="bg-subtle max-w-full overflow-x-auto rounded-[var(--radius-lg)] p-4 font-mono text-sm leading-6">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div
      className="border-line max-w-full overflow-x-auto overscroll-x-contain rounded-[var(--radius-lg)] border"
      tabIndex={0}
    >
      <table className="w-full min-w-[36rem] border-collapse text-left font-sans text-sm">
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

export function primaryReflowSource(block: DocumentReflowBlock) {
  return block.source_spans[0];
}

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
    <AcademicMarkdown className="[&>*+*]:mt-5" components={components}>
      {sanitizeAcademicMarkdown(markdown)}
    </AcademicMarkdown>
  );
}

function ReflowFigure({
  active,
  asset,
  documentId,
  label,
}: {
  active: boolean;
  asset: DocumentReflowAsset;
  documentId: string;
  label: string;
}) {
  const assetQuery = useQuery(
    reflowQueries.asset(documentId, asset.id, active),
  );
  if (!active || assetQuery.isPending) {
    return (
      <div
        aria-label={label}
        className="motion-skeleton bg-subtle aspect-[4/3] w-full rounded-[var(--radius-lg)]"
      />
    );
  }
  if (!assetQuery.data?.url) {
    return (
      <div className="border-line text-muted rounded-[var(--radius-lg)] border px-5 py-12 text-center font-sans text-sm">
        {label}
      </div>
    );
  }
  return (
    // Signed reflow assets are short-lived and must bypass Next's persistent
    // image optimizer cache while retaining native lazy loading.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      alt={label}
      className="mx-auto h-auto max-h-[42rem] w-auto max-w-full rounded-[var(--radius-md)] object-contain"
      decoding="async"
      height={asset.height}
      loading="lazy"
      src={assetQuery.data.url}
      width={asset.width}
    />
  );
}

const untranslatableKinds = new Set<DocumentReflowBlock["kind"]>([
  "authors",
  "affiliations",
  "code",
  "equation",
  "figure",
]);

export function isTranslatableReflowBlock(
  block: DocumentReflowBlock,
  translateReferences: boolean,
) {
  if (untranslatableKinds.has(block.kind)) return false;
  return block.kind !== "references" || translateReferences;
}

function ReflowBlock({
  asset,
  block,
  documentId,
  fullTranslationDisplay,
  fullTranslationEnabled,
  labels,
  onOpenPdfSource,
  onRequestTranslation,
  onRetryTranslation,
  showTranslationMarker,
  targetLanguage,
  translatable,
  translation,
}: {
  asset?: DocumentReflowAsset;
  block: DocumentReflowBlock;
  documentId: string;
  fullTranslationDisplay: "bilingual" | "translation_only";
  fullTranslationEnabled: boolean;
  labels: ReaderReflowLabels;
  onOpenPdfSource?: (source: DocumentReflowSourceSpan) => void;
  onRequestTranslation: (blockId: string) => void;
  onRetryTranslation: (blockId: string) => void;
  showTranslationMarker: boolean;
  targetLanguage: string;
  translatable: boolean;
  translation?: ReflowBlockTranslationState;
}) {
  const ref = React.useRef<HTMLElement>(null);
  const [nearViewport, setNearViewport] = React.useState(
    () => typeof IntersectionObserver === "undefined",
  );

  React.useEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (typeof IntersectionObserver === "undefined") {
      if (fullTranslationEnabled && translatable && !translation) {
        onRequestTranslation(block.id);
      }
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setNearViewport(true);
        if (fullTranslationEnabled && translatable && !translation) {
          onRequestTranslation(block.id);
        }
        observer.disconnect();
      },
      { rootMargin: "700px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [
    block.id,
    fullTranslationEnabled,
    onRequestTranslation,
    translatable,
    translation,
  ]);

  const translatedText = translation?.text;
  const showOriginal =
    !fullTranslationEnabled ||
    !translatable ||
    fullTranslationDisplay === "bilingual" ||
    !translatedText;
  const source = block.render_markdown;
  const primarySource = primaryReflowSource(block);
  const pageNumber = primarySource?.page_number;
  const metadataVisible =
    pageNumber !== undefined || block.presentation_status === "repaired";

  return (
    <section
      aria-busy={
        translation?.status === "queued" ||
        translation?.status === "streaming" ||
        undefined
      }
      className={cn(
        "group min-w-0 scroll-mt-24",
        block.kind === "title" && "mt-1",
        block.kind === "heading" && "mt-5 sm:mt-7",
        block.kind === "caption" && "-mt-4",
      )}
      data-presentation-status={block.presentation_status}
      data-reflow-block={block.id}
      data-reflow-kind={block.kind}
      ref={ref}
    >
      {showOriginal ? (
        <div
          className={cn(
            "relative min-w-0 [font-family:var(--font-reading-serif)]",
            block.kind === "eyebrow" &&
              "text-muted font-sans text-xs font-medium tracking-[0.08em] uppercase",
            block.kind === "title" && "mb-1",
            ["authors", "affiliations"].includes(block.kind) &&
              "text-secondary font-sans text-sm leading-6",
            block.kind === "abstract" &&
              "text-[1rem] leading-[1.68] sm:text-[1.02rem] sm:leading-[1.72]",
            block.kind === "keywords" &&
              "text-secondary font-sans text-sm leading-6",
            block.kind === "paragraph" &&
              "text-[1rem] leading-[1.65] sm:text-[1.0625rem] sm:leading-[1.75]",
            ["list", "quote", "footnote", "references"].includes(block.kind) &&
              "text-[1rem] leading-[1.65] sm:text-[1.02rem] sm:leading-[1.72]",
            block.kind === "equation" &&
              "my-1 max-w-full text-[0.98rem] leading-relaxed",
            block.kind === "caption" &&
              "text-secondary mx-auto max-w-[60rem] px-3 text-center font-sans text-sm leading-6",
          )}
        >
          <span className="sr-only">{labels.original}</span>
          {block.presentation_status === "degraded" ? (
            <div className="border-line bg-subtle rounded-[var(--radius-lg)] border p-4 font-sans">
              <p className="text-sm font-medium">{labels.degradedTitle}</p>
              <p className="text-muted mt-1 text-sm leading-6">
                {labels.degradedDescription}
              </p>
              {pageNumber && primarySource && onOpenPdfSource ? (
                <Button
                  className="mt-3"
                  onClick={() => onOpenPdfSource(primarySource)}
                  size="sm"
                  variant="secondary"
                >
                  {labels.openPdfPage(pageNumber)}
                </Button>
              ) : null}
            </div>
          ) : block.kind === "figure" && asset ? (
            <ReflowFigure
              active={nearViewport}
              asset={asset}
              documentId={documentId}
              label={
                academicMarkdownToPlainText(source) || labels.figurePlaceholder
              }
            />
          ) : (
            <MarkdownBlock
              figurePlaceholder={labels.figurePlaceholder}
              markdown={source}
            />
          )}

          {metadataVisible && block.presentation_status !== "degraded" ? (
            <div className="motion-control bg-canvas border-line text-muted pointer-events-none absolute top-full right-0 z-10 mt-1 flex items-center gap-2 rounded-[var(--radius-sm)] border px-2 py-1 font-sans text-xs opacity-0 shadow-sm group-focus-within:pointer-events-auto group-focus-within:opacity-100 group-hover:pointer-events-auto group-hover:opacity-100">
              {block.presentation_status === "repaired" ? (
                <span>{labels.repaired}</span>
              ) : null}
              {pageNumber && primarySource && onOpenPdfSource ? (
                <button
                  className="hover:text-foreground underline-offset-4 hover:underline"
                  onClick={() => onOpenPdfSource(primarySource)}
                  type="button"
                >
                  {labels.openPdfPage(pageNumber)}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {fullTranslationEnabled && translatable && translation ? (
        <div
          aria-label={labels.translated}
          className={cn(
            "min-w-0 font-sans text-[1.02rem] leading-[1.72]",
            fullTranslationDisplay === "bilingual" &&
              "border-line text-secondary mt-4 border-l pl-4 sm:pl-6",
          )}
          lang={targetLanguage}
          role="group"
        >
          {showTranslationMarker && translation.text ? (
            <span className="text-muted mb-1 block text-[0.6875rem] font-medium tracking-[0.08em] uppercase">
              {labels.translationMarker}
            </span>
          ) : null}
          {translation.status === "error" ? (
            <div className="grid gap-2">
              {translation.text ? (
                <MarkdownBlock
                  figurePlaceholder={labels.figurePlaceholder}
                  markdown={translation.text}
                />
              ) : null}
              <div className="text-muted flex flex-wrap items-center gap-3 text-sm">
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
            <div aria-hidden className="grid gap-2 py-1">
              <span className="motion-skeleton bg-subtle h-3 w-[92%] rounded-full" />
              <span className="motion-skeleton bg-subtle h-3 w-[74%] rounded-full" />
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}

function PaperInformation({
  blocks,
  renderBlock,
  title,
}: {
  blocks: DocumentReflowBlock[];
  renderBlock: (block: DocumentReflowBlock) => React.ReactNode;
  title: string;
}) {
  if (blocks.length === 0) return null;
  return (
    <details className="border-line border-y py-3">
      <summary className="cursor-pointer list-none font-sans text-sm font-medium [&::-webkit-details-marker]:hidden">
        {title}
      </summary>
      <div className="border-line mt-3 grid gap-3 border-t pt-3">
        {blocks.map(renderBlock)}
      </div>
    </details>
  );
}

export function ReaderReflowView({
  assets,
  blocks,
  className,
  documentId,
  fullTranslationDisplay,
  fullTranslationEnabled,
  labels,
  onOpenPdfSource,
  onRequestTranslation,
  onRetryTranslation,
  scrollContainerRef,
  showTranslationMarker,
  targetLanguage,
  translateReferences,
  translations,
}: {
  assets: DocumentReflowAsset[];
  blocks: DocumentReflowBlock[];
  className?: string;
  documentId: string;
  fullTranslationDisplay: "bilingual" | "translation_only";
  fullTranslationEnabled: boolean;
  labels: ReaderReflowLabels;
  onOpenPdfSource?: (source: DocumentReflowSourceSpan) => void;
  onRequestTranslation: (blockId: string) => void;
  onRetryTranslation: (blockId: string) => void;
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
  showTranslationMarker: boolean;
  targetLanguage: string;
  translateReferences: boolean;
  translations: Record<string, ReflowBlockTranslationState>;
}) {
  const assetById = React.useMemo(
    () => new Map(assets.map((asset) => [asset.id, asset])),
    [assets],
  );
  const infoBlocks = blocks.filter((block) =>
    ["authors", "affiliations"].includes(block.kind),
  );
  const infoIds = new Set(infoBlocks.map((block) => block.id));
  const firstInfoIndex = blocks.findIndex((block) => infoIds.has(block.id));

  const renderBlock = (block: DocumentReflowBlock) => (
    <ReflowBlock
      asset={block.asset_id ? assetById.get(block.asset_id) : undefined}
      block={block}
      documentId={documentId}
      fullTranslationDisplay={fullTranslationDisplay}
      fullTranslationEnabled={fullTranslationEnabled}
      key={block.id}
      labels={labels}
      onOpenPdfSource={onOpenPdfSource}
      onRequestTranslation={onRequestTranslation}
      onRetryTranslation={onRetryTranslation}
      showTranslationMarker={showTranslationMarker}
      targetLanguage={targetLanguage}
      translatable={isTranslatableReflowBlock(block, translateReferences)}
      translation={translations[block.id]}
    />
  );

  return (
    <div
      className={cn(
        "bg-canvas min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-x-none",
        className,
      )}
      ref={scrollContainerRef}
    >
      <article
        aria-label={labels.document}
        className="mx-auto grid w-full max-w-[var(--layout-reading-column)] min-w-0 grid-cols-[minmax(0,1fr)] gap-5 px-5 pt-9 pb-[max(5rem,env(safe-area-inset-bottom))] sm:gap-6 sm:px-8 sm:pt-12"
      >
        {blocks.map((block, index) => {
          if (index === firstInfoIndex) {
            return (
              <PaperInformation
                blocks={infoBlocks}
                key="paper-information"
                renderBlock={renderBlock}
                title={labels.paperInformation}
              />
            );
          }
          if (infoIds.has(block.id)) return null;
          return renderBlock(block);
        })}
      </article>
    </div>
  );
}
