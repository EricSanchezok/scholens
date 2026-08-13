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
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui";
import { Badge } from "@/components/ui/display";
import { Icon, type IconGlyph } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import type { OutputKind, OutputSort } from "../library-search";

type Output = components["schemas"]["LibraryOutputResponse"];
type OutputList = components["schemas"]["LibraryOutputListResponse"];

const OUTPUT_KINDS: OutputKind[] = [
  "highlight_thread",
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
  highlight_thread: QuoteIcon,
  citation: CitationIcon,
  audio_overview: AudioIcon,
  data_table: DataTableIcon,
};

function outputPreview(output: Output) {
  const item = output.item;
  if (item.kind === "highlight_thread") {
    return item.highlight_thread?.quote_text;
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
      <span className="bg-subtle grid size-9 shrink-0 place-items-center rounded-[var(--radius-md)]">
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
    <Button variant="secondary">
      <Icon glyph={FilterIcon} size={20} tone="secondary" />
      {t("label")}
      {active.length > 0 && <Badge tone="neutral">{active.length}</Badge>}
    </Button>
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
            className="inset-x-0 top-auto bottom-0 h-auto max-h-[76dvh] w-full max-w-none rounded-t-[var(--radius-xl)] border-t border-l-0 p-5"
            closeLabel={common("close")}
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
      <div className="grid min-w-0 gap-2 md:grid-cols-[minmax(12rem,1fr)_auto_auto_auto] md:items-center">
        <div className="min-w-0">{search}</div>
        <div className="flex min-w-0 items-center gap-2 md:contents">
          <KindFilter active={kinds} onChange={onKindFilterChange} />
          <Select
            onValueChange={(value) => onSortChange(value as OutputSort)}
            value={sort}
          >
            <SelectTrigger
              aria-label={t("sort.label")}
              className="min-w-0 flex-1 md:w-auto md:min-w-44 md:flex-none"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {OUTPUT_SORTS.map((option) => (
                <SelectItem key={option} value={option}>
                  {t(`sort.${option}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {data && (
            <span className="text-secondary ml-auto shrink-0 text-sm md:ml-2">
              {t("count", { count: data.total_count })}
            </span>
          )}
        </div>
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
            <div className="border-line bg-surface hidden overflow-hidden rounded-[var(--radius-lg)] border md:block">
              <table className="w-full table-fixed border-collapse text-left">
                <thead className="bg-subtle text-secondary text-xs font-medium">
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
                          {t(`scope.${output.source.scope_type}`)}
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

            <ul className="grid min-w-0 gap-2 md:hidden">
              {outputs.map((output) => (
                <li
                  className="border-line bg-surface min-w-0 overflow-hidden rounded-[var(--radius-lg)] border p-4"
                  key={output.item.id}
                >
                  <OutputIdentity output={output} />
                  <div className="text-secondary mt-4 grid grid-cols-[1fr_auto] gap-3 text-xs">
                    <span className="min-w-0">
                      <span className="text-foreground block truncate font-medium">
                        {output.source.title}
                      </span>
                      {t(`scope.${output.source.scope_type}`)}
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
