"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
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
    const error = connect.isError
      ? t(zoteroSettingsErrorKey(zoteroErrorCode(connect.error)))
      : oauthResult && oauthResult !== "connected"
        ? oauthT(zoteroOAuthResultKey(oauthResult))
        : undefined;

    return (
      <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 sm:flex-nowrap">
        {error ? (
          <p
            className="text-danger max-w-40 truncate text-xs"
            role="alert"
            title={error}
          >
            {error}
          </p>
        ) : null}
        <Button
          loading={connect.isPending}
          onClick={() => connect.mutate()}
          size="sm"
        >
          {t("connect")}
        </Button>
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
  const invalid = current?.connection_state === "invalid";
  const requestError = sync.error ?? operation.error ?? cancel.error;
  const feedback = (() => {
    if (connect.isError) {
      return {
        message: t(zoteroSettingsErrorKey(zoteroErrorCode(connect.error))),
        tone: "danger" as const,
      };
    }
    if (status.isError) {
      return {
        message: t(zoteroSettingsErrorKey(zoteroErrorCode(status.error))),
        tone: "danger" as const,
      };
    }
    if (invalid) {
      return {
        message: t(
          zoteroSettingsErrorKey(
            current?.last_error_code ?? "zotero_credentials_invalid",
          ),
        ),
        tone: "danger" as const,
      };
    }
    if (preferences.isError) {
      return {
        message: t(zoteroSettingsErrorKey(zoteroErrorCode(preferences.error))),
        tone: "danger" as const,
      };
    }
    if (requestError) {
      return {
        message: t(zoteroSettingsErrorKey(zoteroErrorCode(requestError))),
        tone: "danger" as const,
      };
    }
    if (
      operation.data &&
      ["failed", "partial"].includes(operation.data.status) &&
      operation.data.error_code
    ) {
      return {
        message: operationT(zoteroOperationErrorKey(operation.data.error_code)),
        tone: "danger" as const,
      };
    }
    if (current?.active_operation_kind === "import") {
      return {
        message: t("operation.importActive"),
        tone: "neutral" as const,
      };
    }
    if (operation.data) {
      return {
        message: t(`operation.${operation.data.status}`),
        tone:
          operation.data.status === "failed"
            ? ("danger" as const)
            : ("neutral" as const),
      };
    }
    if (oauthResult === "connected") {
      return {
        message: oauthT(zoteroOAuthResultKey(oauthResult)),
        tone: "success" as const,
      };
    }
    return undefined;
  })();

  return (
    <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 sm:flex-nowrap">
      {feedback ? (
        <p
          className={`max-w-40 truncate text-xs ${
            feedback.tone === "danger"
              ? "text-danger"
              : feedback.tone === "success"
                ? "text-success"
                : "text-secondary"
          }`}
          role={feedback.tone === "danger" ? "alert" : "status"}
          title={feedback.message}
        >
          {feedback.message}
        </p>
      ) : null}
      {!invalid && canManageAutoImport && current ? (
        <label
          className="flex min-h-9 items-center gap-2"
          title={
            current.auto_import_state === "paused"
              ? t("autoImportPaused")
              : undefined
          }
        >
          <span className="text-secondary hidden text-xs whitespace-nowrap sm:inline">
            {t("autoImportShort")}
          </span>
          <Switch
            aria-label={t("autoImport")}
            checked={current.auto_import_enabled}
            disabled={preferences.isPending || !current.automatic_sync_eligible}
            onCheckedChange={(checked) => preferences.mutate(checked)}
          />
        </label>
      ) : null}
      {invalid ? (
        <Button
          loading={connect.isPending}
          onClick={() => connect.mutate()}
          size="sm"
          variant="secondary"
        >
          {t("reconnect")}
        </Button>
      ) : activeSyncId && !terminal ? (
        <Button
          loading={cancel.isPending}
          onClick={() => cancel.mutate()}
          size="sm"
          variant="secondary"
        >
          {t("cancelSync")}
        </Button>
      ) : (
        <Button
          disabled={!current || hasActiveOperation}
          loading={status.isPending || syncing}
          onClick={() => sync.mutate()}
          size="sm"
          variant="secondary"
        >
          {t("syncNow")}
        </Button>
      )}
      <Button onClick={onDisconnect} size="sm" variant="ghost">
        {t("disconnect")}
      </Button>
    </div>
  );
}
