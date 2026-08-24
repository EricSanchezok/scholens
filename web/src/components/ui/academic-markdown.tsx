"use client";

import type { Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { cn } from "@/lib/utilities/cn";
import { focusSurfaceVariants } from "./focus";

type AcademicMarkdownProps = Omit<
  React.ComponentPropsWithoutRef<"div">,
  "children"
> & {
  children: string;
  components?: Omit<Components, "span">;
};

function OverflowAwareMathDisplay({
  children,
  className,
  ...props
}: React.ComponentPropsWithoutRef<"span">) {
  const elementRef = React.useRef<HTMLSpanElement>(null);
  const [overflowing, setOverflowing] = React.useState(false);

  React.useLayoutEffect(() => {
    const element = elementRef.current;
    if (!element) return;
    let active = true;
    const update = () => {
      if (active) {
        setOverflowing(element.scrollWidth > element.clientWidth + 1);
      }
    };
    update();
    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(update);
    observer?.observe(element);
    if (element.firstElementChild) observer?.observe(element.firstElementChild);
    void document.fonts?.ready.then(update);
    return () => {
      active = false;
      observer?.disconnect();
    };
  }, []);

  return (
    <span
      {...props}
      className={cn(className, focusSurfaceVariants({ intent: "scroll" }))}
      data-overflow-focus={overflowing || undefined}
      ref={elementRef}
      tabIndex={overflowing ? 0 : undefined}
    >
      {children}
    </span>
  );
}

function transformOutsideInlineCode(
  value: string,
  transform: (segment: string) => string,
) {
  const output: string[] = [];
  let cursor = 0;
  let segmentStart = 0;

  while (cursor < value.length) {
    if (value[cursor] !== "`") {
      cursor += 1;
      continue;
    }
    let markerEnd = cursor + 1;
    while (value[markerEnd] === "`") markerEnd += 1;
    const marker = value.slice(cursor, markerEnd);
    const closing = value.indexOf(marker, markerEnd);
    if (closing < 0) {
      output.push(transform(value.slice(segmentStart, cursor)));
      output.push(value.slice(cursor));
      segmentStart = value.length;
      break;
    }

    output.push(transform(value.slice(segmentStart, cursor)));
    output.push(value.slice(cursor, closing + marker.length));
    cursor = closing + marker.length;
    segmentStart = cursor;
  }

  output.push(transform(value.slice(segmentStart)));
  return output.join("");
}

function normalizeDelimiterSegment(value: string) {
  return value
    .replace(
      /(^|[^\\])\\\[([\s\S]*?)\\\]/g,
      (match, prefix: string, expression: string) => {
        const normalized = expression.trim();
        return normalized ? `${prefix}\n\n$$\n${normalized}\n$$\n\n` : match;
      },
    )
    .replace(
      /(^|[^\\])\\\(([\s\S]*?)\\\)/g,
      (match, prefix: string, expression: string) => {
        const normalized = expression.trim();
        return normalized ? `${prefix}$${normalized}$` : match;
      },
    );
}

/** Normalize common TeX delimiters without rewriting Markdown code regions. */
export function normalizeAcademicMathDelimiters(markdown: string) {
  const output: string[] = [];
  const prose: string[] = [];
  const lines = markdown.match(/.*(?:\n|$)/g) ?? [];
  let fence: { marker: "`" | "~"; length: number } | null = null;

  const flushProse = () => {
    if (!prose.length) return;
    output.push(
      transformOutsideInlineCode(prose.join(""), normalizeDelimiterSegment),
    );
    prose.length = 0;
  };

  for (const line of lines) {
    const candidate = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (fence) {
      output.push(line);
      const closing = line.match(/^ {0,3}(`+|~+)[ \t]*(?:\n|$)/);
      if (
        closing &&
        closing[1]![0] === fence.marker &&
        closing[1]!.length >= fence.length
      ) {
        fence = null;
      }
      continue;
    }
    if (candidate) {
      flushProse();
      const marker = candidate[1]!;
      fence = {
        marker: marker[0] as "`" | "~",
        length: marker.length,
      };
      output.push(line);
      continue;
    }
    prose.push(line);
  }
  flushProse();
  return output.join("");
}

const academicComponents: Pick<Components, "span"> = {
  span: ({ children, className, node: _node, ...props }) => {
    void _node;
    if (className?.includes("katex-display")) {
      return (
        <OverflowAwareMathDisplay {...props} className={className}>
          {children}
        </OverflowAwareMathDisplay>
      );
    }
    return (
      <span {...props} className={className}>
        {children}
      </span>
    );
  },
};

export function AcademicMarkdown({
  children,
  className,
  components,
  ...props
}: AcademicMarkdownProps) {
  const normalized = React.useMemo(
    () => normalizeAcademicMathDelimiters(children),
    [children],
  );
  const markdownComponents = React.useMemo<Components>(
    () => ({ ...components, ...academicComponents }),
    [components],
  );

  return (
    <div
      className={cn(
        "max-w-full min-w-0 [overflow-wrap:anywhere] [&_.katex-display]:max-w-full [&_.katex-display]:overflow-x-auto [&_.katex-display]:overscroll-x-contain [&_.katex-display]:py-[0.5em]",
        className,
      )}
      {...props}
    >
      <ReactMarkdown
        components={markdownComponents}
        rehypePlugins={[rehypeKatex]}
        remarkPlugins={[remarkGfm, remarkMath]}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
}
