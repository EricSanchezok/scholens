"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import type { components } from "@/lib/api/generated/schema";
import { ApiError } from "@/lib/api/errors";
import {
  cancelPaperIngestion,
  libraryKeys,
  retryPaperIngestion,
  uploadPaperFile,
  uploadPaperSource,
} from "./api";

type Ingestion = components["schemas"]["LibraryPaperIngestionResponse"];
type LibraryEntry =
  components["schemas"]["LibraryPaperListResponse"]["items"][number];
type Source = components["schemas"]["UploadFromSourceRequest"]["source"];

export type PreparedPaperUpload = {
  contentDigest: string;
  file: File;
  id: string;
  idempotencyKey: string;
};

export type PaperIngestionRow = {
  createdAt: string;
  displayName: string;
  errorCode?: string;
  id: string;
  requiredIntegration?: "mineru";
  retryable: boolean;
  sourceKind: "upload" | "doi" | "arxiv" | "url";
  stage:
    | "uploading"
    | "queued"
    | "downloading"
    | "parsing"
    | "extracting_metadata"
    | "indexing"
    | "finalizing";
  state:
    | "uploading"
    | "queued"
    | "processing"
    | "failed"
    | "retrying"
    | "cancelling";
};

type LocalUpload = PaperIngestionRow & {
  file: File;
  idempotencyKey: string;
};

const MAX_CONCURRENT_UPLOADS = 3;
const CANCELLATION_RECONCILIATION_TIMEOUT_MS = 8_000;

async function runWithConcurrency<T>(
  values: T[],
  worker: (value: T) => Promise<void>,
) {
  let nextIndex = 0;
  await Promise.all(
    Array.from(
      { length: Math.min(MAX_CONCURRENT_UPLOADS, values.length) },
      async () => {
        while (nextIndex < values.length) {
          const value = values[nextIndex];
          nextIndex += 1;
          if (value !== undefined) await worker(value);
        }
      },
    ),
  );
}

function errorCode(error: unknown) {
  if (error instanceof ApiError) return error.code ?? "service_unavailable";
  return "connection_failed";
}

function serverRow(ingestion: Ingestion): PaperIngestionRow {
  return {
    createdAt: ingestion.created_at,
    displayName: ingestion.display_name,
    errorCode: ingestion.failure?.code ?? undefined,
    id: ingestion.id,
    requiredIntegration: ingestion.failure?.required_integration ?? undefined,
    retryable: ingestion.failure?.retryable ?? true,
    sourceKind: ingestion.source_kind,
    stage: ingestion.stage,
    state: ingestion.state,
  };
}

export function usePaperIngestions(
  entries: LibraryEntry[],
  { onWillIngest }: { onWillIngest?: () => void } = {},
) {
  const queryClient = useQueryClient();
  const [localUploads, setLocalUploads] = React.useState<LocalUpload[]>([]);
  const [optimistic, setOptimistic] = React.useState<Ingestion[]>([]);
  const [cancellingIds, setCancellingIds] = React.useState<Set<string>>(
    () => new Set(),
  );
  const [retryingIds, setRetryingIds] = React.useState<Set<string>>(
    () => new Set(),
  );
  const uploadControllers = React.useRef(new Map<string, AbortController>());
  const cancelledLocalIds = React.useRef(new Set<string>());
  const retryKeys = React.useRef(new Map<string, string>());

  const refresh = React.useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: [...libraryKeys.all, "papers"],
      }),
      queryClient.invalidateQueries({ queryKey: libraryKeys.summary() }),
    ]);
  }, [queryClient]);

  const addOptimistic = React.useCallback((ingestion: Ingestion) => {
    setOptimistic((current) => [
      ingestion,
      ...current.filter((item) => item.id !== ingestion.id),
    ]);
  }, []);

  const reconcileCancelledUpload = React.useCallback(
    async (item: LocalUpload) => {
      const controller = new AbortController();
      const timeout = window.setTimeout(
        () => controller.abort(),
        CANCELLATION_RECONCILIATION_TIMEOUT_MS,
      );
      try {
        const accepted = await uploadPaperFile(item.file, {
          idempotencyKey: item.idempotencyKey,
          signal: controller.signal,
        });
        await cancelPaperIngestion(accepted.id, controller.signal);
        await refresh();
      } catch {
        // Aborting a request cannot prove whether the server committed it.
        // Replay the same idempotency key once, within a bounded window. If
        // connectivity is still unavailable, the canonical list will expose
        // any accepted ingestion so it can be cancelled there.
      } finally {
        window.clearTimeout(timeout);
        cancelledLocalIds.current.delete(item.id);
      }
    },
    [refresh],
  );

  const reconcileCancelledSource = React.useCallback(
    async ({
      idempotencyKey,
      source,
    }: {
      idempotencyKey: string;
      source: Source;
    }) => {
      const controller = new AbortController();
      const timeout = window.setTimeout(
        () => controller.abort(),
        CANCELLATION_RECONCILIATION_TIMEOUT_MS,
      );
      try {
        const accepted = await uploadPaperSource(source, {
          idempotencyKey,
          signal: controller.signal,
        });
        await cancelPaperIngestion(accepted.id, controller.signal);
        await refresh();
      } catch {
        // See reconcileCancelledUpload: a later canonical-list refresh is the
        // fallback when the network remains unavailable.
      } finally {
        window.clearTimeout(timeout);
      }
    },
    [refresh],
  );

  React.useEffect(() => {
    const serverIds = new Set(
      entries.flatMap((entry) =>
        entry.entry_type === "ingestion" ? [entry.ingestion.id] : [],
      ),
    );
    const documentIds = new Set(
      entries.flatMap((entry) =>
        entry.entry_type === "paper" ? [entry.document.document_id] : [],
      ),
    );
    setOptimistic((current) => {
      const next = current.filter(
        (item) =>
          !serverIds.has(item.id) &&
          !(item.document_id && documentIds.has(item.document_id)),
      );
      return next.length === current.length ? current : next;
    });
  }, [entries]);

  const uploadOne = React.useCallback(
    async (item: LocalUpload) => {
      if (cancelledLocalIds.current.has(item.id)) {
        cancelledLocalIds.current.delete(item.id);
        return;
      }
      const controller = new AbortController();
      uploadControllers.current.set(item.id, controller);
      setLocalUploads((current) =>
        current.map((candidate) =>
          candidate.id === item.id
            ? { ...candidate, errorCode: undefined, state: "uploading" }
            : candidate,
        ),
      );
      try {
        const accepted = await uploadPaperFile(item.file, {
          idempotencyKey: item.idempotencyKey,
          signal: controller.signal,
        });
        if (cancelledLocalIds.current.has(item.id)) {
          try {
            await cancelPaperIngestion(accepted.id);
            cancelledLocalIds.current.delete(item.id);
          } catch {
            void reconcileCancelledUpload(item);
          }
        } else {
          addOptimistic(accepted);
        }
        setLocalUploads((current) =>
          current.filter((candidate) => candidate.id !== item.id),
        );
        await refresh();
      } catch (error) {
        if (cancelledLocalIds.current.has(item.id)) {
          void reconcileCancelledUpload(item);
          return;
        }
        setLocalUploads((current) =>
          current.map((candidate) =>
            candidate.id === item.id
              ? { ...candidate, errorCode: errorCode(error), state: "failed" }
              : candidate,
          ),
        );
      } finally {
        uploadControllers.current.delete(item.id);
      }
    },
    [addOptimistic, reconcileCancelledUpload, refresh],
  );

  const startUploads = React.useCallback(
    (uploads: PreparedPaperUpload[]) => {
      const seenDigests = new Set<string>();
      const distinctUploads = uploads.filter((upload) => {
        if (seenDigests.has(upload.contentDigest)) return false;
        seenDigests.add(upload.contentDigest);
        return true;
      });
      if (distinctUploads.length === 0) return;
      onWillIngest?.();
      const createdAt = new Date().toISOString();
      const next: LocalUpload[] = distinctUploads.map((upload, index) => ({
        createdAt,
        displayName: upload.file.name,
        file: upload.file,
        id: upload.id,
        idempotencyKey: upload.idempotencyKey,
        sourceKind: "upload",
        retryable: true,
        stage: index < MAX_CONCURRENT_UPLOADS ? "uploading" : "queued",
        state: index < MAX_CONCURRENT_UPLOADS ? "uploading" : "queued",
      }));
      setLocalUploads((current) => [...next, ...current]);
      void runWithConcurrency(next, uploadOne);
    },
    [onWillIngest, uploadOne],
  );

  const retry = React.useCallback(
    async (id: string) => {
      setRetryingIds((current) => new Set(current).add(id));
      try {
        const local = localUploads.find((item) => item.id === id);
        if (local) {
          await uploadOne(local);
          return;
        }
        const key = retryKeys.current.get(id) ?? crypto.randomUUID();
        retryKeys.current.set(id, key);
        const accepted = await retryPaperIngestion(id, key);
        addOptimistic(accepted);
        retryKeys.current.delete(id);
        await refresh();
      } finally {
        setRetryingIds((current) => {
          const next = new Set(current);
          next.delete(id);
          return next;
        });
      }
    },
    [addOptimistic, localUploads, refresh, uploadOne],
  );

  const cancel = React.useCallback(
    async (id: string) => {
      const local = localUploads.find((item) => item.id === id);
      if (local) {
        cancelledLocalIds.current.add(id);
        setLocalUploads((current) => current.filter((item) => item.id !== id));
        const controller = uploadControllers.current.get(id);
        if (controller) controller.abort();
        else if (
          local.state === "failed" &&
          local.errorCode === "connection_failed"
        ) {
          void reconcileCancelledUpload(local);
        }
        return;
      }
      setCancellingIds((current) => new Set(current).add(id));
      try {
        await cancelPaperIngestion(id);
        setOptimistic((current) => current.filter((item) => item.id !== id));
        await refresh();
      } finally {
        setCancellingIds((current) => {
          const next = new Set(current);
          next.delete(id);
          return next;
        });
      }
    },
    [localUploads, reconcileCancelledUpload, refresh],
  );

  const submitSource = React.useCallback(
    async ({
      idempotencyKey,
      signal,
      source,
    }: {
      idempotencyKey: string;
      signal: AbortSignal;
      source: Source;
    }) => {
      onWillIngest?.();
      let acceptedAfterCancellation = false;
      try {
        const accepted = await uploadPaperSource(source, {
          idempotencyKey,
          signal,
        });
        if (signal.aborted) {
          acceptedAfterCancellation = true;
          await cancelPaperIngestion(accepted.id);
          await refresh();
          throw new DOMException("Aborted", "AbortError");
        }
        addOptimistic(accepted);
        await refresh();
        return accepted;
      } catch (error) {
        if (signal.aborted && !acceptedAfterCancellation) {
          void reconcileCancelledSource({ idempotencyKey, source });
        }
        throw error;
      }
    },
    [addOptimistic, onWillIngest, reconcileCancelledSource, refresh],
  );

  const rows = React.useMemo(() => {
    const server = entries.flatMap((entry) =>
      entry.entry_type === "ingestion" ? [entry.ingestion] : [],
    );
    const serverIds = new Set(server.map((item) => item.id));
    const combined = [
      ...localUploads,
      ...optimistic.filter((item) => !serverIds.has(item.id)).map(serverRow),
      ...server.map(serverRow),
    ];
    return combined.map((row) => {
      if (cancellingIds.has(row.id)) {
        return { ...row, state: "cancelling" as const };
      }
      if (retryingIds.has(row.id)) {
        return { ...row, state: "retrying" as const };
      }
      return row;
    });
  }, [cancellingIds, entries, localUploads, optimistic, retryingIds]);

  React.useEffect(
    () => () => {
      uploadControllers.current.forEach((controller) => controller.abort());
    },
    [],
  );

  return { cancel, retry, rows, startUploads, submitSource };
}
