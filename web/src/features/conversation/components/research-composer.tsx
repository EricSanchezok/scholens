"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  ArrowUp,
  AtSign,
  NavArrowDown,
  Page,
  Square,
  Xmark,
} from "iconoir-react";
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
import { composerSchema, type ComposerValues } from "../schemas";

type LibraryPaper = components["schemas"]["LibraryPaperResponse"];
type Project = components["schemas"]["ProjectResponse"];
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
  papers: ReadonlyArray<{
    document: {
      document_id: string;
      original_filename: string;
      title?: string | null;
    };
    metadata_overrides?: { title?: string | null } | null;
  }>,
  projects: ReadonlyArray<{ id: string; title: string }>,
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

function ContextPicker({
  context,
  papers,
  projects,
  onChange,
  open,
  onOpenChange,
  disabled,
}: {
  context: ResearchContext;
  papers: LibraryPaper[];
  projects: Project[];
  onChange: (context: ResearchContext) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("Home.context");
  const librarySwitchId = React.useId();
  const [query, setQuery] = React.useState("");
  const selectedProjects =
    context.kind === "selection" ? (context.project_ids ?? []) : [];
  const selectedDocuments =
    context.kind === "selection" ? (context.document_ids ?? []) : [];
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleProjects = projects.filter((project) =>
    project.title.toLocaleLowerCase().includes(normalizedQuery),
  );
  const visiblePapers = papers.filter((paper) =>
    (paper.metadata_overrides.title ?? paper.document.title ?? "")
      .toLocaleLowerCase()
      .includes(normalizedQuery),
  );
  const selectionCount = selectedProjects.length + selectedDocuments.length;
  const display = getResearchContextDisplay(context, papers, projects);
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
          )}
          disabled={disabled}
          title={displayLabel}
          type="button"
        >
          <Icon glyph={AtSign} size={20} />
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
            onCheckedChange={(checked) =>
              onChange(
                checked
                  ? { kind: "library" }
                  : { kind: "selection", project_ids: [], document_ids: [] },
              )
            }
          />
        </div>
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
                      disabled={context.kind === "library"}
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
                        {project.num_papers} · {project.num_conversations}
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
                  paper.metadata_overrides.title ??
                  paper.document.title ??
                  paper.document.original_filename;
                const authors = paper.document.authors?.slice(0, 2).join(", ");
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
                      disabled={context.kind === "library"}
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
          {visibleProjects.length === 0 && visiblePapers.length === 0 && (
            <p className="text-muted py-8 text-center text-sm">
              {t("noMatches")}
            </p>
          )}
        </div>
        <div className="border-line flex items-center gap-3 border-t pt-3">
          <span className="text-ui min-w-0 flex-1 font-medium">
            {context.kind === "library"
              ? t("librarySelected")
              : t("selected", { count: selectionCount })}
          </span>
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
            <Icon glyph={NavArrowDown} size={16} tone="secondary" />
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
  surface,
  unavailable,
  contextLocked = false,
  contextLabel,
  turnContextLabel,
}: {
  form?: UseFormReturn<ComposerValues>;
  context: ResearchContext;
  papers: LibraryPaper[];
  projects: Project[];
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
  contextLocked?: boolean;
  contextLabel?: string;
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
  const expanded =
    selectionCount > 0 ||
    messageValue.includes("\n") ||
    messageValue.trim().length > 88;

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
        className="border-line bg-surface grid w-full gap-1.5 rounded-[var(--radius-xl)] border p-2 shadow-sm"
        data-focus-surface
        onSubmit={composerForm.handleSubmit(submit)}
      >
        <textarea
          aria-label={placeholder}
          className="placeholder:text-muted [field-sizing:content] max-h-28 min-h-11 w-full resize-none overflow-y-auto bg-transparent px-2 py-2 text-sm leading-6 outline-none focus-visible:outline-none"
          data-focus-delegate="surface"
          data-focus-origin={focusOrigin ?? undefined}
          disabled={busy || unavailable}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void composerForm.handleSubmit(submit)();
            }
          }}
          placeholder={placeholder}
          rows={1}
          {...messageRegistration}
          {...focusHandlers}
        />
        <div className="flex min-w-0 items-center gap-1">
          <div
            aria-label={contextLabel}
            className="text-secondary grid size-9 shrink-0 place-items-center rounded-full"
            role="img"
            title={contextLabel}
          >
            <Icon glyph={AtSign} size={20} tone="secondary" />
          </div>
          {turnContextLabel ? (
            <span className="bg-subtle text-secondary flex max-w-[45%] min-w-0 items-center gap-1 rounded-full py-1 pr-1 pl-2 text-xs">
              <Icon glyph={Page} size={16} tone="secondary" />
              <span className="truncate">{turnContextLabel}</span>
              {onTurnContextClear ? (
                <button
                  aria-label={t("composer.removeTurnContext")}
                  className="hover:bg-hover grid size-6 shrink-0 place-items-center rounded-full"
                  onClick={onTurnContextClear}
                  type="button"
                >
                  <Icon glyph={Xmark} size={16} tone="secondary" />
                </button>
              ) : null}
            </span>
          ) : null}
          <ReasoningMenu
            className="ml-auto h-9 px-2"
            disabled={unavailable}
            onChange={onReasoningLevelChange}
            value={reasoningLevel}
            variant="contextPanel"
          />
          {busy && onStop ? (
            <IconButton
              className="size-9 min-h-9 rounded-full"
              label={t("composer.stop")}
              onClick={onStop}
              type="button"
            >
              <Icon glyph={Square} size={16} tone="inverse" />
            </IconButton>
          ) : (
            <IconButton
              className="size-9 min-h-9 rounded-full"
              disabled={!composerForm.formState.isValid || busy || unavailable}
              label={t("composer.submit")}
              type="submit"
            >
              <Icon glyph={ArrowUp} size={16} tone="inverse" />
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
        "max-w-[760px]",
        expanded
          ? "lg:grid-cols-[auto_minmax(0,1fr)_auto_auto] lg:rounded-[var(--radius-2xl)] lg:p-3"
          : "lg:grid-cols-[auto_minmax(0,1fr)_auto_auto] lg:items-center lg:rounded-[var(--radius-full)] lg:p-2",
      )}
      data-expanded={expanded}
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
        disabled={busy || unavailable}
        onKeyDown={(event) => {
          if (event.key === "@") setPickerOpen(true);
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            void composerForm.handleSubmit(submit)();
          }
        }}
        placeholder={placeholder}
        rows={1}
        {...messageRegistration}
        {...focusHandlers}
      />
      {turnContextLabel ||
      (context.kind === "selection" && selectionCount > 0) ? (
        <div className="col-span-4 row-start-2 hidden flex-wrap gap-1.5 lg:flex">
          <span className="bg-subtle text-secondary inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm lg:text-xs">
            <Icon glyph={Page} size={16} tone="secondary" />
            {turnContextLabel ??
              t("context.selectionSummary", { count: selectionCount })}
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
        {contextLocked ? (
          <div
            aria-label={contextLabel}
            className="text-secondary grid size-12 shrink-0 place-items-center rounded-full lg:size-11"
            role="img"
            title={contextLabel}
          >
            <Icon glyph={Page} size={20} tone="secondary" />
          </div>
        ) : (
          <ContextPicker
            context={context}
            disabled={unavailable}
            onChange={onContextChange}
            onOpenChange={setPickerOpen}
            open={pickerOpen}
            papers={papers}
            projects={projects}
          />
        )}
      </div>
      <ReasoningMenu
        className={cn(
          "hidden justify-self-start lg:flex",
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
          className={cn(
            "col-start-3 row-start-1 size-12 rounded-full lg:col-start-4 lg:size-11",
            expanded ? "lg:row-start-3" : "lg:row-start-1",
          )}
          label={t("composer.stop")}
          onClick={onStop}
          type="button"
        >
          <Icon glyph={Square} size={20} tone="inverse" />
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
          <Icon glyph={ArrowUp} size={20} tone="inverse" />
        </IconButton>
      )}
    </form>
  );
}
