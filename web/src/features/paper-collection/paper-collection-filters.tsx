"use client";

import { useTranslations } from "next-intl";

import {
  Button,
  Checkbox,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui";
import { Badge } from "@/components/ui/display";
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
    <div className="flex items-center gap-2">
      <Popover>
        <PopoverTrigger asChild>
          <Button variant="secondary">
            {t("columns.status")}
            {statuses.length ? (
              <Badge tone="neutral">{statuses.length}</Badge>
            ) : null}
          </Button>
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
          <Button variant="secondary">
            {t("columns.tags")}
            {tagIds.length ? (
              <Badge tone="neutral">{tagIds.length}</Badge>
            ) : null}
          </Button>
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
