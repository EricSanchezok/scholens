"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AsyncBoundary } from "@/components/feedback";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldControl,
  FieldLabel,
  FieldMessage,
  LinkButton,
  PasswordInput,
  Switch,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import {
  IntegrationIcon,
  LinkIcon,
} from "@/design-system/icons/semantic-icons";
import {
  connectIntegration,
  disconnectIntegration,
  integrationKeys,
  integrationQueries,
  setIntegrationEnabled,
  type Integration,
  type IntegrationProvider,
} from "@/features/integrations";
import {
  disconnectZotero,
  ZoteroConnectionControls,
  zoteroKeys,
} from "@/features/zotero";
import {
  SettingsCard,
  SettingsCardBody,
  SettingsPanelHeader,
  SettingsStatus,
} from "./settings-layout";

const credentialSchema = z.object({
  credential: z.string().trim().min(8).max(2048),
});
type CredentialValues = z.infer<typeof credentialSchema>;

const providerLinks: Partial<Record<IntegrationProvider, string>> = {
  mineru: "https://mineru.net/apiManage/token",
  anysearch: "https://www.anysearch.com/",
  tavily: "https://app.tavily.com/home",
  exa: "https://dashboard.exa.ai/api-keys",
  firecrawl: "https://www.firecrawl.dev/app/api-keys",
  openalex: "https://openalex.org/settings/api",
};

function toneForState(state: Integration["state"]) {
  if (state === "connected") return "success" as const;
  if (state === "invalid") return "danger" as const;
  if (state === "connected_unverified") return "warning" as const;
  return "neutral" as const;
}

function CredentialDialog({
  integration,
  open,
  onOpenChange,
}: {
  integration?: Integration;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("Settings");
  const queryClient = useQueryClient();
  const form = useForm<CredentialValues>({
    defaultValues: { credential: "" },
    resolver: zodResolver(credentialSchema),
  });
  React.useEffect(() => {
    if (open) form.reset({ credential: "" });
  }, [form, open]);
  const mutation = useMutation({
    mutationFn: ({ credential }: CredentialValues) => {
      if (!integration) throw new Error("integration_missing");
      return connectIntegration(integration.provider, credential);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: integrationKeys.current(),
      });
      onOpenChange(false);
    },
  });
  if (!integration) return null;
  const link = providerLinks[integration.provider];

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent
        closeLabel={t("actions.close")}
        placement="responsive-bottom"
      >
        <form onSubmit={form.handleSubmit((values) => mutation.mutate(values))}>
          <DialogHeader>
            <DialogTitle>
              {t("connections.connectTitle", {
                provider: t(`connections.provider.${integration.provider}`),
              })}
            </DialogTitle>
            <DialogDescription>
              {t("connections.secretDescription")}
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="grid gap-4">
            <Field invalid={Boolean(form.formState.errors.credential)}>
              <FieldLabel>
                {integration.provider === "openalex"
                  ? t("connections.apiKey")
                  : t("connections.accessToken")}
              </FieldLabel>
              <FieldControl>
                <PasswordInput
                  autoComplete="off"
                  autoFocus
                  hidePasswordLabel={t("connections.hideToken")}
                  placeholder={
                    integration.provider === "openalex"
                      ? t("connections.apiKeyPlaceholder")
                      : t("connections.tokenPlaceholder")
                  }
                  showPasswordLabel={t("connections.showToken")}
                  {...form.register("credential")}
                />
              </FieldControl>
              <FieldMessage>
                {form.formState.errors.credential
                  ? integration.provider === "openalex"
                    ? t("connections.apiKeyError")
                    : t("connections.tokenError")
                  : undefined}
              </FieldMessage>
            </Field>
            {link ? (
              <LinkButton
                href={link}
                rel="noreferrer"
                target="_blank"
                variant="secondary"
              >
                <Icon glyph={LinkIcon} size={16} />
                {integration.provider === "mineru"
                  ? t("connections.getMineruToken")
                  : integration.provider === "openalex"
                    ? t("connections.getOpenAlexKey")
                    : t("connections.getCredential")}
              </LinkButton>
            ) : null}
            {mutation.isError ? (
              <p className="text-danger text-sm" role="alert">
                {integration.provider === "mineru"
                  ? t("connections.mineruSaveError")
                  : t("connections.verifyError")}
              </p>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button
              onClick={() => onOpenChange(false)}
              type="button"
              variant="secondary"
            >
              {t("actions.cancel")}
            </Button>
            <Button loading={mutation.isPending} type="submit">
              {t("connections.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ConnectionsPanel() {
  const t = useTranslations("Settings");
  const queryClient = useQueryClient();
  const integrations = useQuery(integrationQueries.current());
  const [editing, setEditing] = React.useState<Integration>();
  const [disconnecting, setDisconnecting] = React.useState<Integration>();
  const enabledMutation = useMutation({
    mutationFn: ({
      provider,
      enabled,
    }: {
      provider: IntegrationProvider;
      enabled: boolean;
    }) => setIntegrationEnabled(provider, enabled),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: integrationKeys.current(),
      }),
  });
  const disconnectMutation = useMutation({
    mutationFn: (provider: IntegrationProvider) =>
      provider === "zotero"
        ? disconnectZotero()
        : disconnectIntegration(provider),
    onSuccess: () => {
      setDisconnecting(undefined);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: integrationKeys.current() }),
        queryClient.invalidateQueries({ queryKey: zoteroKeys.all }),
      ]);
    },
  });

  return (
    <div>
      <SettingsPanelHeader
        description={t("connections.description")}
        title={t("connections.title")}
      />
      <AsyncBoundary
        data={integrations.data}
        error={integrations.error}
        loading={integrations.isLoading}
        retry={() => void integrations.refetch()}
      >
        {(data) => (
          <SettingsCard>
            <SettingsCardBody>
              <div className="divide-line -m-4 divide-y sm:-m-5">
                {data.items.map((integration) => {
                  const connected = integration.state !== "disconnected";
                  const description = t(
                    `connections.providerDescription.${integration.provider}`,
                  );
                  return (
                    <article
                      className="flex flex-wrap items-center gap-4 px-4 py-4 sm:flex-nowrap sm:px-5"
                      key={integration.provider}
                    >
                      <div className="bg-subtle grid size-10 shrink-0 place-items-center rounded-[var(--radius-lg)]">
                        <Icon
                          glyph={IntegrationIcon}
                          size={20}
                          tone="secondary"
                        />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-semibold">
                            {t(`connections.provider.${integration.provider}`)}
                          </h3>
                          <SettingsStatus
                            tone={toneForState(integration.state)}
                          >
                            {t(`connections.state.${integration.state}`)}
                          </SettingsStatus>
                        </div>
                        <p
                          className="text-secondary mt-1 truncate text-sm leading-5"
                          title={description}
                        >
                          {description}
                        </p>
                      </div>
                      {integration.managed ? (
                        <SettingsStatus
                          tone={integration.enabled ? "success" : "neutral"}
                        >
                          {t("connections.builtIn")}
                        </SettingsStatus>
                      ) : integration.provider === "zotero" ? (
                        <ZoteroConnectionControls
                          connected={connected}
                          onDisconnect={() => setDisconnecting(integration)}
                        />
                      ) : (
                        <div className="flex items-center gap-2">
                          {connected && integration.state !== "invalid" ? (
                            <Switch
                              aria-label={t("connections.toggle", {
                                provider: t(
                                  `connections.provider.${integration.provider}`,
                                ),
                              })}
                              checked={integration.enabled}
                              disabled={enabledMutation.isPending}
                              onCheckedChange={(enabled) =>
                                enabledMutation.mutate({
                                  provider: integration.provider,
                                  enabled,
                                })
                              }
                            />
                          ) : null}
                          <Button
                            onClick={() => setEditing(integration)}
                            size="sm"
                            variant={connected ? "secondary" : "primary"}
                          >
                            {connected
                              ? t("connections.replace")
                              : t("connections.connect")}
                          </Button>
                          {connected ? (
                            <Button
                              onClick={() => setDisconnecting(integration)}
                              size="sm"
                              variant="ghost"
                            >
                              {t("connections.disconnect")}
                            </Button>
                          ) : null}
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            </SettingsCardBody>
          </SettingsCard>
        )}
      </AsyncBoundary>

      <CredentialDialog
        integration={editing}
        onOpenChange={(open) => !open && setEditing(undefined)}
        open={Boolean(editing)}
      />
      <AlertDialog
        onOpenChange={(open) => !open && setDisconnecting(undefined)}
        open={Boolean(disconnecting)}
      >
        <AlertDialogContent>
          <AlertDialogTitle>
            {t("connections.disconnectTitle")}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {disconnecting?.provider === "zotero"
              ? t("connections.zoteroDisconnectDescription")
              : t("connections.disconnectDescription", {
                  provider: disconnecting
                    ? t(`connections.provider.${disconnecting.provider}`)
                    : "",
                })}
          </AlertDialogDescription>
          {disconnectMutation.isError ? (
            <p className="text-danger mt-4 text-sm" role="alert">
              {t("errors.save")}
            </p>
          ) : null}
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialogCancel asChild>
              <Button variant="secondary">{t("actions.cancel")}</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                loading={disconnectMutation.isPending}
                onClick={() =>
                  disconnecting &&
                  disconnectMutation.mutate(disconnecting.provider)
                }
                variant="danger"
              >
                {t("connections.disconnect")}
              </Button>
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
