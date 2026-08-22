"use client";

import { useTranslations } from "next-intl";

import {
  Checkbox,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui";
import { FilterIcon, TagIcon } from "@/design-system/icons/semantic-icons";
import { CollectionToolbarButton } from "./collection-toolbar";
import type { PaperCollectionTag } from "./paper-collection-workbench";
import type { PaperStatus } from "./api";

export function PaperCollectionFilters({
  onStatusesChange,
  onTagIdsChange,
  statuses,
  tagIds,
  tags,
}: {
  onStatusesChange: (statuses: PaperStatus[]) => void;
  onTagIdsChange: (tagIds: string[]) => void;
  statuses: PaperStatus[];
  tagIds: string[];
  tags: PaperCollectionTag[];
}) {
  const t = useTranslations("PaperCollection");
  return (
    <div className="flex shrink-0 items-center gap-2">
      <Popover>
        <PopoverTrigger asChild>
          <CollectionToolbarButton
            count={statuses.length}
            glyph={FilterIcon}
            label={t("columns.status")}
          />
        </PopoverTrigger>
        <PopoverContent className="grid gap-1">
          {(["todo", "reading", "completed"] as const).map((status) => (
            <label
              className="hover:bg-hover flex min-h-10 items-center gap-3 rounded-[var(--radius-md)] px-2 text-sm"
              key={status}
            >
              <Checkbox
                aria-label={t(`status.${status}`)}
                checked={statuses.includes(status)}
                onCheckedChange={(checked) =>
                  onStatusesChange(
                    checked === true
                      ? [...statuses, status]
                      : statuses.filter((value) => value !== status),
                  )
                }
              />
              {t(`status.${status}`)}
            </label>
          ))}
        </PopoverContent>
      </Popover>
      <Popover>
        <PopoverTrigger asChild>
          <CollectionToolbarButton
            count={tagIds.length}
            glyph={TagIcon}
            label={t("columns.tags")}
          />
        </PopoverTrigger>
        <PopoverContent className="grid max-h-72 gap-1 overflow-auto">
          {tags.map((tag) => (
            <label
              className="hover:bg-hover flex min-h-10 items-center gap-3 rounded-[var(--radius-md)] px-2 text-sm"
              key={tag.id}
            >
              <Checkbox
                aria-label={tag.name}
                checked={tagIds.includes(tag.id)}
                onCheckedChange={(checked) =>
                  onTagIdsChange(
                    checked === true
                      ? [...tagIds, tag.id]
                      : tagIds.filter((value) => value !== tag.id),
                  )
                }
              />
              {tag.name}
            </label>
          ))}
        </PopoverContent>
      </Popover>
    </div>
  );
}
