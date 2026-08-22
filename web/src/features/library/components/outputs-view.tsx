"use client";

import {
  FilterIcon,
  AudioIcon,
  CitationIcon,
  QuoteIcon,
  DataTableIcon,
} from "@/design-system/icons/semantic-icons";
import { useFormatter, useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import {
  Button,
  Checkbox,
  CursorPagination,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  SelectContent,
  SelectItem,
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui";
import { Icon, type IconGlyph } from "@/design-system/icons/icon";
import {
  CollectionToolbar,
  CollectionToolbarButton,
  CollectionToolbarSelectTrigger,
} from "@/features/paper-collection";
import type { components } from "@/lib/api/generated/schema";
import type { OutputKind, OutputSort } from "../library-search";

type Output = components["schemas"]["LibraryOutputResponse"];
type OutputList = components["schemas"]["LibraryOutputListResponse"];

const OUTPUT_KINDS: OutputKind[] = [
  "annotation_thread",
  "citation",
  "audio_overview",
  "data_table",
];
const OUTPUT_SORTS: OutputSort[] = [
  "updated_desc",
  "updated_asc",
  "title_asc",
  "title_desc",
];

const kindIcon: Record<OutputKind, IconGlyph> = {
  annotation_thread: QuoteIcon,
  citation: CitationIcon,
  audio_overview: AudioIcon,
  data_table: DataTableIcon,
};

function outputPreview(output: Output) {
  const item = output.item;
  if (item.kind === "annotation_thread") {
    return item.annotation_thread?.quote_text;
  }
  if (item.kind === "citation") {
    return item.citation?.snapshot.data.title;
  }
  if (item.kind === "audio_overview") {
    return item.audio_overview?.transcript;
  }
  return item.data_table
    ? `${item.data_table.columns.length} × ${item.data_table.rows.length}`
    : undefined;
}

function OutputIdentity({ output }: { output: Output }) {
  const t = useTranslations("Library.outputs");
  const kind = output.item.kind;
  return (
    <div className="flex min-w-0 items-start gap-3">
      <span className="border-line bg-subtle grid size-9 shrink-0 place-items-center rounded-[var(--radius-md)] border">
        <Icon glyph={kindIcon[kind]} size={20} tone="secondary" />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-semibold">
          {output.title}
        </span>
        <span className="text-secondary mt-1 block truncate text-xs">
          {outputPreview(output) || t(`kind.${kind}`)}
        </span>
      </span>
    </div>
  );
}

function KindFilter({
  active,
  onChange,
}: {
  active: OutputKind[];
  onChange: (kinds: OutputKind[]) => void;
}) {
  const t = useTranslations("Library.outputs.filters");
  const common = useTranslations("Library.common");
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const body = (
    <div className="grid gap-1">
      {OUTPUT_KINDS.map((kind) => (
        <label
          className="hover:bg-hover flex min-h-10 items-center gap-3 rounded-[var(--radius-md)] px-2 text-sm"
          key={kind}
        >
          <Checkbox
            aria-label={t(`kind.${kind}`)}
            checked={active.includes(kind)}
            onCheckedChange={(checked) =>
              onChange(
                checked === true
                  ? [...active, kind]
                  : active.filter((value) => value !== kind),
              )
            }
          />
          <span className="grid size-5 place-items-center">
            <Icon glyph={kindIcon[kind]} size={16} tone="secondary" />
          </span>
          {t(`kind.${kind}`)}
        </label>
      ))}
    </div>
  );
  const trigger = (
    <CollectionToolbarButton
      count={active.length}
      glyph={FilterIcon}
      label={t("label")}
    />
  );
  return (
    <>
      <div className="hidden sm:block">
        <Popover>
          <PopoverTrigger asChild>{trigger}</PopoverTrigger>
          <PopoverContent>{body}</PopoverContent>
        </Popover>
      </div>
      <div className="sm:hidden">
        <Sheet onOpenChange={setMobileOpen} open={mobileOpen}>
          <SheetTrigger asChild>{trigger}</SheetTrigger>
          <SheetContent
            className="h-auto max-h-[76dvh] rounded-t-[var(--radius-xl)] p-5"
            closeLabel={common("close")}
            side="bottom"
          >
            <SheetTitle className="mb-4 text-lg font-semibold">
              {t("label")}
            </SheetTitle>
            {body}
          </SheetContent>
        </Sheet>
      </div>
    </>
  );
}

export function OutputsView({
  data,
  error,
  kinds,
  loading,
  onKindFilterChange,
  onNext,
  onPrevious,
  onRetryLoad,
  onSortChange,
  search,
  sort,
}: {
  data?: OutputList;
  error?: unknown;
  kinds: OutputKind[];
  loading: boolean;
  onKindFilterChange: (kinds: OutputKind[]) => void;
  onNext: (cursor: string) => void;
  onPrevious: (cursor: string) => void;
  onRetryLoad: () => void;
  onSortChange: (sort: OutputSort) => void;
  search: React.ReactNode;
  sort: OutputSort;
}) {
  const t = useTranslations("Library.outputs");
  const format = useFormatter();
  const outputs = data?.items ?? [];

  return (
    <>
      <div className="min-w-0">
        <CollectionToolbar
          controls={
            <>
              <KindFilter active={kinds} onChange={onKindFilterChange} />
              <Select
                onValueChange={(value) => onSortChange(value as OutputSort)}
                value={sort}
              >
                <CollectionToolbarSelectTrigger label={t("sort.label")} />
                <SelectContent>
                  {OUTPUT_SORTS.map((option) => (
                    <SelectItem key={option} value={option}>
                      {t(`sort.${option}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          }
          meta={data ? t("count", { count: data.total_count }) : undefined}
          search={search}
        />
      </div>

      <div className="mt-4 min-w-0">
        {loading && <LoadingState label={t("loading")} />}
        {Boolean(error) && !loading && (
          <AsyncFeedback
            action={{ label: t("tryAgain"), onClick: onRetryLoad }}
            description={t("errorDescription")}
            state="error"
            title={t("errorTitle")}
          />
        )}
        {!loading && !error && data && outputs.length === 0 && (
          <AsyncFeedback
            description={t("emptyDescription")}
            state="empty"
            title={t("emptyTitle")}
          />
        )}
        {!loading && !error && outputs.length > 0 && (
          <>
            <div className="border-line bg-surface hidden border-y md:block">
              <table className="w-full table-fixed border-collapse text-left">
                <thead className="bg-subtle text-muted text-xs font-medium">
                  <tr>
                    <th className="px-4 py-3 font-medium">
                      {t("columns.output")}
                    </th>
                    <th className="w-40 px-3 py-3 font-medium">
                      {t("columns.type")}
                    </th>
                    <th className="w-56 px-3 py-3 font-medium">
                      {t("columns.source")}
                    </th>
                    <th className="w-40 px-3 py-3 font-medium">
                      {t("columns.updated")}
                    </th>
                    <th className="w-40 px-3 py-3 font-medium">
                      {t("columns.open")}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-line divide-y">
                  {outputs.map((output) => (
                    <tr className="hover:bg-hover" key={output.item.id}>
                      <td className="px-4 py-4">
                        <OutputIdentity output={output} />
                      </td>
                      <td className="text-secondary px-3 py-4 text-sm">
                        {t(`kind.${output.item.kind}`)}
                      </td>
                      <td className="px-3 py-4">
                        <span className="block truncate text-sm font-medium">
                          {output.source.title}
                        </span>
                        <span className="text-secondary mt-1 block text-xs">
                          {t(`scope.${output.source.audience_type}`)}
                        </span>
                      </td>
                      <td className="text-secondary px-3 py-4 text-sm">
                        {format.dateTime(new Date(output.item.updated_at), {
                          dateStyle: "medium",
                        })}
                      </td>
                      <td className="px-3 py-3">
                        <Button disabled size="sm" variant="ghost">
                          {t("notAvailable")}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <ul className="divide-line border-line bg-surface min-w-0 divide-y border-y md:hidden">
              {outputs.map((output) => (
                <li
                  className="min-w-0 overflow-hidden py-4"
                  key={output.item.id}
                >
                  <OutputIdentity output={output} />
                  <div className="text-secondary mt-4 grid grid-cols-[1fr_auto] gap-3 text-xs">
                    <span className="min-w-0">
                      <span className="text-foreground block truncate font-medium">
                        {output.source.title}
                      </span>
                      {t(`scope.${output.source.audience_type}`)}
                    </span>
                    <span>
                      {format.dateTime(new Date(output.item.updated_at), {
                        dateStyle: "medium",
                      })}
                    </span>
                  </div>
                  <div className="mt-3">
                    <Button disabled size="sm" variant="ghost">
                      {t("notAvailable")}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {data && (data.previous_cursor || data.next_cursor) && (
        <div className="mt-6 flex justify-end">
          <CursorPagination
            nextDisabled={!data.next_cursor}
            nextLabel={t("next")}
            onNext={() => data.next_cursor && onNext(data.next_cursor)}
            onPrevious={() =>
              data.previous_cursor && onPrevious(data.previous_cursor)
            }
            previousDisabled={!data.previous_cursor}
            previousLabel={t("previous")}
          />
        </div>
      )}
    </>
  );
}
