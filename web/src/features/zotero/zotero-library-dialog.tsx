"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import {
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHandle,
  DialogHeader,
  DialogTitle,
  SearchField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import {
  beginZoteroAuthorization,
  startZoteroImport,
  type ZoteroLibraryFilters,
  type ZoteroOperation,
  zoteroQueries,
} from "./api";
import { zoteroLibraryErrorKey } from "./message-keys";
import { buildZoteroReturnPath } from "./oauth-return";

function useDebouncedValue(value: string) {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), 250);
    return () => window.clearTimeout(timer);
  }, [value]);
  return debounced;
}

function errorCode(error: unknown) {
  return error instanceof ApiError && error.code
    ? error.code
    : "zotero_unavailable";
}

const defaultFilters: ZoteroLibraryFilters = {
  sort: "modified_desc",
};

export function ZoteroLibraryDialog({
  onImportAccepted,
  onOpenChange,
  open,
}: {
  onImportAccepted: (operation: ZoteroOperation) => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const t = useTranslations("Zotero.library");
  const [query, setQuery] = React.useState("");
  const debouncedQuery = useDebouncedValue(query);
  const [filters, setFilters] = React.useState(defaultFilters);
  const [selected, setSelected] = React.useState<string[]>([]);
  const status = useQuery({ ...zoteroQueries.status(), enabled: open });
  const connected = status.data?.connection_state === "connected";
  const collections = useQuery({
    ...zoteroQueries.collections(),
    enabled: open && connected,
  });
  const effectiveFilters = React.useMemo(
    () => ({ ...filters, query: debouncedQuery }),
    [debouncedQuery, filters],
  );
  const library = useQuery({
    ...zoteroQueries.library(effectiveFilters),
    enabled: open && connected,
  });
  const authorize = useMutation({
    mutationFn: async () => {
      const result = await beginZoteroAuthorization(
        "import",
        buildZoteroReturnPath(
          window.location.pathname,
          window.location.search,
          "import",
        ),
      );
      window.location.assign(result.auth_url);
    },
  });
  const importMutation = useMutation({
    mutationFn: startZoteroImport,
    onSuccess: (operation) => {
      onImportAccepted(operation);
      onOpenChange(false);
    },
  });

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) {
      setFilters(defaultFilters);
      setQuery("");
      setSelected([]);
    }
    onOpenChange(nextOpen);
  }

  function updateFilters(patch: Partial<ZoteroLibraryFilters>) {
    setFilters((current) => ({
      ...current,
      ...patch,
      cursor: undefined,
    }));
  }

  const maxSelection = Math.min(
    library.data?.max_batch_size ?? 50,
    library.data?.remaining_slots ?? 50,
    50,
  );

  return (
    <Dialog onOpenChange={handleOpenChange} open={open}>
      <DialogContent
        className="lg:w-[min(94vw,64rem)] lg:max-w-5xl"
        closeLabel={t("close")}
        placement="responsive-full"
      >
        <DialogHandle />
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <p className="text-secondary mt-2 text-sm">{t("description")}</p>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {status.isPending ? (
            <LoadingState label={t("loadingConnection")} />
          ) : status.isError ? (
            <AsyncFeedback
              action={{
                label: t("retry"),
                onClick: () => void status.refetch(),
              }}
              description={t(zoteroLibraryErrorKey(errorCode(status.error)))}
              state="error"
              title={t("connectionError")}
            />
          ) : !connected ? (
            <div className="mx-auto grid max-w-lg justify-items-start gap-4 py-12">
              <div>
                <h3 className="text-lg font-semibold">{t("connectTitle")}</h3>
                <p className="text-secondary mt-2 text-sm leading-6">
                  {t("connectDescription")}
                </p>
              </div>
              <Button
                loading={authorize.isPending}
                onClick={() => authorize.mutate()}
              >
                {t("connect")}
              </Button>
              {authorize.isError ? (
                <p className="text-danger text-sm" role="alert">
                  {t(zoteroLibraryErrorKey(errorCode(authorize.error)))}
                </p>
              ) : null}
            </div>
          ) : (
            <>
              <div className="grid gap-3 lg:grid-cols-[minmax(14rem,1fr)_12rem_12rem_12rem]">
                <SearchField
                  aria-label={t("search")}
                  onChange={(event) => {
                    setQuery(event.currentTarget.value);
                    setFilters((current) => ({
                      ...current,
                      cursor: undefined,
                    }));
                  }}
                  placeholder={t("search")}
                  value={query}
                />
                <Select
                  onValueChange={(value) =>
                    updateFilters({
                      collectionKey: value === "all" ? undefined : value,
                    })
                  }
                  value={filters.collectionKey ?? "all"}
                >
                  <SelectTrigger aria-label={t("collection")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t("allCollections")}</SelectItem>
                    {collections.data?.items.map((collection) => (
                      <SelectItem key={collection.key} value={collection.key}>
                        {collection.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select
                  onValueChange={(value) =>
                    updateFilters({
                      itemType:
                        value === "all"
                          ? undefined
                          : (value as ZoteroLibraryFilters["itemType"]),
                    })
                  }
                  value={filters.itemType ?? "all"}
                >
                  <SelectTrigger aria-label={t("type")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t("types.all")}</SelectItem>
                    <SelectItem value="journalArticle">
                      {t("types.journalArticle")}
                    </SelectItem>
                    <SelectItem value="conferencePaper">
                      {t("types.conferencePaper")}
                    </SelectItem>
                    <SelectItem value="preprint">
                      {t("types.preprint")}
                    </SelectItem>
                  </SelectContent>
                </Select>
                <Select
                  onValueChange={(value) =>
                    updateFilters({
                      sort: value as ZoteroLibraryFilters["sort"],
                    })
                  }
                  value={filters.sort}
                >
                  <SelectTrigger aria-label={t("sort.label")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(
                      [
                        "modified_desc",
                        "added_desc",
                        "published_desc",
                        "title_asc",
                        "creator_asc",
                      ] as const
                    ).map((sort) => (
                      <SelectItem key={sort} value={sort}>
                        {t(`sort.${sort}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {library.isPending ? (
                <LoadingState label={t("loading")} />
              ) : library.isError ? (
                <AsyncFeedback
                  action={{
                    label: t("retry"),
                    onClick: () => void library.refetch(),
                  }}
                  description={t(
                    zoteroLibraryErrorKey(errorCode(library.error)),
                  )}
                  state="error"
                  title={t("loadError")}
                />
              ) : library.data?.items.length === 0 ? (
                <AsyncFeedback
                  description={t("emptyDescription")}
                  state="empty"
                  title={t("emptyTitle")}
                />
              ) : (
                <div className="border-line divide-line shrink-0 overflow-hidden rounded-[var(--radius-lg)] border">
                  {library.data?.items.map((item) => {
                    const checked = selected.includes(item.zotero_item_key);
                    const unavailable =
                      item.source_availability === "unavailable" ||
                      item.import_state !== "available";
                    const disabled =
                      unavailable ||
                      (!checked && selected.length >= maxSelection);
                    return (
                      <label
                        aria-disabled={disabled}
                        className={`hover:bg-hover flex min-h-16 items-start gap-3 px-3 py-3 sm:px-4 ${disabled ? "cursor-not-allowed" : "cursor-pointer"}`}
                        key={item.zotero_item_key}
                      >
                        <Checkbox
                          checked={checked}
                          data-disabled={disabled ? "" : undefined}
                          disabled={disabled}
                          onCheckedChange={(next) =>
                            setSelected((current) =>
                              next
                                ? [...current, item.zotero_item_key]
                                : current.filter(
                                    (key) => key !== item.zotero_item_key,
                                  ),
                            )
                          }
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium break-words">
                            {item.title || t("untitled")}
                          </span>
                          <span className="text-secondary mt-1 block truncate text-xs">
                            {t("metadata", {
                              authors:
                                item.authors.join(", ") || t("unknownAuthors"),
                              date: item.date ?? t("unknownDate"),
                            })}
                          </span>
                          <span className="text-secondary mt-1 block text-xs">
                            {item.import_state !== "available"
                              ? t(`importState.${item.import_state}`)
                              : t(`availability.${item.source_availability}`)}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}

              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-secondary text-sm" role="status">
                  {maxSelection === 0
                    ? t("zeroQuota")
                    : t("selection", {
                        count: selected.length,
                        limit: maxSelection,
                      })}
                </p>
                <div className="flex gap-2">
                  <Button
                    disabled={!library.data?.previous_cursor}
                    onClick={() =>
                      setFilters((current) => ({
                        ...current,
                        cursor: library.data?.previous_cursor ?? undefined,
                      }))
                    }
                    size="sm"
                    variant="secondary"
                  >
                    {t("previous")}
                  </Button>
                  <Button
                    disabled={!library.data?.next_cursor}
                    onClick={() =>
                      setFilters((current) => ({
                        ...current,
                        cursor: library.data?.next_cursor ?? undefined,
                      }))
                    }
                    size="sm"
                    variant="secondary"
                  >
                    {t("next")}
                  </Button>
                </div>
              </div>
              {importMutation.isError ? (
                <p className="text-danger text-sm" role="alert">
                  {t(zoteroLibraryErrorKey(errorCode(importMutation.error)))}
                </p>
              ) : null}
            </>
          )}
        </DialogBody>
        {connected ? (
          <DialogFooter>
            <Button onClick={() => handleOpenChange(false)} variant="secondary">
              {t("cancel")}
            </Button>
            <Button
              disabled={selected.length === 0 || maxSelection === 0}
              loading={importMutation.isPending}
              onClick={() => importMutation.mutate(selected)}
            >
              {t("import", { count: selected.length })}
            </Button>
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
