"use client";

import {
  LinkIcon,
  DocumentIcon,
  UploadIcon,
  WarningIcon,
  DismissIcon,
  IntegrationIcon,
} from "@/design-system/icons/semantic-icons";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";

import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHandle,
  DialogHeader,
  DialogTitle,
  Field,
  FieldControl,
  FieldLabel,
  FieldMessage,
  IconButton,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { ApiError } from "@/lib/api/errors";
import type { KnownPaperSource } from "../api";
import type { PreparedPaperUpload } from "../use-paper-ingestions";

type SourceKind = KnownPaperSource["kind"];

type QueuedFile = PreparedPaperUpload & { errorCode?: "fileTooLarge" };
type SourceError = { connectOpenAlex: boolean; message: string };

const MAX_FILE_BYTES = 30 * 1024 * 1024;

async function fileContentDigest(file: File) {
  if (file.size > MAX_FILE_BYTES) {
    return `oversize:${file.name}:${file.size}:${file.lastModified}`;
  }
  const digest = await crypto.subtle.digest(
    "SHA-256",
    await file.arrayBuffer(),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

const sourceSchema = z.object({
  sourceKind: z.enum(["doi", "arxiv", "url"]),
  sourceValue: z.string().trim().min(1),
});
type SourceForm = z.infer<typeof sourceSchema>;

export function AddPapersDialog({
  onBrowseZotero,
  onOpenChange,
  onConnectOpenAlex,
  onSubmitSource,
  onUploadFiles,
  open,
}: {
  onBrowseZotero: () => void;
  onOpenChange: (open: boolean) => void;
  onConnectOpenAlex: () => void;
  onSubmitSource: (input: {
    idempotencyKey: string;
    signal: AbortSignal;
    source: KnownPaperSource;
  }) => Promise<unknown>;
  onUploadFiles: (files: PreparedPaperUpload[]) => void;
  open: boolean;
}) {
  const t = useTranslations("Library.addPapers");
  const [queue, setQueue] = React.useState<QueuedFile[]>([]);
  const [filesChecking, setFilesChecking] = React.useState(false);
  const [duplicateCount, setDuplicateCount] = React.useState(0);
  const [sourcePending, setSourcePending] = React.useState(false);
  const [sourceError, setSourceError] = React.useState<SourceError>();
  const [sourceController, setSourceController] = React.useState<
    AbortController | undefined
  >();
  const [sourceKey, setSourceKey] = React.useState<string>();
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const queuedDigests = React.useRef(new Set<string>());
  const form = useForm<SourceForm>({
    defaultValues: { sourceKind: "doi", sourceValue: "" },
    resolver: zodResolver(sourceSchema),
  });
  const sourceKind =
    useWatch({ control: form.control, name: "sourceKind" }) ?? "doi";

  async function enqueue(files: File[]) {
    setDuplicateCount(0);
    setFilesChecking(true);
    try {
      const candidates = await Promise.all(
        files.map(async (file) => ({
          contentDigest: await fileContentDigest(file),
          file,
        })),
      );
      const accepted: QueuedFile[] = [];
      let duplicates = 0;
      for (const candidate of candidates) {
        if (queuedDigests.current.has(candidate.contentDigest)) {
          duplicates += 1;
          continue;
        }
        queuedDigests.current.add(candidate.contentDigest);
        accepted.push({
          ...candidate,
          errorCode:
            candidate.file.size > MAX_FILE_BYTES ? "fileTooLarge" : undefined,
          id: crypto.randomUUID(),
          idempotencyKey: crypto.randomUUID(),
        });
      }
      if (accepted.length > 0) {
        setQueue((items) => [...items, ...accepted]);
      }
      setDuplicateCount(duplicates);
    } finally {
      setFilesChecking(false);
    }
  }

  function removeQueuedFile(id: string) {
    setDuplicateCount(0);
    setQueue((items) => {
      const removed = items.find((item) => item.id === id);
      if (removed) queuedDigests.current.delete(removed.contentDigest);
      return items.filter((item) => item.id !== id);
    });
  }

  function submitFiles() {
    const valid = queue.filter((item) => !item.errorCode);
    if (valid.length === 0) return;
    const invalid = queue.filter((item) => item.errorCode);
    onUploadFiles(valid);
    valid.forEach((item) => queuedDigests.current.delete(item.contentDigest));
    setDuplicateCount(0);
    setQueue(invalid);
    if (invalid.length === 0) onOpenChange(false);
  }

  function sourceErrorMessage(error: unknown) {
    const code = error instanceof ApiError ? error.code : "connection_failed";
    if (code === "openalex_credential_required") {
      return {
        connectOpenAlex: true,
        message: t("errors.openAlexRequired"),
      };
    }
    if (code === "openalex_credential_invalid") {
      return {
        connectOpenAlex: true,
        message: t("errors.openAlexInvalid"),
      };
    }
    let message: string;
    switch (code) {
      case "paper_source_pdf_unavailable":
        message = t("errors.unavailable");
        break;
      case "paper_source_unsafe_address":
        message = t("errors.unsafeAddress");
        break;
      case "document_already_in_library":
      case "document_already_in_project":
        message = t("errors.alreadyInCollection");
        break;
      case "document_upload_in_progress":
        message = t("errors.uploadInProgress");
        break;
      case "upload_too_large":
        message = t("errors.tooLarge");
        break;
      case "invalid_pdf":
      case "pdf_encrypted":
        message = t("errors.invalidPdf");
        break;
      case "upload_quota_exceeded":
      case "paper_upload_quota_exceeded":
      case "paper_quota_exceeded":
      case "storage_quota_exceeded":
      case "project_owner_quota_exceeded":
      case "project_paper_quota_exceeded":
        message = t("errors.quota");
        break;
      case "openalex_rate_limited":
        message = t("errors.openAlexRateLimited");
        break;
      case "openalex_unavailable":
        message = t("errors.openAlexUnavailable");
        break;
      case "connection_failed":
      case "jobs_submission_failed":
      case "service_unavailable":
        message = t("errors.serviceUnavailable");
        break;
      default:
        message = t("sourceFailed");
    }
    return { connectOpenAlex: false, message };
  }

  async function submitSource(values: SourceForm) {
    const controller = new AbortController();
    const idempotencyKey = sourceKey ?? crypto.randomUUID();
    setSourceController(controller);
    setSourceKey(idempotencyKey);
    setSourcePending(true);
    setSourceError(undefined);
    try {
      await onSubmitSource({
        idempotencyKey,
        signal: controller.signal,
        source: { kind: values.sourceKind, value: values.sourceValue },
      });
      setSourceKey(undefined);
      form.reset({ ...values, sourceValue: "" });
      onOpenChange(false);
    } catch (error) {
      if (!controller.signal.aborted) setSourceError(sourceErrorMessage(error));
    } finally {
      setSourceController((current) =>
        current === controller ? undefined : current,
      );
      setSourcePending(false);
    }
  }

  function cancelSource() {
    sourceController?.abort();
    setSourceController(undefined);
    setSourceKey(undefined);
    setSourcePending(false);
  }

  React.useEffect(() => {
    return () => sourceController?.abort();
  }, [sourceController]);

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      cancelSource();
      setDuplicateCount(0);
    }
    onOpenChange(nextOpen);
  }

  const waitingCount = queue.filter((item) => !item.errorCode).length;

  return (
    <Dialog onOpenChange={handleOpenChange} open={open}>
      <DialogContent
        className="lg:max-w-2xl"
        closeLabel={t("close")}
        placement="responsive-bottom"
      >
        <DialogHandle />
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <section className="grid gap-3">
            <div>
              <h3 className="text-sm font-semibold">{t("zoteroTitle")}</h3>
              <p className="text-secondary mt-1 text-sm">
                {t("zoteroDescription")}
              </p>
            </div>
            <Button
              className="justify-self-start"
              onClick={() => {
                onOpenChange(false);
                onBrowseZotero();
              }}
              variant="secondary"
            >
              <Icon glyph={IntegrationIcon} size={20} />
              {t("browseZotero")}
            </Button>
          </section>

          <div className="border-line my-6 border-t" />

          <section className="grid gap-3">
            <div>
              <h3 className="text-sm font-semibold">{t("pdfTitle")}</h3>
              <p className="text-secondary mt-1 text-sm">
                {t("pdfDescription")}
              </p>
            </div>
            <input
              accept="application/pdf,.pdf"
              aria-label={t("chooseFiles")}
              className="sr-only"
              multiple
              onChange={(event) => {
                void enqueue(Array.from(event.currentTarget.files ?? []));
                event.currentTarget.value = "";
              }}
              ref={fileInputRef}
              tabIndex={-1}
              type="file"
            />
            <Button
              className="justify-self-start"
              disabled={filesChecking}
              onClick={() => fileInputRef.current?.click()}
              variant="secondary"
            >
              <Icon glyph={UploadIcon} size={20} />
              {t("chooseFiles")}
            </Button>
            {(filesChecking || duplicateCount > 0) && (
              <p className="text-secondary text-sm" role="status">
                {filesChecking
                  ? t("status.checking")
                  : t("duplicatesIgnored", { count: duplicateCount })}
              </p>
            )}
            {queue.length > 0 && (
              <ul aria-label={t("queueLabel")} className="grid gap-2">
                {queue.map((item) => (
                  <li
                    className="border-line bg-surface flex min-h-14 items-center gap-3 rounded-[var(--radius-md)] border px-3 py-2"
                    key={item.id}
                  >
                    <span className="grid size-5 shrink-0 place-items-center">
                      <Icon
                        glyph={item.errorCode ? WarningIcon : DocumentIcon}
                        size={20}
                        tone={item.errorCode ? "danger" : "secondary"}
                      />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {item.file.name}
                      </span>
                      <span
                        className={
                          item.errorCode
                            ? "text-danger text-xs"
                            : "text-secondary text-xs"
                        }
                      >
                        {item.errorCode
                          ? t(item.errorCode)
                          : t("status.queued")}
                      </span>
                    </span>
                    <IconButton
                      label={t("removeFile", { name: item.file.name })}
                      onClick={() => removeQueuedFile(item.id)}
                      variant="ghost"
                    >
                      <Icon glyph={DismissIcon} size={16} tone="secondary" />
                    </IconButton>
                  </li>
                ))}
              </ul>
            )}
            {waitingCount > 0 && (
              <Button
                className="justify-self-start"
                disabled={filesChecking}
                onClick={submitFiles}
              >
                {t("uploadFiles", { count: waitingCount })}
              </Button>
            )}
          </section>

          <div className="border-line my-6 border-t" />

          <form
            className="grid gap-4"
            onSubmit={form.handleSubmit(submitSource)}
          >
            <div>
              <h3 className="text-sm font-semibold">{t("sourceTitle")}</h3>
              <p className="text-secondary mt-1 text-sm">
                {t("sourceDescription")}
              </p>
            </div>
            <fieldset className="contents" disabled={sourcePending}>
              <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
                <Field>
                  <FieldLabel>{t("sourceType")}</FieldLabel>
                  <Select
                    onValueChange={(value) => {
                      setSourceKey(undefined);
                      setSourceError(undefined);
                      form.setValue("sourceKind", value as SourceKind);
                    }}
                    value={sourceKind}
                  >
                    <FieldControl>
                      <SelectTrigger aria-label={t("sourceType")}>
                        <SelectValue />
                      </SelectTrigger>
                    </FieldControl>
                    <SelectContent>
                      <SelectItem value="doi">DOI</SelectItem>
                      <SelectItem value="arxiv">arXiv</SelectItem>
                      <SelectItem value="url">{t("pdfUrl")}</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
                <Field invalid={Boolean(form.formState.errors.sourceValue)}>
                  <FieldLabel>{t("sourceValue")}</FieldLabel>
                  <FieldControl>
                    <Input
                      placeholder={t(`placeholder.${sourceKind}`)}
                      {...form.register("sourceValue", {
                        onChange: () => {
                          setSourceKey(undefined);
                          setSourceError(undefined);
                        },
                      })}
                    />
                  </FieldControl>
                  <FieldMessage>
                    {form.formState.errors.sourceValue
                      ? t("sourceRequired")
                      : ""}
                  </FieldMessage>
                </Field>
              </div>
            </fieldset>
            <div className="flex flex-wrap items-center gap-2">
              <Button loading={sourcePending} type="submit">
                <Icon glyph={LinkIcon} size={20} tone="inverse" />
                {sourcePending ? t("sourcePending") : t("addSource")}
              </Button>
              {sourcePending && (
                <Button onClick={cancelSource} type="button" variant="ghost">
                  {t("cancelSource")}
                </Button>
              )}
            </div>
            {sourceError ? (
              <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center">
                <p className="text-danger min-w-0 flex-1 text-sm" role="alert">
                  {sourceError.message}
                </p>
                {sourceError.connectOpenAlex ? (
                  <Button
                    onClick={() => {
                      handleOpenChange(false);
                      onConnectOpenAlex();
                    }}
                    size="sm"
                    type="button"
                    variant="secondary"
                  >
                    {t("connectOpenAlex")}
                  </Button>
                ) : null}
              </div>
            ) : null}
          </form>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
