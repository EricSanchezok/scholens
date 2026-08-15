"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AsyncBoundary } from "@/components/feedback";
import {
  Button,
  Field,
  FieldControl,
  FieldLabel,
  FieldMessage,
  Input,
  LinkButton,
  PasswordInput,
} from "@/components/ui";
import { useAuthSession } from "@/features/authentication";
import {
  changePassword,
  settingsKeys,
  settingsQueries,
  updateProfile,
} from "./api";
import {
  SettingsCard,
  SettingsCardBody,
  SettingsCardHeader,
  SettingsPanelHeader,
  SettingsStatus,
} from "./settings-layout";

const profileSchema = z.object({
  displayName: z.string().trim().min(1).max(120),
});
const passwordSchema = z
  .object({
    currentPassword: z.string().min(1),
    newPassword: z.string().min(12),
    confirmPassword: z.string().min(1),
  })
  .refine((value) => value.newPassword === value.confirmPassword, {
    path: ["confirmPassword"],
    message: "password_mismatch",
  });

type ProfileValues = z.infer<typeof profileSchema>;
type PasswordValues = z.infer<typeof passwordSchema>;

export function AccountPanel({
  accountCenterUrl,
}: {
  accountCenterUrl?: string;
}) {
  const t = useTranslations("Settings");
  const router = useRouter();
  const queryClient = useQueryClient();
  const { signOut } = useAuthSession();
  const profile = useQuery(settingsQueries.profile());
  const plan = useQuery(settingsQueries.usage("current_week"));
  const [signingOut, setSigningOut] = React.useState(false);
  const profileForm = useForm<ProfileValues>({
    defaultValues: { displayName: "" },
    resolver: zodResolver(profileSchema),
  });
  const passwordForm = useForm<PasswordValues>({
    defaultValues: {
      currentPassword: "",
      newPassword: "",
      confirmPassword: "",
    },
    resolver: zodResolver(passwordSchema),
  });

  React.useEffect(() => {
    if (profile.data) {
      profileForm.reset({ displayName: profile.data.display_name ?? "" });
    }
  }, [profile.data, profileForm]);

  const profileMutation = useMutation({
    mutationFn: ({ displayName }: ProfileValues) => updateProfile(displayName),
    onSuccess: (data) => {
      queryClient.setQueryData(settingsKeys.profile(), data);
      profileForm.reset({ displayName: data.display_name ?? "" });
    },
  });
  const passwordMutation = useMutation({
    mutationFn: ({ currentPassword, newPassword }: PasswordValues) =>
      changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    onSuccess: () => passwordForm.reset(),
  });
  async function handleSignOut() {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await signOut();
    } catch {
      // AuthSession clears local credentials even if remote logout is unavailable.
    } finally {
      router.replace("/login");
      setSigningOut(false);
    }
  }

  return (
    <div>
      <SettingsPanelHeader
        description={t("account.description")}
        title={t("account.title")}
      />
      <div className="grid gap-5">
        <AsyncBoundary
          data={profile.data}
          error={profile.error}
          loading={profile.isLoading}
          retry={() => void profile.refetch()}
        >
          {(data) => (
            <SettingsCard>
              <SettingsCardHeader
                description={t("account.profileDescription")}
                title={t("account.profile")}
              />
              <SettingsCardBody>
                <form
                  className="grid max-w-xl gap-4"
                  onSubmit={profileForm.handleSubmit((values) =>
                    profileMutation.mutate(values),
                  )}
                >
                  <Field
                    invalid={Boolean(profileForm.formState.errors.displayName)}
                  >
                    <FieldLabel>{t("account.displayName")}</FieldLabel>
                    <FieldControl>
                      <Input
                        autoComplete="name"
                        {...profileForm.register("displayName")}
                      />
                    </FieldControl>
                    <FieldMessage>
                      {profileForm.formState.errors.displayName
                        ? t("account.displayNameError")
                        : undefined}
                    </FieldMessage>
                  </Field>
                  <Field>
                    <FieldLabel>{t("account.email")}</FieldLabel>
                    <FieldControl>
                      <Input disabled value={data.email} />
                    </FieldControl>
                  </Field>
                  {profileMutation.isError ? (
                    <p className="text-danger text-sm" role="alert">
                      {t("errors.save")}
                    </p>
                  ) : null}
                  <div>
                    <Button
                      disabled={!profileForm.formState.isDirty}
                      loading={profileMutation.isPending}
                      type="submit"
                    >
                      {t("actions.save")}
                    </Button>
                  </div>
                </form>
              </SettingsCardBody>
            </SettingsCard>
          )}
        </AsyncBoundary>

        <AsyncBoundary
          data={plan.data}
          error={plan.error}
          loading={plan.isLoading}
          retry={() => void plan.refetch()}
        >
          {(data) => {
            const planLabel =
              data.plan === "researcher"
                ? t("plan.researcher")
                : data.plan === "basic"
                  ? t("plan.basic")
                  : data.plan;
            return (
              <SettingsCard>
                <SettingsCardHeader
                  action={
                    <SettingsStatus tone="success">{planLabel}</SettingsStatus>
                  }
                  description={t("account.planDescription")}
                  title={t("account.plan")}
                />
              </SettingsCard>
            );
          }}
        </AsyncBoundary>

        <SettingsCard>
          <SettingsCardHeader
            action={
              <SettingsStatus tone="neutral">
                {t("account.unavailable")}
              </SettingsStatus>
            }
            description={t("account.workspaceDescription")}
            title={t("account.workspace")}
          />
          <SettingsCardBody>
            {accountCenterUrl ? (
              <LinkButton
                href={accountCenterUrl}
                rel="noreferrer"
                target="_blank"
                variant="secondary"
              >
                {t("account.openAccountCenter")}
              </LinkButton>
            ) : (
              <Button
                aria-label={`${t("account.openAccountCenter")}. ${t("account.accountCenterUnavailable")}`}
                disabled
                variant="secondary"
              >
                {t("account.openAccountCenter")}
              </Button>
            )}
            {!accountCenterUrl ? (
              <p className="text-secondary mt-2 text-sm">
                {t("account.accountCenterUnavailable")}
              </p>
            ) : null}
          </SettingsCardBody>
        </SettingsCard>

        <SettingsCard>
          <SettingsCardHeader
            description={t("account.passwordDescription")}
            title={t("account.password")}
          />
          <SettingsCardBody>
            <form
              className="grid max-w-xl gap-4"
              onSubmit={passwordForm.handleSubmit((values) =>
                passwordMutation.mutate(values),
              )}
            >
              {(
                ["currentPassword", "newPassword", "confirmPassword"] as const
              ).map((name) => (
                <Field
                  invalid={Boolean(passwordForm.formState.errors[name])}
                  key={name}
                >
                  <FieldLabel>{t(`account.${name}`)}</FieldLabel>
                  <FieldControl>
                    <PasswordInput
                      autoComplete={
                        name === "currentPassword"
                          ? "current-password"
                          : "new-password"
                      }
                      hidePasswordLabel={t("account.hidePassword")}
                      showPasswordLabel={t("account.showPassword")}
                      {...passwordForm.register(name)}
                    />
                  </FieldControl>
                  <FieldMessage>
                    {passwordForm.formState.errors[name]
                      ? t(
                          name === "confirmPassword"
                            ? "account.passwordMismatch"
                            : "account.passwordError",
                        )
                      : undefined}
                  </FieldMessage>
                </Field>
              ))}
              {passwordMutation.isError ? (
                <p className="text-danger text-sm" role="alert">
                  {t("errors.password")}
                </p>
              ) : null}
              {passwordMutation.isSuccess ? (
                <p className="text-success text-sm" role="status">
                  {t("account.passwordUpdated")}
                </p>
              ) : null}
              <div>
                <Button loading={passwordMutation.isPending} type="submit">
                  {t("account.updatePassword")}
                </Button>
              </div>
            </form>
          </SettingsCardBody>
        </SettingsCard>

        <SettingsCard>
          <SettingsCardHeader
            description={t("account.sessionDescription")}
            title={t("account.session")}
          />
          <SettingsCardBody>
            <Button
              loading={signingOut}
              onClick={() => void handleSignOut()}
              variant="secondary"
            >
              {signingOut ? t("account.signingOut") : t("account.signOut")}
            </Button>
          </SettingsCardBody>
        </SettingsCard>
      </div>
    </div>
  );
}
