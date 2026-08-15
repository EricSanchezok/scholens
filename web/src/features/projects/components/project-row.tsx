"use client";

import type { Route } from "next";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  keyboardFocusRing,
  OverflowMenuButton,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { EditIcon, ProjectIcon } from "@/design-system/icons/semantic-icons";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";

type Project = components["schemas"]["ProjectResponse"];

export function ProjectRow({
  project,
  onDelete,
  onEdit,
  onLeave,
}: {
  project: Project;
  onDelete: (project: Project) => void;
  onEdit: (project: Project) => void;
  onLeave: (project: Project) => void;
}) {
  const t = useTranslations("Projects");
  const format = useFormatter();

  return (
    <article className="motion-control group/interactive-row hover:bg-hover focus-within:bg-hover active:bg-pressed flex min-w-0 items-start gap-1 rounded-[var(--radius-xl)] p-1">
      <Link
        aria-label={project.title}
        className={cn(
          "flex min-w-0 flex-1 items-start gap-3 rounded-[var(--radius-lg)] px-2 py-3 sm:gap-4 sm:px-3",
          keyboardFocusRing,
        )}
        href={`/projects/${project.id}` as Route}
      >
        <span className="bg-subtle mt-0.5 grid size-10 shrink-0 place-items-center rounded-[var(--radius-lg)]">
          <Icon glyph={ProjectIcon} size={20} tone="secondary" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block min-w-0 truncate text-base font-semibold tracking-[-0.01em]">
            {project.title}
          </span>
          <span className="text-secondary mt-1 line-clamp-2 block text-sm leading-5">
            {project.description || t("row.noDescription")}
          </span>
          <span className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span className="text-secondary flex flex-wrap items-center gap-x-4 gap-y-1">
              {(
                [
                  ["papers", project.num_papers],
                  ["conversations", project.num_conversations],
                  ["outputs", project.num_outputs],
                ] as const
              ).map(([label, value]) => (
                <span className="flex items-baseline gap-1" key={label}>
                  <span>{t(`metrics.${label}`)}</span>
                  <span className="text-foreground order-first font-medium tabular-nums">
                    {format.number(value)}
                  </span>
                </span>
              ))}
            </span>
            <span className="text-secondary sm:ml-auto">
              {t("row.updated", {
                date: format.dateTime(
                  new Date(project.activity_at),
                  "timestamp",
                ),
              })}
            </span>
          </span>
        </span>
      </Link>
      <div className="mt-1 shrink-0">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <OverflowMenuButton
              label={t("row.openMenu")}
              visibility="contextual"
            />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem asChild>
              <Link href={`/projects/${project.id}` as Route}>
                {t("actions.open")}
              </Link>
            </DropdownMenuItem>
            {project.capabilities.edit_project && (
              <DropdownMenuItem onSelect={() => onEdit(project)}>
                <Icon glyph={EditIcon} size={16} />
                {t("actions.rename")}
              </DropdownMenuItem>
            )}
            {(project.capabilities.delete || project.capabilities.leave) && (
              <DropdownMenuSeparator />
            )}
            {project.capabilities.delete && (
              <DropdownMenuItem destructive onSelect={() => onDelete(project)}>
                {t("actions.delete")}
              </DropdownMenuItem>
            )}
            {project.capabilities.leave && (
              <DropdownMenuItem destructive onSelect={() => onLeave(project)}>
                {t("actions.leave")}
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </article>
  );
}
