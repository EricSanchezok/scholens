"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { Button } from "@/components/ui";
import type { components } from "@/lib/api/generated/schema";
import { projectQueries } from "../api";

type Project = components["schemas"]["ProjectResponse"];
type ProjectMember = components["schemas"]["ProjectCollaboratorResponse"];

function memberInitial(member: ProjectMember) {
  return member.display_name.trim().charAt(0).toUpperCase() || "?";
}

export function ProjectCollaboration({
  onManage,
  project,
}: {
  onManage: () => void;
  project: Project;
}) {
  const t = useTranslations("Projects");
  const membersQuery = useQuery(projectQueries.members(project.id));
  const members = membersQuery.data?.items;
  const memberCount = members?.length ?? project.num_collaborators + 1;

  return (
    <section
      aria-labelledby="project-collaboration-heading"
      className="min-w-0"
      data-project-collaboration
    >
      <div className="mb-3 flex min-w-0 flex-wrap items-center justify-between gap-2">
        <h2
          className="text-base font-semibold"
          id="project-collaboration-heading"
        >
          {t("detail.collaboration")}
        </h2>
        <span className="flex min-w-0 items-center gap-2">
          <span className="text-secondary shrink-0 text-xs tabular-nums">
            {t("detail.memberCount", { count: memberCount })}
          </span>
          {project.capabilities.manage_collaborators ? (
            <Button onClick={onManage} size="sm" variant="ghost">
              {t("detail.manageMembers")}
            </Button>
          ) : null}
        </span>
      </div>
      <div className="border-line-subtle min-w-0 border-y">
        {!members && membersQuery.isPending ? (
          <div className="px-1 py-4">
            <LoadingState presentation="inline" />
          </div>
        ) : !members && membersQuery.isError ? (
          <div className="px-1 py-3">
            <AsyncFeedback
              action={{
                label: t("feedback.retry"),
                onClick: () => void membersQuery.refetch(),
              }}
              presentation="inline"
              state="error"
            />
          </div>
        ) : (
          <ul className="divide-line-subtle min-w-0 divide-y">
            {(members ?? []).map((member) => (
              <li
                className="flex min-w-0 items-center gap-3 py-3"
                key={member.user_id}
              >
                <span
                  aria-hidden="true"
                  className="bg-pressed grid size-8 shrink-0 place-items-center rounded-full text-sm font-medium"
                >
                  {memberInitial(member)}
                </span>
                <span className="text-secondary min-w-0 truncate text-sm">
                  {member.display_name}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
