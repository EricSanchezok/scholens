"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import * as React from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHandle,
  DialogHeader,
  DialogTitle,
  Field,
  FieldControl,
  FieldLabel,
  FieldMessage,
  Input,
} from "@/components/ui";
import { ApiError } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import {
  createProjectInvitation,
  removeProjectMember,
  resendProjectInvitation,
  revokeProjectInvitation,
  updateProjectMember,
} from "../api/mutations";
import { projectKeys } from "../api/keys";
import { projectQueries } from "../api/queries";

type Project = components["schemas"]["ProjectResponse"];
type Member = components["schemas"]["ProjectCollaboratorResponse"];
type Invitation = components["schemas"]["ProjectInvitationResponse"];
type Permissions = components["schemas"]["ProjectPermissionSet"];

const inviteSchema = z.object({
  email: z.email(),
  edit_project: z.boolean(),
  manage_papers: z.boolean(),
  manage_collaborators: z.boolean(),
});

type InviteValues = z.infer<typeof inviteSchema>;

const emptyPermissions: Permissions = {
  edit_project: false,
  manage_collaborators: false,
  manage_papers: false,
};

function ErrorMessage({ error }: { error: unknown }) {
  const t = useTranslations("Projects.collaborators.errors");
  if (!(error instanceof ApiError)) return <>{t("offline")}</>;
  if (error.code === "project_collaborator_exists") {
    return <>{t("alreadyMember")}</>;
  }
  if (error.code === "project_invitation_delivery_pending") {
    return <>{t("deliveryPending")}</>;
  }
  if (error.code === "project_permission_escalation") {
    return <>{t("permissionEscalation")}</>;
  }
  if (error.code === "project_collaborator_not_manageable") {
    return <>{t("notManageable")}</>;
  }
  return (
    <>
      {error.correlationId
        ? t("unknownWithRequest", { requestId: error.correlationId })
        : t("unknown")}
    </>
  );
}

function PermissionFields({
  disabled,
  onChange,
  value,
}: {
  disabled: Permissions;
  onChange: (permissions: Permissions) => void;
  value: Permissions;
}) {
  const t = useTranslations("Projects.collaborators.permissions");
  const fields = [
    ["edit_project", "editProject"],
    ["manage_papers", "managePapers"],
    ["manage_collaborators", "manageCollaborators"],
  ] as const;
  return (
    <div className="grid gap-2">
      {fields.map(([field, label]) => (
        <label className="flex min-h-11 items-center gap-3 text-sm" key={field}>
          <Checkbox
            checked={value[field]}
            disabled={disabled[field]}
            onCheckedChange={(checked) =>
              onChange({ ...value, [field]: checked === true })
            }
          />
          <span>{t(label)}</span>
        </label>
      ))}
    </div>
  );
}

function MemberRow({
  actorId,
  actorPermissions,
  member,
  onRemove,
  onUpdate,
}: {
  actorId: number;
  actorPermissions: Permissions;
  member: Member;
  onRemove: (userId: number) => Promise<unknown>;
  onUpdate: (userId: number, permissions: Permissions) => Promise<unknown>;
}) {
  const t = useTranslations("Projects.collaborators");
  const [permissions, setPermissions] = React.useState(member.permissions);
  const [error, setError] = React.useState<unknown>();
  const [action, setAction] = React.useState<"save" | "remove" | null>(null);
  const withinActorAuthority =
    (!member.permissions.edit_project || actorPermissions.edit_project) &&
    (!member.permissions.manage_papers || actorPermissions.manage_papers) &&
    (!member.permissions.manage_collaborators ||
      actorPermissions.manage_collaborators);
  const immutable =
    member.is_owner || member.user_id === actorId || !withinActorAuthority;
  const changed =
    permissions.edit_project !== member.permissions.edit_project ||
    permissions.manage_papers !== member.permissions.manage_papers ||
    permissions.manage_collaborators !==
      member.permissions.manage_collaborators;

  async function run(nextAction: "save" | "remove") {
    setError(undefined);
    setAction(nextAction);
    try {
      if (nextAction === "save") await onUpdate(member.user_id, permissions);
      else await onRemove(member.user_id);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setAction(null);
    }
  }

  return (
    <article className="border-line grid gap-3 border-t py-4 first:border-t-0 first:pt-0">
      <div className="flex min-w-0 items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{member.display_name}</p>
          <p className="text-muted truncate text-xs">{member.email}</p>
        </div>
        {member.is_owner ? (
          <span className="bg-subtle text-secondary rounded-full px-2.5 py-1 text-xs">
            {t("owner")}
          </span>
        ) : null}
      </div>
      {!member.is_owner ? (
        <>
          <PermissionFields
            disabled={{
              edit_project: immutable || !actorPermissions.edit_project,
              manage_collaborators:
                immutable || !actorPermissions.manage_collaborators,
              manage_papers: immutable || !actorPermissions.manage_papers,
            }}
            onChange={setPermissions}
            value={permissions}
          />
          {!immutable ? (
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={!changed}
                loading={action === "save"}
                onClick={() => void run("save")}
                size="sm"
                type="button"
                variant="secondary"
              >
                {t("savePermissions")}
              </Button>
              <Button
                loading={action === "remove"}
                onClick={() => void run("remove")}
                size="sm"
                type="button"
                variant="danger"
              >
                {t("removeMember")}
              </Button>
            </div>
          ) : null}
          {!member.is_owner &&
          member.user_id !== actorId &&
          !withinActorAuthority ? (
            <p className="text-muted text-xs">{t("memberOutsideAuthority")}</p>
          ) : null}
        </>
      ) : null}
      {error ? (
        <p aria-live="polite" className="text-danger text-sm">
          <ErrorMessage error={error} />
        </p>
      ) : null}
    </article>
  );
}

function InvitationRow({
  invitation,
  onResend,
  onRevoke,
}: {
  invitation: Invitation;
  onResend: (invitationId: string) => Promise<unknown>;
  onRevoke: (invitationId: string) => Promise<unknown>;
}) {
  const t = useTranslations("Projects.collaborators");
  const format = useFormatter();
  const [action, setAction] = React.useState<"resend" | "revoke" | null>(null);
  const [error, setError] = React.useState<unknown>();
  const permissionLabels = (
    [
      ["edit_project", "editProject"],
      ["manage_papers", "managePapers"],
      ["manage_collaborators", "manageCollaborators"],
    ] as const
  )
    .filter(([permission]) => invitation.permissions[permission])
    .map(([, label]) => t(`permissions.${label}`));

  async function run(nextAction: "resend" | "revoke") {
    setError(undefined);
    setAction(nextAction);
    try {
      if (nextAction === "resend") await onResend(invitation.id);
      else await onRevoke(invitation.id);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setAction(null);
    }
  }

  return (
    <article className="border-line grid gap-2 border-t py-4 first:border-t-0 first:pt-0">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <p className="truncate text-sm font-medium">{invitation.email}</p>
        <span
          className={
            invitation.delivery_status === "failed"
              ? "text-danger text-xs font-medium"
              : "text-muted text-xs"
          }
        >
          {t(`delivery.${invitation.delivery_status}`)}
        </span>
      </div>
      <p className="text-muted text-xs">
        {permissionLabels.length > 0
          ? permissionLabels.join(" · ")
          : t("minimumAccess")}
      </p>
      {invitation.delivery_status === "sent" && invitation.delivered_at ? (
        <p className="text-muted text-xs">
          {t("deliveredAt", {
            date: format.dateTime(new Date(invitation.delivered_at), "short"),
          })}
        </p>
      ) : null}
      {invitation.delivery_status === "failed" ? (
        <p className="text-secondary text-sm">{t("deliveryFailedHint")}</p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {invitation.delivery_status !== "pending" ? (
          <Button
            loading={action === "resend"}
            onClick={() => void run("resend")}
            size="sm"
            type="button"
            variant="secondary"
          >
            {t("resend")}
          </Button>
        ) : null}
        <Button
          loading={action === "revoke"}
          onClick={() => void run("revoke")}
          size="sm"
          type="button"
          variant="ghost"
        >
          {t("revoke")}
        </Button>
      </div>
      {error ? (
        <p aria-live="polite" className="text-danger text-sm">
          <ErrorMessage error={error} />
        </p>
      ) : null}
    </article>
  );
}

export function ManageProjectCollaboratorsDialog({
  actorId,
  onOpenChange,
  open,
  project,
}: {
  actorId: number;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  project: Project;
}) {
  const t = useTranslations("Projects.collaborators");
  const queryClient = useQueryClient();
  const membersQuery = useQuery({
    ...projectQueries.members(project.id),
    enabled: open,
  });
  const invitationsQuery = useQuery({
    ...projectQueries.invitations(project.id),
    enabled: open,
  });
  const inviteMutation = useMutation({
    mutationFn: (values: InviteValues) =>
      createProjectInvitation(project.id, values),
  });
  const form = useForm<InviteValues>({
    defaultValues: { email: "", ...emptyPermissions },
    resolver: zodResolver(inviteSchema),
  });
  const permissions = useWatch({
    control: form.control,
    name: ["edit_project", "manage_papers", "manage_collaborators"],
  });
  const actorPermissions = project.membership.permissions;

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: projectKeys.members(project.id),
      }),
      queryClient.invalidateQueries({
        queryKey: projectKeys.invitations(project.id),
      }),
      queryClient.invalidateQueries({
        queryKey: projectKeys.detail(project.id),
      }),
    ]);
  }

  async function submit(values: InviteValues) {
    try {
      await inviteMutation.mutateAsync(values);
      form.reset({ email: "", ...emptyPermissions });
      await refresh();
    } catch (error) {
      form.setError("root", { message: "request", type: "server" });
      form.setError("email", { message: "request", type: "server" });
      throw error;
    }
  }

  const loading = membersQuery.isPending || invitationsQuery.isPending;
  const queryError = membersQuery.error ?? invitationsQuery.error;

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent closeLabel={t("close")} placement="responsive-full">
        <DialogHandle />
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <DialogBody className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.72fr)]">
          <section aria-labelledby="project-members-heading">
            <h2
              className="text-base font-semibold"
              id="project-members-heading"
            >
              {t("members")}
            </h2>
            <div className="mt-4">
              {loading ? (
                <p className="text-muted text-sm">{t("loading")}</p>
              ) : queryError ? (
                <div className="grid gap-3">
                  <p className="text-danger text-sm">
                    <ErrorMessage error={queryError} />
                  </p>
                  <Button
                    className="justify-self-start"
                    onClick={() => {
                      void membersQuery.refetch();
                      void invitationsQuery.refetch();
                    }}
                    size="sm"
                    type="button"
                    variant="secondary"
                  >
                    {t("retry")}
                  </Button>
                </div>
              ) : (
                membersQuery.data?.items.map((member) => (
                  <MemberRow
                    actorId={actorId}
                    actorPermissions={actorPermissions}
                    key={member.user_id}
                    member={member}
                    onRemove={async (userId) => {
                      await removeProjectMember(project.id, userId);
                      await refresh();
                    }}
                    onUpdate={async (userId, nextPermissions) => {
                      await updateProjectMember(
                        project.id,
                        userId,
                        nextPermissions,
                      );
                      await refresh();
                    }}
                  />
                ))
              )}
            </div>
          </section>

          <div className="grid content-start gap-8">
            <section aria-labelledby="invite-collaborator-heading">
              <h2
                className="text-base font-semibold"
                id="invite-collaborator-heading"
              >
                {t("inviteTitle")}
              </h2>
              <form
                className="mt-4 grid gap-4"
                onSubmit={form.handleSubmit(async (values) => {
                  try {
                    await submit(values);
                  } catch {
                    // The typed request error is rendered below.
                  }
                })}
              >
                <Field invalid={Boolean(form.formState.errors.email)}>
                  <FieldLabel>{t("email")}</FieldLabel>
                  <FieldControl>
                    <Input
                      autoComplete="email"
                      inputMode="email"
                      placeholder={t("emailPlaceholder")}
                      type="email"
                      {...form.register("email")}
                    />
                  </FieldControl>
                  {form.formState.errors.email?.type === "invalid_format" ? (
                    <FieldMessage>{t("invalidEmail")}</FieldMessage>
                  ) : null}
                </Field>
                <PermissionFields
                  disabled={{
                    edit_project: !actorPermissions.edit_project,
                    manage_collaborators:
                      !actorPermissions.manage_collaborators,
                    manage_papers: !actorPermissions.manage_papers,
                  }}
                  onChange={(next) => {
                    form.setValue("edit_project", next.edit_project);
                    form.setValue("manage_papers", next.manage_papers);
                    form.setValue(
                      "manage_collaborators",
                      next.manage_collaborators,
                    );
                  }}
                  value={{
                    edit_project: permissions[0],
                    manage_papers: permissions[1],
                    manage_collaborators: permissions[2],
                  }}
                />
                {form.formState.errors.root ? (
                  <p aria-live="polite" className="text-danger text-sm">
                    <ErrorMessage error={inviteMutation.error} />
                  </p>
                ) : null}
                <Button
                  className="justify-self-start"
                  loading={form.formState.isSubmitting}
                  type="submit"
                >
                  {t("sendInvitation")}
                </Button>
              </form>
            </section>

            <section aria-labelledby="pending-invitations-heading">
              <h2
                className="text-base font-semibold"
                id="pending-invitations-heading"
              >
                {t("invitations")}
              </h2>
              <div className="mt-4">
                {invitationsQuery.data?.items.length ? (
                  invitationsQuery.data.items.map((invitation) => (
                    <InvitationRow
                      invitation={invitation}
                      key={invitation.id}
                      onResend={async (invitationId) => {
                        await resendProjectInvitation(project.id, invitationId);
                        await refresh();
                      }}
                      onRevoke={async (invitationId) => {
                        await revokeProjectInvitation(project.id, invitationId);
                        await refresh();
                      }}
                    />
                  ))
                ) : !loading && !queryError ? (
                  <p className="text-muted text-sm">{t("noInvitations")}</p>
                ) : null}
              </div>
            </section>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button
            onClick={() => onOpenChange(false)}
            type="button"
            variant="secondary"
          >
            {t("done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
