"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  CheckCircle,
  Link,
  Page,
  RefreshDouble,
  Upload,
  WarningTriangle,
} from "iconoir-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

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
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import { uploadPaperFile, uploadPaperSource } from "../api";

type Project = components["schemas"]["ProjectResponse"];
type SourceKind = "doi" | "arxiv" | "url";
type QueueStatus = "queued" | "uploading" | "succeeded" | "failed";

type UploadQueueItem = {
  error?: string;
  file: File;
  id: string;
  status: QueueStatus;
};

const MAX_FILE_BYTES = 50 * 1024 * 1024;
const MAX_CONCURRENT_UPLOADS = 3;

const sourceSchema = z.object({
  projectId: z.string().optional(),
  sourceKind: z.enum(["doi", "arxiv", "url"]),
  sourceValue: z.string().trim().min(1),
});
type SourceForm = z.infer<typeof sourceSchema>;

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

function QueueIcon({ status }: { status: QueueStatus }) {
  const glyph =
    status === "succeeded"
      ? CheckCircle
      : status === "failed"
        ? WarningTriangle
        : status === "uploading"
          ? RefreshDouble
          : Page;
  return (
    <Icon
      className={cn(
        status === "uploading" && "animate-spin motion-reduce:animate-none",
      )}
      glyph={glyph}
      size={20}
      tone={
        status === "failed"
          ? "danger"
          : status === "succeeded"
            ? "success"
            : "secondary"
      }
    />
  );
}

export function AddPapersDialog({
  onIngestionStarted,
  onOpenChange,
  open,
  projects,
}: {
  onIngestionStarted: () => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  projects: Project[];
}) {
  const t = useTranslations("Library.addPapers");
  const [queue, setQueue] = React.useState<UploadQueueItem[]>([]);
  const [sourcePending, setSourcePending] = React.useState(false);
  const [sourceError, setSourceError] = React.useState<string>();
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const form = useForm<SourceForm>({
    defaultValues: { projectId: "", sourceKind: "doi", sourceValue: "" },
    resolver: zodResolver(sourceSchema),
  });
  const projectId = useWatch({ control: form.control, name: "projectId" });
  const sourceKind = useWatch({ control: form.control, name: "sourceKind" });

  function updateItem(id: string, patch: Partial<UploadQueueItem>) {
    setQueue((items) =>
      items.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
  }

  function enqueue(files: File[]) {
    const next = files.map<UploadQueueItem>((file) => ({
      error: file.size > MAX_FILE_BYTES ? t("fileTooLarge") : undefined,
      file,
      id: crypto.randomUUID(),
      status: file.size > MAX_FILE_BYTES ? "failed" : "queued",
    }));
    setQueue((items) => [...items, ...next]);
  }

  async function uploadItems(items: UploadQueueItem[]) {
    const projectId = form.getValues("projectId") || undefined;
    await runWithConcurrency(
      items.filter((item) => item.file.size <= MAX_FILE_BYTES),
      async (item) => {
        updateItem(item.id, { error: undefined, status: "uploading" });
        try {
          await uploadPaperFile(item.file, projectId);
          updateItem(item.id, { status: "succeeded" });
          onIngestionStarted();
        } catch {
          updateItem(item.id, { error: t("uploadFailed"), status: "failed" });
        }
      },
    );
  }

  async function submitFiles() {
    await uploadItems(queue.filter((item) => item.status === "queued"));
  }

  async function submitSource(values: SourceForm) {
    setSourcePending(true);
    setSourceError(undefined);
    try {
      await uploadPaperSource(
        { kind: values.sourceKind, value: values.sourceValue },
        values.projectId || undefined,
      );
      form.reset({ ...values, sourceValue: "" });
      onIngestionStarted();
    } catch {
      setSourceError(t("sourceFailed"));
    } finally {
      setSourcePending(false);
    }
  }

  const waitingCount = queue.filter((item) => item.status === "queued").length;

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
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
              <ul className="grid gap-2" aria-label={t("queueLabel")}>
                {queue.map((item) => (
                  <li
                    className="border-line bg-surface flex min-h-14 items-center gap-3 rounded-[var(--radius-md)] border px-3 py-2"
                    key={item.id}
                  >
                    <span className="grid size-5 shrink-0 place-items-center">
                      <QueueIcon status={item.status} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {item.file.name}
                      </span>
                      <span
                        className={cn(
                          "text-xs",
                          item.error ? "text-danger" : "text-secondary",
                        )}
                      >
                        {item.error ?? t(`status.${item.status}`)}
                      </span>
                    </span>
                    {item.status === "failed" &&
                      item.file.size <= MAX_FILE_BYTES && (
                        <Button
                          onClick={() => void uploadItems([item])}
                          size="sm"
                          variant="ghost"
                        >
                          {t("retry")}
                        </Button>
                      )}
                  </li>
                ))}
              </ul>
            )}
            {waitingCount > 0 && (
              <Button
                className="justify-self-start"
                onClick={() => void submitFiles()}
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
            <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
              <Field>
                <FieldLabel>{t("sourceType")}</FieldLabel>
                <Select
                  onValueChange={(value) =>
                    form.setValue("sourceKind", value as SourceKind)
                  }
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
                    {...form.register("sourceValue")}
                  />
                </FieldControl>
                <FieldMessage>
                  {form.formState.errors.sourceValue ? t("sourceRequired") : ""}
                </FieldMessage>
              </Field>
            </div>
            <Field>
              <FieldLabel>{t("destination")}</FieldLabel>
              <FieldControl>
                <Select
                  onValueChange={(value) =>
                    form.setValue("projectId", value === "library" ? "" : value)
                  }
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
              <FieldDescription>{t("destinationDescription")}</FieldDescription>
            </Field>
            <Button
              className="justify-self-start"
              loading={sourcePending}
              type="submit"
            >
              <Icon glyph={Link} size={20} />
              {t("addSource")}
            </Button>
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
