"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import * as React from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { AsyncBoundary, CopyActionButton } from "@/components/feedback";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  Button,
  Checkbox,
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
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import {
  createAccessKey,
  revokeAccessKey,
  settingsKeys,
  settingsQueries,
  updateAccessKey,
  type AccessKey,
} from "./api";
import {
  SettingsCard,
  SettingsCardBody,
  SettingsPanelHeader,
  SettingsStatus,
} from "./settings-layout";

const permissions = ["read", "write", "manage", "delete"] as const;
const accessKeySchema = z.object({
  name: z.string().trim().min(1).max(120),
  expiration: z.enum(["7_days", "30_days", "90_days", "never"]),
  permissions: z.array(z.enum(permissions)).min(1),
});
type AccessKeyValues = z.infer<typeof accessKeySchema>;

function AccessKeyFormDialog({
  accessKey,
  open,
  onOpenChange,
}: {
  accessKey?: AccessKey;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("Settings");
  const queryClient = useQueryClient();
  const [createdSecret, setCreatedSecret] = React.useState<string>();
  const form = useForm<AccessKeyValues>({
    defaultValues: {
      name: accessKey?.name ?? "",
      expiration: "30_days",
      permissions: accessKey?.permissions ?? ["read"],
    },
    resolver: zodResolver(accessKeySchema),
  });
  const selectedPermissions =
    useWatch({ control: form.control, name: "permissions" }) ?? [];
  const expiration =
    useWatch({ control: form.control, name: "expiration" }) ?? "30_days";
  const mutation = useMutation({
    mutationFn: async (values: AccessKeyValues) => {
      if (accessKey) {
        return {
          kind: "updated" as const,
          accessKey: await updateAccessKey(accessKey.id, {
            name: values.name,
            permissions: values.permissions,
          }),
        };
      }
      return {
        kind: "created" as const,
        result: await createAccessKey(values),
      };
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({
        queryKey: settingsKeys.accessKeys(),
      });
      if (result.kind === "created") setCreatedSecret(result.result.secret);
      else onOpenChange(false);
    },
  });

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent
        closeLabel={t("actions.close")}
        placement="responsive-bottom"
      >
        <DialogHeader>
          <DialogTitle>
            {createdSecret
              ? t("accessKeys.secretTitle")
              : accessKey
                ? t("accessKeys.editTitle")
                : t("accessKeys.createTitle")}
          </DialogTitle>
          <DialogDescription>
            {createdSecret
              ? t("accessKeys.secretDescription")
              : t("accessKeys.formDescription")}
          </DialogDescription>
        </DialogHeader>
        {createdSecret ? (
          <>
            <DialogBody>
              <div className="border-line bg-subtle flex items-center gap-2 rounded-[var(--radius-md)] border p-3">
                <code className="min-w-0 flex-1 text-sm break-all">
                  {createdSecret}
                </code>
                <CopyActionButton
                  errorLabel={t("accessKeys.copyError")}
                  label={t("accessKeys.copy")}
                  pendingLabel={t("accessKeys.copying")}
                  successLabel={t("accessKeys.copied")}
                  value={createdSecret}
                />
              </div>
            </DialogBody>
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>
                {t("accessKeys.done")}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <form
            onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          >
            <DialogBody className="grid gap-5">
              <Field invalid={Boolean(form.formState.errors.name)}>
                <FieldLabel>{t("accessKeys.name")}</FieldLabel>
                <FieldControl>
                  <Input autoFocus {...form.register("name")} />
                </FieldControl>
                <FieldMessage>
                  {form.formState.errors.name
                    ? t("accessKeys.nameError")
                    : undefined}
                </FieldMessage>
              </Field>
              {!accessKey ? (
                <Field>
                  <FieldLabel>{t("accessKeys.expiration")}</FieldLabel>
                  <Select
                    onValueChange={(value) =>
                      form.setValue(
                        "expiration",
                        value as AccessKeyValues["expiration"],
                      )
                    }
                    value={expiration}
                  >
                    <FieldControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FieldControl>
                    <SelectContent>
                      {(["7_days", "30_days", "90_days", "never"] as const).map(
                        (value) => (
                          <SelectItem key={value} value={value}>
                            {t(`accessKeys.expirations.${value}`)}
                          </SelectItem>
                        ),
                      )}
                    </SelectContent>
                  </Select>
                </Field>
              ) : null}
              <Field invalid={Boolean(form.formState.errors.permissions)}>
                <FieldLabel>{t("accessKeys.permissions")}</FieldLabel>
                <div className="grid gap-2">
                  {permissions.map((permission) => {
                    return (
                      <label
                        className="border-line hover:bg-hover flex min-h-11 items-center gap-3 rounded-[var(--radius-md)] border px-3 text-sm"
                        key={permission}
                      >
                        <Checkbox
                          checked={selectedPermissions.includes(permission)}
                          onCheckedChange={(checked) =>
                            form.setValue(
                              "permissions",
                              checked
                                ? [...selectedPermissions, permission]
                                : selectedPermissions.filter(
                                    (item) => item !== permission,
                                  ),
                              { shouldValidate: true },
                            )
                          }
                        />
                        {t(`accessKeys.permission.${permission}`)}
                      </label>
                    );
                  })}
                </div>
                <FieldMessage>
                  {form.formState.errors.permissions
                    ? t("accessKeys.permissionError")
                    : undefined}
                </FieldMessage>
              </Field>
              {mutation.isError ? (
                <p className="text-danger text-sm" role="alert">
                  {t("errors.save")}
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
                {accessKey ? t("actions.save") : t("accessKeys.create")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function AccessKeysPanel() {
  const t = useTranslations("Settings");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const keys = useQuery(settingsQueries.accessKeys());
  const [formKey, setFormKey] = React.useState<AccessKey | null | undefined>();
  const [revoking, setRevoking] = React.useState<AccessKey>();
  const revoke = useMutation({
    mutationFn: revokeAccessKey,
    onSuccess: () => {
      setRevoking(undefined);
      void queryClient.invalidateQueries({
        queryKey: settingsKeys.accessKeys(),
      });
    },
  });

  return (
    <div>
      <SettingsPanelHeader
        description={t("accessKeys.description")}
        title={t("accessKeys.title")}
      />
      <div className="mb-4 flex justify-end">
        <Button onClick={() => setFormKey(null)}>
          {t("accessKeys.create")}
        </Button>
      </div>
      <AsyncBoundary
        data={keys.data}
        empty={(data) => data.items.length === 0}
        error={keys.error}
        loading={keys.isLoading}
        retry={() => void keys.refetch()}
      >
        {(data) => (
          <SettingsCard>
            <SettingsCardBody>
              <div className="divide-line -m-4 divide-y sm:-m-5">
                {data.items.map((key) => (
                  <div
                    className="flex flex-wrap items-center gap-4 px-4 py-4 sm:px-5"
                    key={key.id}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <h3 className="truncate text-sm font-semibold">
                          {key.name}
                        </h3>
                        <SettingsStatus
                          tone={key.status === "active" ? "success" : "neutral"}
                        >
                          {t(`accessKeys.status.${key.status}`)}
                        </SettingsStatus>
                      </div>
                      <p className="text-secondary mt-1 text-xs leading-5">
                        {key.key_prefix}… ·{" "}
                        {key.permissions
                          .map((value) => t(`accessKeys.permission.${value}`))
                          .join(", ")}
                      </p>
                      <p className="text-secondary text-xs leading-5">
                        {t("accessKeys.created", {
                          date: format.dateTime(
                            new Date(key.created_at),
                            "short",
                          ),
                        })}
                      </p>
                    </div>
                    {key.status === "active" ? (
                      <div className="flex gap-2">
                        <Button
                          onClick={() => setFormKey(key)}
                          size="sm"
                          variant="secondary"
                        >
                          {t("actions.edit")}
                        </Button>
                        <Button
                          onClick={() => setRevoking(key)}
                          size="sm"
                          variant="ghost"
                        >
                          {t("accessKeys.revoke")}
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </SettingsCardBody>
          </SettingsCard>
        )}
      </AsyncBoundary>

      {formKey !== undefined ? (
        <AccessKeyFormDialog
          accessKey={formKey ?? undefined}
          key={formKey?.id ?? "create"}
          onOpenChange={(open) => !open && setFormKey(undefined)}
          open
        />
      ) : null}
      <AlertDialog
        onOpenChange={(open) => !open && setRevoking(undefined)}
        open={Boolean(revoking)}
      >
        <AlertDialogContent>
          <AlertDialogTitle>{t("accessKeys.revokeTitle")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t("accessKeys.revokeDescription", { name: revoking?.name ?? "" })}
          </AlertDialogDescription>
          {revoke.isError ? (
            <p className="text-danger mt-4 text-sm">{t("errors.save")}</p>
          ) : null}
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialogCancel asChild>
              <Button variant="secondary">{t("actions.cancel")}</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                loading={revoke.isPending}
                onClick={() => revoking && revoke.mutate(revoking.id)}
                variant="danger"
              >
                {t("accessKeys.revoke")}
              </Button>
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
