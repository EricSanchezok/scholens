"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { Button, Switch } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import {
  beginZoteroAuthorization,
  cancelZoteroSync,
  startZoteroSync,
  updateZoteroSyncPreferences,
  zoteroKeys,
  zoteroQueries,
} from "./api";
import {
  zoteroOAuthResultKey,
  zoteroOperationErrorKey,
  zoteroSettingsErrorKey,
} from "./message-keys";
import { buildZoteroReturnPath } from "./oauth-return";

function zoteroErrorCode(error: unknown) {
  return error instanceof ApiError && error.code
    ? error.code
    : "zotero_unavailable";
}

export function ZoteroConnectionControls({
  connected,
  onDisconnect,
}: {
  connected: boolean;
  onDisconnect: () => void;
}) {
  const t = useTranslations("Zotero.settings");
  const operationT = useTranslations("Zotero.operation");
  const oauthT = useTranslations("Zotero.oauth");
  const format = useFormatter();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const status = useQuery({
    ...zoteroQueries.status(),
    enabled: connected,
  });
  const [operationId, setOperationId] = React.useState<string>();
  const [oauthResult] = React.useState(() =>
    searchParams.get("zotero_intent") === "manage"
      ? (searchParams.get("zotero") ?? undefined)
      : undefined,
  );
  const activeSyncId =
    operationId ??
    (status.data?.active_operation_kind === "sync"
      ? (status.data.active_operation_id ?? undefined)
      : undefined);
  const operation = useQuery({
    ...zoteroQueries.operation("sync", activeSyncId ?? "pending"),
    enabled: Boolean(activeSyncId),
  });
  const connect = useMutation({
    mutationFn: async () => {
      const result = await beginZoteroAuthorization(
        "manage",
        buildZoteroReturnPath(
          window.location.pathname,
          window.location.search,
          "manage",
        ),
      );
      window.location.assign(result.auth_url);
    },
  });
  const sync = useMutation({
    mutationFn: startZoteroSync,
    onSuccess: async (result) => {
      setOperationId(result.id);
      queryClient.setQueryData(zoteroKeys.operation("sync", result.id), result);
      await queryClient.invalidateQueries({ queryKey: zoteroKeys.status() });
    },
    onError: async () => {
      await queryClient.invalidateQueries({ queryKey: zoteroKeys.status() });
    },
  });
  const cancel = useMutation({
    mutationFn: () => cancelZoteroSync(activeSyncId ?? ""),
    onSuccess: async (result) => {
      if (activeSyncId) {
        queryClient.setQueryData(
          zoteroKeys.operation("sync", activeSyncId),
          result,
        );
      }
      await queryClient.invalidateQueries({ queryKey: zoteroKeys.status() });
    },
  });
  const preferences = useMutation({
    mutationFn: updateZoteroSyncPreferences,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: zoteroKeys.status() });
    },
  });
  const terminal = operation.data
    ? ["partial", "succeeded", "failed", "cancelled"].includes(
        operation.data.status,
      )
    : false;

  React.useEffect(() => {
    if (!terminal) return;
    void queryClient.invalidateQueries({ queryKey: zoteroKeys.status() });
  }, [queryClient, terminal]);

  React.useEffect(() => {
    const intent = searchParams.get("zotero_intent");
    const result = searchParams.get("zotero");
    if (intent !== "manage" || !result) return;
    void queryClient.invalidateQueries({ queryKey: zoteroKeys.all });
    const next = new URLSearchParams(searchParams.toString());
    next.delete("zotero");
    next.delete("zotero_intent");
    const query = next.toString();
    router.replace(
      (query
        ? `${window.location.pathname}?${query}`
        : window.location.pathname) as Route,
      { scroll: false },
    );
  }, [queryClient, router, searchParams]);

  if (!connected) {
    return (
      <div className="flex flex-col items-start gap-2">
        <Button
          loading={connect.isPending}
          onClick={() => connect.mutate()}
          size="sm"
        >
          {t("connect")}
        </Button>
        {connect.isError ? (
          <p className="text-danger text-sm" role="alert">
            {t(zoteroSettingsErrorKey(zoteroErrorCode(connect.error)))}
          </p>
        ) : null}
        {oauthResult ? (
          <p
            className={
              oauthResult === "connected"
                ? "text-success text-sm"
                : "text-danger text-sm"
            }
            role="status"
          >
            {oauthT(zoteroOAuthResultKey(oauthResult))}
          </p>
        ) : null}
      </div>
    );
  }

  const current = status.data;
  const operationStatus = operation.data?.status;
  const syncing =
    sync.isPending ||
    operationStatus === "queued" ||
    operationStatus === "running";
  const hasActiveOperation = Boolean(current?.active_operation_id);
  const canManageAutoImport = Boolean(
    current?.automatic_sync_eligible || current?.auto_import_enabled,
  );

  return (
    <div className="basis-full pl-14 sm:pl-0">
      {oauthResult ? (
        <p
          className={
            oauthResult === "connected"
              ? "text-success mb-3 text-sm"
              : "text-danger mb-3 text-sm"
          }
          role="status"
        >
          {oauthT(zoteroOAuthResultKey(oauthResult))}
        </p>
      ) : null}
      <div className="border-line grid gap-4 border-t pt-4 sm:grid-cols-[minmax(0,1fr)_auto]">
        <div className="grid gap-2 text-sm">
          {status.isPending ? (
            <p className="text-secondary" role="status">
              {t("loading")}
            </p>
          ) : status.isError ? (
            <p className="text-danger" role="alert">
              {t(zoteroSettingsErrorKey(zoteroErrorCode(status.error)))}
            </p>
          ) : current ? (
            <>
              <p className="text-secondary">
                {current.connected_at
                  ? t("connectedAt", {
                      date: format.dateTime(new Date(current.connected_at), {
                        dateStyle: "medium",
                      }),
                    })
                  : t("connected")}
              </p>
              <p className="text-secondary">
                {current.last_successful_sync_at
                  ? t("lastSync", {
                      date: format.dateTime(
                        new Date(current.last_successful_sync_at),
                        { dateStyle: "medium", timeStyle: "short" },
                      ),
                    })
                  : t("neverSynced")}
              </p>
              {current.connection_state === "invalid" ? (
                <p className="text-danger" role="alert">
                  {t(
                    zoteroSettingsErrorKey(
                      current.last_error_code ?? "zotero_credentials_invalid",
                    ),
                  )}
                </p>
              ) : null}
              <p className="text-secondary">
                {current.automatic_annotation_sync === "active"
                  ? t("automaticAnnotationsActive")
                  : t("manualMode")}
              </p>
              {canManageAutoImport ? (
                <label className="flex min-h-11 max-w-xl items-center justify-between gap-4">
                  <span>
                    <span className="block font-medium">{t("autoImport")}</span>
                    <span className="text-secondary mt-0.5 block text-xs leading-5">
                      {current.auto_import_state === "paused"
                        ? t("autoImportPaused")
                        : t("autoImportDescription")}
                    </span>
                  </span>
                  <Switch
                    aria-label={t("autoImport")}
                    checked={current.auto_import_enabled}
                    disabled={
                      preferences.isPending || !current.automatic_sync_eligible
                    }
                    onCheckedChange={(checked) => preferences.mutate(checked)}
                  />
                </label>
              ) : null}
              {preferences.isError ? (
                <p className="text-danger" role="alert">
                  {t(
                    zoteroSettingsErrorKey(zoteroErrorCode(preferences.error)),
                  )}
                </p>
              ) : null}
              {operation.data ? (
                <div className="grid gap-1">
                  <p
                    className={
                      operation.data.status === "failed"
                        ? "text-danger"
                        : "text-secondary"
                    }
                    role="status"
                  >
                    {t(`operation.${operation.data.status}`)}
                  </p>
                  {["failed", "partial"].includes(operation.data.status) &&
                  operation.data.error_code ? (
                    <p className="text-danger" role="alert">
                      {operationT(
                        zoteroOperationErrorKey(operation.data.error_code),
                      )}
                    </p>
                  ) : null}
                </div>
              ) : null}
              {current.active_operation_kind === "import" ? (
                <p className="text-secondary" role="status">
                  {t("operation.importActive")}
                </p>
              ) : null}
            </>
          ) : null}
        </div>
        <div className="flex flex-wrap items-start gap-2">
          <Button
            disabled={
              current?.connection_state === "invalid" || hasActiveOperation
            }
            loading={syncing}
            onClick={() => sync.mutate()}
            size="sm"
            variant="secondary"
          >
            {t("syncNow")}
          </Button>
          {activeSyncId && !terminal ? (
            <Button
              loading={cancel.isPending}
              onClick={() => cancel.mutate()}
              size="sm"
              variant="ghost"
            >
              {t("cancelSync")}
            </Button>
          ) : null}
          <Button onClick={onDisconnect} size="sm" variant="ghost">
            {t("disconnect")}
          </Button>
        </div>
      </div>
      {sync.isError || operation.isError || cancel.isError ? (
        <p className="text-danger mt-2 text-sm" role="alert">
          {t(
            zoteroSettingsErrorKey(
              zoteroErrorCode(sync.error ?? operation.error ?? cancel.error),
            ),
          )}
        </p>
      ) : null}
    </div>
  );
}
