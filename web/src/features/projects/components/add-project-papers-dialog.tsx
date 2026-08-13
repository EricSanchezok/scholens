"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import {
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHandle,
  DialogHeader,
  DialogTitle,
  SearchField,
} from "@/components/ui";
import type { components } from "@/lib/api/generated/schema";

type LibraryEntry =
  components["schemas"]["LibraryPaperListResponse"]["items"][number];

export function AddProjectPapersDialog({
  entries,
  loading,
  onOpenChange,
  onSubmit,
  open,
}: {
  entries: LibraryEntry[];
  loading: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (documentIds: string[]) => Promise<unknown>;
  open: boolean;
}) {
  const t = useTranslations("Projects.addPapers");
  const [query, setQuery] = React.useState("");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState(false);

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) {
      setQuery("");
      setSelected([]);
      setError(false);
    }
    onOpenChange(nextOpen);
  }
  const papers = entries.filter(
    (entry) =>
      entry.entry_type === "paper" &&
      (entry.document.title ?? entry.document.original_filename)
        .toLocaleLowerCase()
        .includes(query.trim().toLocaleLowerCase()),
  );

  async function submit() {
    setSubmitting(true);
    setError(false);
    try {
      await onSubmit(selected);
      handleOpenChange(false);
    } catch {
      setError(true);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog onOpenChange={handleOpenChange} open={open}>
      <DialogContent closeLabel={t("close")} placement="responsive-bottom">
        <DialogHandle />
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <DialogBody className="grid gap-4">
          <SearchField
            aria-label={t("search")}
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder={t("search")}
            value={query}
          />
          <div className="grid max-h-80 gap-1 overflow-y-auto">
            {loading ? (
              <p className="text-muted py-8 text-center text-sm">
                {t("loading")}
              </p>
            ) : papers.length === 0 ? (
              <p className="text-muted py-8 text-center text-sm">
                {t("empty")}
              </p>
            ) : (
              papers.map((entry) => {
                if (entry.entry_type !== "paper") return null;
                const id = entry.document.document_id;
                const checked = selected.includes(id);
                return (
                  <label
                    className="hover:bg-hover flex cursor-pointer items-start gap-3 rounded-[var(--radius-md)] px-3 py-3"
                    key={id}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={(next) =>
                        setSelected((current) =>
                          next
                            ? [...current, id]
                            : current.filter((value) => value !== id),
                        )
                      }
                    />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">
                        {entry.document.title ??
                          entry.document.original_filename}
                      </span>
                      <span className="text-muted mt-1 block truncate text-xs">
                        {entry.document.authors?.join(", ") ||
                          t("unknownAuthors")}
                      </span>
                    </span>
                  </label>
                );
              })
            )}
          </div>
          {error && (
            <p aria-live="polite" className="text-danger text-sm">
              {t("error")}
            </p>
          )}
        </DialogBody>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="secondary">
              {t("cancel")}
            </Button>
          </DialogClose>
          <Button
            disabled={selected.length === 0}
            loading={submitting}
            onClick={() => void submit()}
          >
            {t("action", { count: selected.length })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
