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
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  EditIcon,
  MoreIcon,
  ProjectIcon,
} from "@/design-system/icons/semantic-icons";
import type { components } from "@/lib/api/generated/schema";

type Project = components["schemas"]["ProjectResponse"];

export function ProjectCard({
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
    <article className="border-line bg-surface hover:border-line-strong flex min-h-56 flex-col rounded-[var(--radius-xl)] border p-5 transition-colors">
      <div className="flex min-w-0 items-start gap-3">
        <div className="bg-subtle grid size-10 shrink-0 place-items-center rounded-[var(--radius-lg)]">
          <Icon glyph={ProjectIcon} size={20} tone="secondary" />
        </div>
        <div className="min-w-0 flex-1">
          <Link
            className="hover:text-secondary block truncate text-base font-semibold"
            href={`/projects/${project.id}` as Route}
          >
            {project.title}
          </Link>
          <p className="text-secondary mt-1 line-clamp-2 min-h-10 text-sm leading-5">
            {project.description || t("card.noDescription")}
          </p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <IconButton label={t("card.openMenu")} variant="ghost">
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
      <dl className="mt-5 grid grid-cols-3 gap-4">
        {(
          [
            ["papers", project.num_papers],
            ["conversations", project.num_conversations],
            ["outputs", project.num_outputs],
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <dd className="text-base font-semibold tabular-nums">{value}</dd>
            <dt className="text-muted mt-0.5 text-xs">
              {t(`metrics.${label}`)}
            </dt>
          </div>
        ))}
      </dl>
      <div className="border-line text-muted mt-4 border-t pt-4 text-right text-xs">
        {t("card.updated", {
          date: format.dateTime(new Date(project.activity_at), "timestamp"),
        })}
      </div>
    </article>
  );
}
