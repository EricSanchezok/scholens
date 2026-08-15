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
  IconButton,
  keyboardFocusRing,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  EditIcon,
  MoreIcon,
  ProjectIcon,
} from "@/design-system/icons/semantic-icons";
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
    <article className="group hover:bg-hover flex min-w-0 items-start gap-3 rounded-[var(--radius-xl)] px-3 py-4 transition-colors motion-reduce:transition-none sm:gap-4 sm:px-4">
      <Link
        aria-label={t("row.open", { title: project.title })}
        className={cn(
          "bg-subtle mt-0.5 grid size-10 shrink-0 place-items-center rounded-[var(--radius-lg)]",
          keyboardFocusRing,
        )}
        href={`/projects/${project.id}` as Route}
      >
        <Icon glyph={ProjectIcon} size={20} tone="secondary" />
      </Link>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-start gap-3">
          <div className="min-w-0 flex-1">
            <Link
              className={cn(
                "hover:text-secondary block w-fit max-w-full truncate text-base font-semibold tracking-[-0.01em]",
                keyboardFocusRing,
              )}
              href={`/projects/${project.id}` as Route}
            >
              {project.title}
            </Link>
            <p className="text-secondary mt-1 line-clamp-2 text-sm leading-5">
              {project.description || t("row.noDescription")}
            </p>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <IconButton label={t("row.openMenu")} variant="ghost">
                <Icon glyph={MoreIcon} size={20} />
              </IconButton>
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
                <DropdownMenuItem
                  destructive
                  onSelect={() => onDelete(project)}
                >
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
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <dl className="text-secondary flex flex-wrap items-center gap-x-4 gap-y-1">
            {(
              [
                ["papers", project.num_papers],
                ["conversations", project.num_conversations],
                ["outputs", project.num_outputs],
              ] as const
            ).map(([label, value]) => (
              <div className="flex items-baseline gap-1" key={label}>
                <dt>{t(`metrics.${label}`)}</dt>
                <dd className="text-foreground order-first font-medium tabular-nums">
                  {format.number(value)}
                </dd>
              </div>
            ))}
          </dl>
          <span className="text-muted sm:ml-auto">
            {t("row.updated", {
              date: format.dateTime(new Date(project.activity_at), "timestamp"),
            })}
          </span>
        </div>
      </div>
    </article>
  );
}
