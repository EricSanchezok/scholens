"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import {
  SendIcon,
  MentionIcon,
  ExpandIcon,
  DocumentIcon,
  StopIcon,
  DismissIcon,
} from "@/design-system/icons/semantic-icons";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm, useWatch, type UseFormReturn } from "react-hook-form";

import {
  Button,
  Checkbox,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
  IconButton,
  isImeComposing,
  keyboardFocusRing,
  Popover,
  PopoverContent,
  PopoverTrigger,
  SearchField,
  Switch,
  useTextControlFocus,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import { conversationQueries } from "../api/queries";
import { composerSchema, type ComposerValues } from "../schemas";

export type ResearchContextPaperOption = {
  document: Pick<
    components["schemas"]["DocumentResponse"],
    "document_id" | "original_filename" | "title"
  > &
    Partial<
      Pick<components["schemas"]["DocumentResponse"], "authors" | "journal">
    >;
  metadata_overrides?: Pick<
    components["schemas"]["DocumentMetadataOverrides"],
    "title"
  > | null;
};
export type ResearchContextProjectOption = Pick<
  components["schemas"]["ProjectResponse"],
  "id" | "title"
> &
  Partial<
    Pick<
      components["schemas"]["ProjectResponse"],
      "num_conversations" | "num_papers"
    >
  >;
export type ResearchContext =
  | components["schemas"]["LibraryPaperContext"]
  | components["schemas"]["SelectedPaperContext"];
export type ReasoningLevel = components["schemas"]["ReasoningLevel"];
export type ResearchComposerSurface = "workspace" | "context-panel";

export type ResearchContextDisplay =
  | { kind: "library" }
  | { kind: "project"; title: string }
  | { kind: "paper"; title: string }
  | { kind: "papers"; count: number }
  | { kind: "items"; count: number }
  | { kind: "empty" };

export function getResearchContextDisplay(
  context: ResearchContext,
  papers: ReadonlyArray<ResearchContextPaperOption>,
  projects: ReadonlyArray<ResearchContextProjectOption>,
): ResearchContextDisplay {
  if (context.kind === "library") return { kind: "library" };

  const projectIds = context.project_ids ?? [];
  const documentIds = context.document_ids ?? [];
  const total = projectIds.length + documentIds.length;
  if (total === 0) return { kind: "empty" };

  if (projectIds.length === 1 && documentIds.length === 0) {
    const project = projects.find((item) => item.id === projectIds[0]);
    if (project) return { kind: "project", title: project.title };
  }

  if (documentIds.length === 1 && projectIds.length === 0) {
    const paper = papers.find(
      (item) => item.document.document_id === documentIds[0],
    );
    if (paper) {
      return {
        kind: "paper",
        title:
          paper.metadata_overrides?.title ??
          paper.document.title ??
          paper.document.original_filename,
      };
    }
  }

  if (projectIds.length === 0 && documentIds.length > 1) {
    return { kind: "papers", count: documentIds.length };
  }

  return { kind: "items", count: total };
}

export function useResearchComposerForm() {
  return useForm<ComposerValues>({
    defaultValues: { message: "" },
    mode: "onChange",
    resolver: zodResolver(composerSchema),
  });
}

function mergeContextOptions<T>(
  seeds: readonly T[],
  results: readonly T[],
  getId: (value: T) => string,
) {
  const merged = new Map(seeds.map((value) => [getId(value), value]));
  for (const value of results) merged.set(getId(value), value);
  return [...merged.values()];
}

function ContextPicker({
  context,
  papers,
  projects,
  onChange,
  open,
  onOpenChange,
  disabled,
  triggerClassName,
}: {
  context: ResearchContext;
  papers: ResearchContextPaperOption[];
  projects: ResearchContextProjectOption[];
  onChange: (context: ResearchContext) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  disabled?: boolean;
  triggerClassName?: string;
}) {
  const t = useTranslations("Home.context");
  const librarySwitchId = React.useId();
  const [query, setQuery] = React.useState("");
  const normalizedInputQuery = query.trim();
  const [catalogQuery, setCatalogQuery] = React.useState(normalizedInputQuery);
  React.useEffect(() => {
    const timer = window.setTimeout(
      () => setCatalogQuery(normalizedInputQuery),
      250,
    );
    return () => window.clearTimeout(timer);
  }, [normalizedInputQuery]);
  const catalogEnabled = open && context.kind !== "library";
  const catalogPapersQuery = useQuery({
    ...conversationQueries.contextPapers(catalogQuery),
    enabled: catalogEnabled,
  });
  const catalogProjectsQuery = useQuery({
    ...conversationQueries.contextProjects(catalogQuery),
    enabled: catalogEnabled,
  });
  const catalogPapers = React.useMemo(
    () =>
      (catalogPapersQuery.data?.items ?? []).flatMap((entry) =>
        entry.entry_type === "paper" ? [entry] : [],
      ),
    [catalogPapersQuery.data],
  );
  const allPapers = React.useMemo(
    () =>
      mergeContextOptions(
        papers,
        catalogPapers,
        (paper) => paper.document.document_id,
      ),
    [catalogPapers, papers],
  );
  const allProjects = React.useMemo(
    () =>
      mergeContextOptions(
        projects,
        catalogProjectsQuery.data?.items ?? [],
        (project) => project.id,
      ),
    [catalogProjectsQuery.data, projects],
  );
  const selectedProjects =
    context.kind === "selection" ? (context.project_ids ?? []) : [];
  const selectedDocuments =
    context.kind === "selection" ? (context.document_ids ?? []) : [];
  const normalizedQuery = normalizedInputQuery.toLocaleLowerCase();
  const visibleProjects = allProjects.filter((project) =>
    project.title.toLocaleLowerCase().includes(normalizedQuery),
  );
  const visiblePapers = allPapers.filter((paper) => {
    const title =
      paper.metadata_overrides?.title ??
      paper.document.title ??
      paper.document.original_filename;
    return title.toLocaleLowerCase().includes(normalizedQuery);
  });
  const catalogLoading =
    catalogQuery !== normalizedInputQuery ||
    catalogPapersQuery.isFetching ||
    catalogProjectsQuery.isFetching;
  const catalogError =
    catalogPapersQuery.isError || catalogProjectsQuery.isError;
  const selectionCount = selectedProjects.length + selectedDocuments.length;
  const display = getResearchContextDisplay(context, allPapers, allProjects);
  const displayLabel =
    display.kind === "project" || display.kind === "paper"
      ? display.title
      : display.kind === "papers" || display.kind === "items"
        ? t(display.kind === "papers" ? "scopePapers" : "scopeItems", {
            count: display.count,
          })
        : t(display.kind === "library" ? "scopeLibrary" : "scopeEmpty");
  const accessibleLabel = t("scopeAccessible", { scope: displayLabel });

  function updateSelection(
    field: "project_ids" | "document_ids",
    id: string,
    checked: boolean,
  ) {
    const selection =
      context.kind === "selection"
        ? context
        : { kind: "selection" as const, project_ids: [], document_ids: [] };
    const values = new Set(selection[field]);
    if (checked) values.add(id);
    else values.delete(id);
    onChange({ ...selection, [field]: [...values] });
  }

  return (
    <Popover onOpenChange={onOpenChange} open={open}>
      <PopoverTrigger asChild>
        <button
          aria-label={accessibleLabel}
          className={cn(
            "hover:bg-hover active:bg-pressed grid size-12 shrink-0 place-items-center rounded-full lg:size-11",
            keyboardFocusRing,
            triggerClassName,
          )}
          disabled={disabled}
          title={displayLabel}
          type="button"
        >
          <span className="relative grid size-6 place-items-center">
            <Icon glyph={MentionIcon} size={20} />
            {selectionCount > 0 ? (
              <span
                aria-hidden
                className="bg-primary text-primary-foreground text-caption absolute -top-1.5 -right-2 grid h-4 min-w-4 place-items-center rounded-full px-1 leading-none font-semibold"
              >
                {selectionCount > 9 ? "9+" : selectionCount}
              </span>
            ) : context.kind === "library" ? (
              <span
                aria-hidden
                className="bg-primary border-surface absolute -top-0.5 -right-0.5 size-2 rounded-full border"
              />
            ) : null}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        aria-label={t("title")}
        className="flex max-h-[min(603px,calc(100dvh-9rem))] w-[min(460px,calc(100vw-1.5rem))] flex-col gap-3 overflow-hidden p-3"
        side="bottom"
      >
        <h2 className="text-base font-medium">{t("title")}</h2>
        <div className="bg-subtle flex items-center justify-between rounded-[var(--radius-md)] px-3 py-2.5">
          <label className="text-ui font-medium" htmlFor={librarySwitchId}>
            {t("entireLibrary")}
          </label>
          <Switch
            checked={context.kind === "library"}
            id={librarySwitchId}
            onCheckedChange={(checked) => {
              if (checked) setQuery("");
              onChange(
                checked
                  ? { kind: "library" }
                  : { kind: "selection", project_ids: [], document_ids: [] },
              );
            }}
          />
        </div>
        {context.kind !== "library" ? (
          <>
            <SearchField
              aria-label={t("search")}
              className="h-10"
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("search")}
              value={query}
            />
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
              {visibleProjects.length > 0 && (
                <section className="grid gap-2">
                  <h3 className="text-secondary text-xs">{t("projects")}</h3>
                  {visibleProjects.map((project) => {
                    const checked = selectedProjects.includes(project.id);
                    return (
                      <label
                        className={cn(
                          "hover:bg-hover flex cursor-pointer items-center gap-3 rounded-[var(--radius-sm)] p-2",
                          checked && "bg-subtle",
                        )}
                        key={project.id}
                      >
                        <Checkbox
                          checked={checked}
                          onCheckedChange={(value) =>
                            updateSelection(
                              "project_ids",
                              project.id,
                              value === true,
                            )
                          }
                        />
                        <span className="min-w-0 flex-1">
                          <span className="text-ui block truncate font-medium">
                            {project.title}
                          </span>
                          <span className="text-secondary mt-1 block text-xs">
                            {project.num_papers ?? 0} ·{" "}
                            {project.num_conversations ?? 0}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </section>
              )}
              {visiblePapers.length > 0 && (
                <section className="grid gap-2">
                  <h3 className="text-secondary text-xs">{t("papers")}</h3>
                  {visiblePapers.map((paper) => {
                    const checked = selectedDocuments.includes(
                      paper.document.document_id,
                    );
                    const title =
                      paper.metadata_overrides?.title ??
                      paper.document.title ??
                      paper.document.original_filename;
                    const authors = paper.document.authors
                      ?.slice(0, 2)
                      .join(", ");
                    return (
                      <label
                        className={cn(
                          "hover:bg-hover flex cursor-pointer items-center gap-3 rounded-[var(--radius-sm)] p-2",
                          checked && "bg-subtle",
                        )}
                        key={paper.document.document_id}
                      >
                        <Checkbox
                          checked={checked}
                          onCheckedChange={(value) =>
                            updateSelection(
                              "document_ids",
                              paper.document.document_id,
                              value === true,
                            )
                          }
                        />
                        <span className="min-w-0 flex-1">
                          <span className="text-ui block truncate font-medium">
                            {title}
                          </span>
                          <span className="text-secondary mt-1 block truncate text-xs">
                            {authors ||
                              paper.document.journal ||
                              paper.document.original_filename}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </section>
              )}
              {catalogLoading ? (
                <p
                  aria-live="polite"
                  className="text-muted py-3 text-center text-sm"
                >
                  {t("searching")}
                </p>
              ) : null}
              {catalogError ? (
                <p
                  aria-live="polite"
                  className="text-danger py-3 text-center text-sm"
                >
                  {t("loadError")}
                </p>
              ) : null}
              {!catalogLoading &&
                !catalogError &&
                visibleProjects.length === 0 &&
                visiblePapers.length === 0 && (
                  <p className="text-muted py-8 text-center text-sm">
                    {t("noMatches")}
                  </p>
                )}
            </div>
          </>
        ) : null}
        <div
          className={cn(
            "flex items-center gap-3 pt-1",
            context.kind !== "library" && "border-line border-t pt-3",
          )}
        >
          {context.kind !== "library" ? (
            <span className="text-ui min-w-0 flex-1 font-medium">
              {t("selected", { count: selectionCount })}
            </span>
          ) : (
            <span className="flex-1" />
          )}
          {context.kind === "selection" && selectionCount > 0 && (
            <Button
              className="min-h-9 px-2"
              onClick={() =>
                onChange({
                  kind: "selection",
                  project_ids: [],
                  document_ids: [],
                })
              }
              size="sm"
              variant="ghost"
            >
              {t("clear")}
            </Button>
          )}
          <Button
            className="min-h-9"
            onClick={() => onOpenChange(false)}
            size="sm"
          >
            {t("done")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export function ReasoningMenu({
  className,
  disabled,
  onChange,
  variant = "composer",
  value,
}: {
  className?: string;
  disabled?: boolean;
  onChange: (level: ReasoningLevel) => void;
  variant?: "composer" | "mobileHeader" | "contextPanel";
  value: ReasoningLevel;
}) {
  const t = useTranslations("Home");
  const compactMenu = variant === "mobileHeader" || variant === "contextPanel";

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          aria-label={t("composer.reasoningStrengthValue", {
            value: t(`composer.${value}`),
          })}
          className={cn(
            "hover:bg-hover active:bg-pressed flex min-w-0 items-center gap-1.5 text-sm font-medium",
            compactMenu
              ? "h-11 shrink-0 rounded-[var(--radius-md)] px-3"
              : "h-11 rounded-full px-3",
            keyboardFocusRing,
            className,
          )}
          disabled={disabled}
          type="button"
        >
          <span className="truncate">{t(`composer.${value}`)}</span>
          <span className="grid size-4 shrink-0 place-items-center">
            <Icon glyph={ExpandIcon} size={16} tone="secondary" />
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align={variant === "mobileHeader" ? "start" : "end"}
        className={cn(
          "p-1.5",
          compactMenu ? "w-32" : "w-[min(18rem,calc(100vw-1.5rem))]",
        )}
        sideOffset={compactMenu ? 4 : 8}
      >
        <DropdownMenuRadioGroup
          onValueChange={(nextValue) => onChange(nextValue as ReasoningLevel)}
          value={value}
        >
          {(["standard", "deep"] as const).map((level) => {
            return (
              <DropdownMenuRadioItem
                className={cn(
                  "pr-8 pl-3 [&>span:first-child]:right-3 [&>span:first-child]:left-auto",
                  compactMenu
                    ? "min-h-11 items-center py-2"
                    : "min-h-16 items-start py-2.5",
                )}
                key={level}
                value={level}
              >
                {compactMenu ? (
                  <span className="text-foreground truncate font-medium">
                    {t(`composer.${level}`)}
                  </span>
                ) : (
                  <span className="min-w-0 flex-1">
                    <span className="text-foreground block font-medium">
                      {t(`composer.${level}`)}
                    </span>
                    <span className="text-secondary mt-0.5 block text-xs leading-4">
                      {t(`composer.${level}Description`)}
                    </span>
                  </span>
                )}
              </DropdownMenuRadioItem>
            );
          })}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function ResearchComposer({
  form,
  context,
  papers,
  projects,
  reasoningLevel,
  busy,
  intent = "new",
  onContextChange,
  onReasoningLevelChange,
  onSubmit,
  onStop,
  onTurnContextClear,
  stopAvailable = false,
  surface,
  unavailable,
  turnContextLabel,
}: {
  form?: UseFormReturn<ComposerValues>;
  context: ResearchContext;
  papers: ResearchContextPaperOption[];
  projects: ResearchContextProjectOption[];
  reasoningLevel: ReasoningLevel;
  busy?: boolean;
  intent?: "new" | "follow-up";
  onContextChange: (context: ResearchContext) => void;
  onReasoningLevelChange: (level: ReasoningLevel) => void;
  onSubmit: (message: string) => Promise<void>;
  onStop?: () => void;
  onTurnContextClear?: () => void;
  surface: ResearchComposerSurface;
  unavailable?: boolean;
  stopAvailable?: boolean;
  turnContextLabel?: string;
}) {
  const t = useTranslations("Home");
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const internalForm = useResearchComposerForm();
  const composerForm = form ?? internalForm;
  const messageValue = useWatch({
    control: composerForm.control,
    name: "message",
  });
  const messageRegistration = composerForm.register("message");
  const { focusHandlers, focusOrigin } =
    useTextControlFocus<HTMLTextAreaElement>({
      onBlur: messageRegistration.onBlur,
    });
  const selectionCount =
    context.kind === "selection"
      ? (context.project_ids?.length ?? 0) + (context.document_ids?.length ?? 0)
      : 0;
  const hasContext = Boolean(turnContextLabel) || selectionCount > 0;
  const expanded =
    messageValue.includes("\n") || messageValue.trim().length > 88;
  const contextPanelExpanded = expanded || Boolean(turnContextLabel);

  async function submit(values: ComposerValues) {
    await onSubmit(values.message.trim());
  }

  const placeholder =
    intent === "follow-up"
      ? t("composer.followUpPlaceholder")
      : t("composer.placeholder");

  if (surface === "context-panel") {
    return (
      <form
        className={cn(
          "motion-shape border-line bg-surface shadow-composer lg:shadow-raised grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-1 border p-2",
          contextPanelExpanded
            ? "rounded-[var(--radius-2xl)]"
            : "rounded-[var(--radius-full)]",
        )}
        data-expanded={contextPanelExpanded}
        data-focus-surface
        onSubmit={composerForm.handleSubmit(submit)}
      >
        <textarea
          aria-label={placeholder}
          className={cn(
            "placeholder:text-muted [field-sizing:content] max-h-28 w-full resize-none overflow-y-auto bg-transparent text-sm leading-6 outline-none focus-visible:outline-none",
            contextPanelExpanded
              ? "col-span-3 col-start-1 row-start-1 min-h-11 px-2 py-2"
              : "col-start-2 row-start-1 min-h-9 px-1 py-1.5",
          )}
          data-focus-delegate="surface"
          data-focus-origin={focusOrigin ?? undefined}
          aria-busy={busy || undefined}
          disabled={unavailable}
          readOnly={busy}
          onKeyDown={(event) => {
            if (!busy && event.key === "@") setPickerOpen(true);
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !isImeComposing(event)
            ) {
              event.preventDefault();
              if (!busy) void composerForm.handleSubmit(submit)();
            }
          }}
          placeholder={placeholder}
          rows={1}
          {...messageRegistration}
          {...focusHandlers}
        />
        <div
          className={cn(
            "col-start-1",
            contextPanelExpanded ? "row-start-2" : "row-start-1",
          )}
        >
          <ContextPicker
            context={context}
            disabled={unavailable}
            onChange={onContextChange}
            onOpenChange={setPickerOpen}
            open={pickerOpen}
            papers={papers}
            projects={projects}
            triggerClassName="text-secondary size-9 lg:size-9"
          />
        </div>
        <div
          className={cn(
            "flex min-w-0 items-center gap-1",
            contextPanelExpanded
              ? "col-span-2 col-start-2 row-start-2"
              : "col-start-3 row-start-1",
          )}
        >
          {turnContextLabel ? (
            <span className="bg-subtle text-secondary flex min-w-0 flex-1 items-center gap-1 rounded-full py-1 pr-1 pl-2 text-xs">
              <Icon glyph={DocumentIcon} size={16} tone="secondary" />
              <span className="truncate">{turnContextLabel}</span>
              {onTurnContextClear ? (
                <button
                  aria-label={t("composer.removeTurnContext")}
                  className="hover:bg-hover grid size-6 shrink-0 place-items-center rounded-full"
                  onClick={onTurnContextClear}
                  type="button"
                >
                  <Icon glyph={DismissIcon} size={16} tone="secondary" />
                </button>
              ) : null}
            </span>
          ) : null}
          <ReasoningMenu
            className="border-line bg-subtle ml-auto h-9 shrink-0 rounded-[var(--radius-lg)] border px-2"
            disabled={unavailable}
            onChange={onReasoningLevelChange}
            value={reasoningLevel}
            variant="contextPanel"
          />
          {busy && onStop ? (
            <IconButton
              aria-busy={!stopAvailable || undefined}
              aria-disabled={!stopAvailable || undefined}
              className="size-9 min-h-9 rounded-full"
              label={t(stopAvailable ? "composer.stop" : "composer.pending")}
              onClick={stopAvailable ? onStop : undefined}
              type="button"
            >
              {stopAvailable ? (
                <Icon glyph={StopIcon} size={16} tone="inverse" />
              ) : (
                <span
                  aria-hidden
                  className="motion-spinner size-4 rounded-full border-2 border-current border-r-transparent"
                />
              )}
            </IconButton>
          ) : (
            <IconButton
              className="size-9 min-h-9 rounded-full"
              disabled={!composerForm.formState.isValid || busy || unavailable}
              label={t("composer.submit")}
              type="submit"
            >
              <Icon glyph={SendIcon} size={16} tone="inverse" />
            </IconButton>
          )}
        </div>
      </form>
    );
  }

  return (
    <form
      className={cn(
        "border-line bg-surface shadow-composer lg:shadow-raised grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-end gap-x-1 rounded-full border p-2",
        expanded
          ? "lg:grid-cols-[auto_minmax(0,1fr)_auto_auto] lg:rounded-[var(--radius-2xl)] lg:p-3"
          : "lg:grid-cols-[auto_minmax(0,1fr)_auto_auto] lg:items-center lg:rounded-[var(--radius-full)] lg:p-1.5",
      )}
      data-expanded={expanded}
      data-has-context={hasContext || undefined}
      data-focus-surface
      onSubmit={composerForm.handleSubmit(submit)}
    >
      <textarea
        aria-label={placeholder}
        className={cn(
          "placeholder:text-muted col-start-2 row-start-1 [field-sizing:content] max-h-28 min-h-12 w-full resize-none overflow-y-auto bg-transparent px-1 py-3 text-[17px] leading-6 outline-none focus-visible:outline-none lg:max-h-36 lg:text-sm lg:leading-6",
          expanded
            ? "lg:col-span-4 lg:col-start-1 lg:min-h-14 lg:px-1"
            : "lg:col-span-1 lg:col-start-2 lg:min-h-11 lg:self-center lg:px-1 lg:py-2.5",
        )}
        data-focus-delegate="surface"
        data-focus-origin={focusOrigin ?? undefined}
        data-mobile-composer-input
        aria-busy={busy || undefined}
        disabled={unavailable}
        readOnly={busy}
        onKeyDown={(event) => {
          if (!busy && event.key === "@") setPickerOpen(true);
          if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !isImeComposing(event)
          ) {
            event.preventDefault();
            if (!busy) void composerForm.handleSubmit(submit)();
          }
        }}
        placeholder={placeholder}
        rows={1}
        {...messageRegistration}
        {...focusHandlers}
      />
      {turnContextLabel ? (
        <div
          className={cn(
            "row-start-2 hidden min-w-0 pt-0.5 lg:flex",
            expanded ? "col-span-4 col-start-1" : "col-span-2 col-start-2 pr-2",
          )}
        >
          <span className="bg-subtle text-secondary inline-flex min-w-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-sm lg:text-xs">
            <Icon glyph={DocumentIcon} size={16} tone="secondary" />
            <span className="truncate">{turnContextLabel}</span>
          </span>
        </div>
      ) : null}
      <div
        className={cn(
          "col-start-1 row-start-1",
          expanded
            ? "lg:col-start-1 lg:row-start-3"
            : "lg:col-start-1 lg:row-start-1",
        )}
      >
        <ContextPicker
          context={context}
          disabled={unavailable}
          onChange={onContextChange}
          onOpenChange={setPickerOpen}
          open={pickerOpen}
          papers={papers}
          projects={projects}
          triggerClassName="lg:border-line lg:bg-subtle lg:size-11 lg:border"
        />
      </div>
      <ReasoningMenu
        className={cn(
          "border-line bg-subtle hidden justify-self-start border lg:flex",
          expanded
            ? "lg:col-start-3 lg:row-start-3 lg:justify-self-end"
            : "lg:col-start-3 lg:row-start-1",
        )}
        disabled={unavailable}
        onChange={onReasoningLevelChange}
        value={reasoningLevel}
      />
      {busy && onStop ? (
        <IconButton
          aria-busy={!stopAvailable || undefined}
          aria-disabled={!stopAvailable || undefined}
          className={cn(
            "col-start-3 row-start-1 size-12 rounded-full lg:col-start-4 lg:size-11",
            expanded ? "lg:row-start-3" : "lg:row-start-1",
          )}
          label={t(stopAvailable ? "composer.stop" : "composer.pending")}
          onClick={stopAvailable ? onStop : undefined}
          type="button"
        >
          {stopAvailable ? (
            <Icon glyph={StopIcon} size={20} tone="inverse" />
          ) : (
            <span
              aria-hidden
              className="motion-spinner size-5 rounded-full border-2 border-current border-r-transparent"
            />
          )}
        </IconButton>
      ) : (
        <IconButton
          className={cn(
            "col-start-3 row-start-1 size-12 rounded-full lg:col-start-4 lg:size-11",
            expanded ? "lg:row-start-3" : "lg:row-start-1",
          )}
          disabled={!composerForm.formState.isValid || busy || unavailable}
          label={t("composer.submit")}
          type="submit"
        >
          <Icon glyph={SendIcon} size={20} tone="inverse" />
        </IconButton>
      )}
    </form>
  );
}
