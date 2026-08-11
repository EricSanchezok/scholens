"use client";

import { Link, Page, Upload, WarningTriangle, Xmark } from "iconoir-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  Field,
  FieldControl,
  FieldDescription,
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
import type { components } from "@/lib/api/generated/schema";
import { ApiError } from "@/lib/api/errors";
import type { PreparedPaperUpload } from "../use-paper-ingestions";

type Project = components["schemas"]["ProjectResponse"];
type Source = components["schemas"]["UploadFromSourceRequest"]["source"];
type SourceKind = Source["kind"];

type QueuedFile = PreparedPaperUpload & { errorCode?: "fileTooLarge" };

const MAX_FILE_BYTES = 50 * 1024 * 1024;

const sourceSchema = z.object({
  projectId: z.string().optional(),
  sourceKind: z.enum(["doi", "arxiv", "url"]),
  sourceValue: z.string().trim().min(1),
});
type SourceForm = z.infer<typeof sourceSchema>;

export function AddPapersDialog({
  onOpenChange,
  onSubmitSource,
  onUploadFiles,
  open,
  projects,
}: {
  onOpenChange: (open: boolean) => void;
  onSubmitSource: (input: {
    idempotencyKey: string;
    projectId?: string;
    signal: AbortSignal;
    source: Source;
  }) => Promise<unknown>;
  onUploadFiles: (files: PreparedPaperUpload[], projectId?: string) => void;
  open: boolean;
  projects: Project[];
}) {
  const t = useTranslations("Library.addPapers");
  const [queue, setQueue] = React.useState<QueuedFile[]>([]);
  const [sourcePending, setSourcePending] = React.useState(false);
  const [sourceError, setSourceError] = React.useState<string>();
  const [sourceController, setSourceController] = React.useState<
    AbortController | undefined
  >();
  const [sourceKey, setSourceKey] = React.useState<string>();
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const form = useForm<SourceForm>({
    defaultValues: { projectId: "", sourceKind: "doi", sourceValue: "" },
    resolver: zodResolver(sourceSchema),
  });
  const projectId =
    useWatch({ control: form.control, name: "projectId" }) ?? "";
  const sourceKind =
    useWatch({ control: form.control, name: "sourceKind" }) ?? "doi";

  function enqueue(files: File[]) {
    setQueue((items) => [
      ...items,
      ...files.map<QueuedFile>((file) => ({
        errorCode: file.size > MAX_FILE_BYTES ? "fileTooLarge" : undefined,
        file,
        id: crypto.randomUUID(),
        idempotencyKey: crypto.randomUUID(),
      })),
    ]);
  }

  function removeQueuedFile(id: string) {
    setQueue((items) => items.filter((item) => item.id !== id));
  }

  function submitFiles() {
    const valid = queue.filter((item) => !item.errorCode);
    if (valid.length === 0) return;
    const invalid = queue.filter((item) => item.errorCode);
    onUploadFiles(valid, projectId || undefined);
    setQueue(invalid);
    if (invalid.length === 0) onOpenChange(false);
  }

  function sourceErrorMessage(error: unknown) {
    const code = error instanceof ApiError ? error.code : "connection_failed";
    switch (code) {
      case "paper_source_pdf_unavailable":
        return t("errors.unavailable");
      case "paper_source_unsafe_address":
        return t("errors.unsafeAddress");
      case "upload_too_large":
        return t("errors.tooLarge");
      case "invalid_pdf":
      case "pdf_encrypted":
        return t("errors.invalidPdf");
      case "upload_quota_exceeded":
      case "paper_upload_quota_exceeded":
      case "paper_quota_exceeded":
      case "storage_quota_exceeded":
      case "project_owner_quota_exceeded":
      case "project_paper_quota_exceeded":
        return t("errors.quota");
      case "connection_failed":
      case "jobs_submission_failed":
      case "service_unavailable":
        return t("errors.serviceUnavailable");
      default:
        return t("sourceFailed");
    }
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
        projectId: values.projectId || undefined,
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
    if (!nextOpen) cancelSource();
    onOpenChange(nextOpen);
  }

  const waitingCount = queue.filter((item) => !item.errorCode).length;

  return (
    <Dialog onOpenChange={handleOpenChange} open={open}>
      <DialogContent
        className="flex max-h-[88dvh] flex-col overflow-hidden lg:max-w-2xl"
        closeLabel={t("close")}
        placement="responsive-bottom"
      >
        <div className="border-line shrink-0 border-b px-5 py-5 pr-14 lg:px-6">
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 lg:px-6">
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
                enqueue(Array.from(event.currentTarget.files ?? []));
                event.currentTarget.value = "";
              }}
              ref={fileInputRef}
              type="file"
            />
            <Button
              className="justify-self-start"
              onClick={() => fileInputRef.current?.click()}
              variant="secondary"
            >
              <Icon glyph={Upload} size={20} />
              {t("chooseFiles")}
            </Button>
            {queue.length > 0 && (
              <ul aria-label={t("queueLabel")} className="grid gap-2">
                {queue.map((item) => (
                  <li
                    className="border-line bg-surface flex min-h-14 items-center gap-3 rounded-[var(--radius-md)] border px-3 py-2"
                    key={item.id}
                  >
                    <span className="grid size-5 shrink-0 place-items-center">
                      <Icon
                        glyph={item.errorCode ? WarningTriangle : Page}
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
                      <Icon glyph={Xmark} size={16} tone="secondary" />
                    </IconButton>
                  </li>
                ))}
              </ul>
            )}
            {waitingCount > 0 && (
              <Button className="justify-self-start" onClick={submitFiles}>
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
              <Field>
                <FieldLabel>{t("destination")}</FieldLabel>
                <FieldControl>
                  <Select
                    onValueChange={(value) => {
                      setSourceKey(undefined);
                      form.setValue(
                        "projectId",
                        value === "library" ? "" : value,
                      );
                    }}
                    value={projectId || "library"}
                  >
                    <SelectTrigger aria-label={t("destination")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="library">
                        {t("personalLibrary")}
                      </SelectItem>
                      {projects.map((project) => (
                        <SelectItem key={project.id} value={project.id}>
                          {project.title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FieldControl>
                <FieldDescription>
                  {t("destinationDescription")}
                </FieldDescription>
              </Field>
            </fieldset>
            <div className="flex flex-wrap items-center gap-2">
              <Button loading={sourcePending} type="submit">
                <Icon glyph={Link} size={20} tone="inverse" />
                {sourcePending ? t("sourcePending") : t("addSource")}
              </Button>
              {sourcePending && (
                <Button onClick={cancelSource} type="button" variant="ghost">
                  {t("cancelSource")}
                </Button>
              )}
            </div>
            {sourceError && (
              <p className="text-danger text-sm" role="alert">
                {sourceError}
              </p>
            )}
          </form>
        </div>
      </DialogContent>
    </Dialog>
  );
}
