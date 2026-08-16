"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import { useAuthSession } from "@/features/authentication";
import { ApiError } from "@/lib/api";
import { acceptProjectInvitation } from "./api/mutations";
import { projectKeys } from "./api/keys";

export function ProjectInvitationPage({ token }: { token: string }) {
  const t = useTranslations("ProjectInvitation");
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useAuthSession();
  const [attempt, setAttempt] = React.useState(0);
  const attempted = React.useRef<string | undefined>(undefined);
  const invitationPath = `/project-invitations/${token}`;
  const mutation = useMutation({ mutationFn: acceptProjectInvitation });

  React.useEffect(() => {
    if (session.status === "anonymous") {
      router.replace(`/login?returnTo=${encodeURIComponent(invitationPath)}`);
    }
  }, [invitationPath, router, session.status]);

  React.useEffect(() => {
    if (session.status !== "authenticated") return;
    const attemptKey = `${token}:${attempt}`;
    if (attempted.current === attemptKey) return;
    attempted.current = attemptKey;
    mutation.mutate(token, {
      onSuccess: async ({ project_id: projectId }) => {
        await queryClient.invalidateQueries({ queryKey: projectKeys.all });
        router.replace(`/projects/${projectId}`);
      },
    });
  }, [attempt, mutation, queryClient, router, session.status, token]);

  if (session.status === "unavailable") {
    return (
      <ProjectInvitationShell>
        <AsyncFeedback
          action={{ label: t("retry"), onClick: session.retryBootstrap }}
          description={t("sessionUnavailableDescription")}
          state="offline"
          title={t("sessionUnavailableTitle")}
        />
      </ProjectInvitationShell>
    );
  }

  if (
    session.status === "bootstrapping" ||
    session.status === "anonymous" ||
    mutation.isIdle ||
    mutation.isPending ||
    mutation.isSuccess
  ) {
    return (
      <ProjectInvitationShell>
        <LoadingState
          label={mutation.isSuccess ? t("openingProject") : t("accepting")}
        />
      </ProjectInvitationShell>
    );
  }

  const error = mutation.error;
  const code = error instanceof ApiError ? error.code : undefined;
  if (code === "project_invitation_recipient_mismatch") {
    return (
      <ProjectInvitationShell>
        <AsyncFeedback
          action={{
            label: t("switchAccount"),
            onClick: async () => {
              await session.signOut();
              router.replace(
                `/login?returnTo=${encodeURIComponent(invitationPath)}`,
              );
            },
          }}
          description={t("accountMismatchDescription")}
          state="error"
          title={t("accountMismatchTitle")}
        />
      </ProjectInvitationShell>
    );
  }

  if (
    code === "project_invitation_invalid" ||
    code === "project_invitation_authority_revoked" ||
    code === "project_collaborator_exists"
  ) {
    return (
      <ProjectInvitationShell>
        <AsyncFeedback
          action={{
            label: t("viewProjects"),
            onClick: () => router.replace("/projects"),
          }}
          description={
            code === "project_invitation_authority_revoked"
              ? t("authorityRevokedDescription")
              : code === "project_collaborator_exists"
                ? t("alreadyMemberDescription")
                : t("invalidDescription")
          }
          state="error"
          title={
            code === "project_collaborator_exists"
              ? t("alreadyMemberTitle")
              : t("invalidTitle")
          }
        />
      </ProjectInvitationShell>
    );
  }

  return (
    <ProjectInvitationShell>
      <AsyncFeedback
        action={{
          label: t("retry"),
          onClick: () => {
            mutation.reset();
            setAttempt((value) => value + 1);
          },
        }}
        description={
          error instanceof ApiError && error.correlationId
            ? t("retryDescriptionWithRequest", {
                requestId: error.correlationId,
              })
            : t("retryDescription")
        }
        state="offline"
        title={t("retryTitle")}
      />
    </ProjectInvitationShell>
  );
}

function ProjectInvitationShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="bg-canvas grid min-h-screen place-items-center px-4 py-10">
      <div className="border-line bg-surface w-full max-w-lg rounded-[var(--radius-xl)] border p-6 sm:p-9">
        {children}
      </div>
    </main>
  );
}
