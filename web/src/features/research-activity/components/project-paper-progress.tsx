"use client";

import type { Route } from "next";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { focusSurfaceVariants } from "@/components/ui";
import { cn } from "@/lib/utilities/cn";
import { formatActivityDuration } from "../format";
import type { ProjectResearchInsights } from "../types";

export function ProjectPaperProgress({
  insights,
  projectId,
}: {
  insights: ProjectResearchInsights;
  projectId: string;
}) {
  const t = useTranslations("ResearchActivity");
  const locale = useLocale();
  if (insights.papers.length === 0) {
    return (
      <p className="text-muted py-10 text-center text-sm">
        {t("project.noPaperActivity")}
      </p>
    );
  }
  return (
    <>
      <div
        className={cn(
          "hidden max-w-full min-w-0 overflow-x-auto sm:block",
          focusSurfaceVariants({ intent: "scroll" }),
        )}
        tabIndex={0}
      >
        <table className="w-full min-w-[52rem] border-collapse text-left text-sm">
          <thead>
            <tr className="text-secondary border-line-subtle border-b text-xs">
              <th className="px-2 py-2 font-medium">
                {t("project.columns.paper")}
              </th>
              <th className="px-2 py-2 font-medium">
                {t("project.columns.reading")}
              </th>
              <th className="px-2 py-2 font-medium">
                {t("project.columns.coverage")}
              </th>
              <th className="px-2 py-2 font-medium">
                {t("project.columns.discussions")}
              </th>
              <th className="px-2 py-2 font-medium">
                {t("project.columns.lastActivity")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-line-subtle divide-y">
            {insights.papers.map((paper) => (
              <tr key={paper.documentId}>
                <td className="max-w-md px-2 py-3">
                  <Link
                    className={cn(
                      "line-clamp-2 font-medium hover:underline",
                      focusSurfaceVariants({ intent: "inline" }),
                    )}
                    href={
                      `/reader/${paper.documentId}?project=${projectId}&panel=insights` as Route
                    }
                  >
                    {paper.title ?? t("paper.untitled")}
                  </Link>
                </td>
                <td className="px-2 py-3 tabular-nums">
                  {formatActivityDuration(paper.activeMs, locale)}
                </td>
                <td className="px-2 py-3 tabular-nums">
                  {paper.coveragePercent == null
                    ? "—"
                    : new Intl.NumberFormat(locale, {
                        maximumFractionDigits: 0,
                        style: "percent",
                      }).format(paper.coveragePercent / 100)}
                </td>
                <td className="px-2 py-3 tabular-nums">
                  {t("project.discussionBreakdown", {
                    annotations: paper.sharedAnnotationCount,
                    messages: paper.discussionMessageCount,
                  })}
                </td>
                <td className="px-2 py-3 tabular-nums">
                  {paper.lastActivityAt ? (
                    new Intl.DateTimeFormat(locale, {
                      dateStyle: "medium",
                    }).format(new Date(paper.lastActivityAt))
                  ) : (
                    <span aria-label={t("project.noLastActivity")}>—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ol className="divide-line-subtle divide-y sm:hidden">
        {insights.papers.map((paper) => (
          <li key={paper.documentId}>
            <Link
              className={cn(
                "hover:bg-hover block rounded-[var(--radius-md)] px-2 py-3",
                focusSurfaceVariants({ intent: "neutral" }),
              )}
              href={
                `/reader/${paper.documentId}?project=${projectId}&panel=insights` as Route
              }
            >
              <span className="line-clamp-2 text-sm font-medium">
                {paper.title ?? t("paper.untitled")}
              </span>
              <span className="text-secondary mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                <span>{formatActivityDuration(paper.activeMs, locale)}</span>
                {paper.coveragePercent == null ? null : (
                  <span>
                    {t("project.coverageValue", {
                      value: Math.round(paper.coveragePercent),
                    })}
                  </span>
                )}
                <span>
                  {t("project.discussionBreakdown", {
                    annotations: paper.sharedAnnotationCount,
                    messages: paper.discussionMessageCount,
                  })}
                </span>
                <span>
                  {paper.lastActivityAt
                    ? t("project.lastActivityValue", {
                        date: new Intl.DateTimeFormat(locale, {
                          dateStyle: "medium",
                        }).format(new Date(paper.lastActivityAt)),
                      })
                    : t("project.noLastActivity")}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
      {insights.papersTotalCount > insights.papers.length ? (
        <p className="text-secondary mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <span>
            {t("project.papersTruncated", {
              shown: insights.papers.length,
              total: insights.papersTotalCount,
            })}
          </span>
          <Link
            className={cn(
              "font-medium hover:underline",
              focusSurfaceVariants({ intent: "inline" }),
            )}
            href={`/projects/${projectId}?view=papers` as Route}
          >
            {t("project.viewPapers")}
          </Link>
        </p>
      ) : null}
    </>
  );
}
