"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AsyncFeedback, LoadingState } from "@/components/feedback";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  Button,
  CursorPagination,
  IconButton,
  SearchField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useToast,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import { AddIcon, ProjectIcon } from "@/design-system/icons/semantic-icons";
import { useAuthSession, type Actor } from "@/features/authentication";
import { conversationQueries } from "@/features/conversation";
import { WorkspaceShell } from "@/features/workspace-shell";
import type { components } from "@/lib/api/generated/schema";
import {
  createProject,
  deleteProject,
  leaveProject,
  projectKeys,
  projectQueries,
  updateProject,
} from "./api";
import { ProjectFormDialog } from "./components/project-form-dialog";
import { ProjectRow } from "./components/project-row";
import {
  parseProjectsSearch,
  serializeProjectsSearch,
  type ProjectsSearchState,
  type ProjectSort,
} from "./project-search";

type Project = components["schemas"]["ProjectResponse"];

function ProjectsEmptyState({
  description,
  title,
}: {
  description: string;
  title: string;
}) {
  return (
    <section
      className="grid min-h-64 place-items-center px-4 py-12 text-center"
      role="status"
    >
      <div className="grid max-w-md justify-items-center">
        <span className="bg-subtle grid size-11 place-items-center rounded-full">
          <Icon glyph={ProjectIcon} size={20} tone="secondary" />
        </span>
        <h2 className="mt-4 text-base font-semibold">{title}</h2>
        <p className="text-secondary mt-1.5 text-sm leading-6">{description}</p>
      </div>
    </section>
  );
}

function SearchControl({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const [input, setInput] = React.useState(value);
  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      if (input !== value) onChange(input);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [input, onChange, value]);
  return (
    <SearchField
      aria-label={label}
      className="bg-subtle hover:border-line rounded-full border-transparent"
      onChange={(event) => setInput(event.currentTarget.value)}
      placeholder={label}
      value={input}
    />
  );
}

export function ProjectsWorkspace({ actor }: { actor: Actor }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const t = useTranslations("Projects");
  const { signOut } = useAuthSession();
  const state = React.useMemo(
    () => parseProjectsSearch(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const [collapsed, setCollapsed] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const [formState, setFormState] = React.useState<
    { mode: "create" } | { mode: "edit"; project: Project } | null
  >(null);
  const [destructive, setDestructive] = React.useState<{
    action: "delete" | "leave";
    project: Project;
  } | null>(null);
  const projectsQuery = useQuery(projectQueries.list(state));
  const conversationsQuery = useQuery(conversationQueries.list());

  const replaceSearch = React.useCallback(
    (patch: Partial<ProjectsSearchState>) => {
      const next = serializeProjectsSearch({ ...state, ...patch }).toString();
      router.replace((next ? `/projects?${next}` : "/projects") as Route, {
        scroll: false,
      });
    },
    [router, state],
  );

  const createMutation = useMutation({
    mutationFn: createProject,
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
      router.push(`/projects/${project.id}` as Route);
    },
  });
  const updateMutation = useMutation({
    mutationFn: ({
      projectId,
      value,
    }: {
      projectId: string;
      value: { title: string; description: string | null };
    }) => updateProject(projectId, value),
    onSuccess: async (project) => {
      queryClient.setQueryData(projectKeys.detail(project.id), project);
      await queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
    },
  });
  const deleteMutation = useMutation({
    mutationFn: deleteProject,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
      setDestructive(null);
    },
  });
  const leaveMutation = useMutation({
    mutationFn: leaveProject,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: projectKeys.lists() });
      setDestructive(null);
    },
  });

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await signOut();
      router.replace("/login");
    } finally {
      setSigningOut(false);
    }
  }

  async function confirmDestructive() {
    if (!destructive) return;
    try {
      if (destructive.action === "delete")
        await deleteMutation.mutateAsync(destructive.project.id);
      else await leaveMutation.mutateAsync(destructive.project.id);
    } catch {
      toast.notify({ title: t("feedback.actionFailed") });
    }
  }

  const pendingDestructive =
    deleteMutation.isPending || leaveMutation.isPending;

  return (
    <WorkspaceShell
      activeDestination="projects"
      actor={actor}
      collapsed={collapsed}
      conversations={conversationsQuery.data?.items ?? []}
      mobileHeaderCenter={
        <span className="block truncate text-base font-semibold">
          {t("title")}
        </span>
      }
      mobileHeaderTrailing={
        <IconButton
          label={t("actions.create")}
          onClick={() => setFormState({ mode: "create" })}
          variant="ghost"
        >
          <Icon glyph={AddIcon} size={24} />
        </IconButton>
      }
      onCollapsedChange={setCollapsed}
      onSignOut={handleSignOut}
      signingOut={signingOut}
    >
      <div className="mx-auto w-full max-w-6xl min-w-0 px-4 pt-5 pb-12 sm:px-6 lg:px-10 lg:pt-6">
        <header className="hidden min-h-11 items-center justify-between gap-6 lg:flex">
          <h1 className="text-2xl font-semibold tracking-[-0.02em]">
            {t("title")}
          </h1>
          <Button onClick={() => setFormState({ mode: "create" })}>
            <Icon glyph={AddIcon} size={20} tone="inverse" />
            {t("actions.create")}
          </Button>
        </header>

        <div className="mt-0 grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem] lg:mt-4">
          <SearchControl
            key={state.query}
            label={t("search")}
            onChange={(query) => replaceSearch({ cursor: undefined, query })}
            value={state.query}
          />
          <Select
            onValueChange={(sort: ProjectSort) =>
              replaceSearch({ cursor: undefined, sort })
            }
            value={state.sort}
          >
            <SelectTrigger
              aria-label={t("sort.label")}
              className="bg-subtle hover:border-line rounded-full border-transparent"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="activity_desc">{t("sort.updated")}</SelectItem>
              <SelectItem value="title_asc">{t("sort.title")}</SelectItem>
              <SelectItem value="papers_desc">{t("sort.papers")}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="mt-5">
          {projectsQuery.isPending ? (
            <div className="grid gap-6 px-3 py-4">
              <LoadingState label={t("feedback.loading")} />
            </div>
          ) : projectsQuery.isError ? (
            <AsyncFeedback
              action={{
                label: t("feedback.retry"),
                onClick: () => void projectsQuery.refetch(),
              }}
              description={t("feedback.errorDescription")}
              presentation="inline"
              state="error"
              title={t("feedback.errorTitle")}
            />
          ) : projectsQuery.data.items.length === 0 ? (
            <ProjectsEmptyState
              description={
                state.query
                  ? t("empty.searchDescription")
                  : t("empty.description")
              }
              title={state.query ? t("empty.searchTitle") : t("empty.title")}
            />
          ) : (
            <>
              <div className="divide-line-subtle divide-y">
                {projectsQuery.data.items.map((project) => (
                  <ProjectRow
                    key={project.id}
                    onDelete={(value) =>
                      setDestructive({ action: "delete", project: value })
                    }
                    onEdit={(value) =>
                      setFormState({ mode: "edit", project: value })
                    }
                    onLeave={(value) =>
                      setDestructive({ action: "leave", project: value })
                    }
                    project={project}
                  />
                ))}
              </div>
              {(projectsQuery.data.previous_cursor ||
                projectsQuery.data.next_cursor) && (
                <div className="mt-6 flex justify-end">
                  <CursorPagination
                    nextDisabled={!projectsQuery.data.next_cursor}
                    nextLabel={t("pagination.next")}
                    onNext={() =>
                      projectsQuery.data.next_cursor &&
                      replaceSearch({ cursor: projectsQuery.data.next_cursor })
                    }
                    onPrevious={() =>
                      projectsQuery.data.previous_cursor &&
                      replaceSearch({
                        cursor: projectsQuery.data.previous_cursor,
                      })
                    }
                    previousDisabled={!projectsQuery.data.previous_cursor}
                    previousLabel={t("pagination.previous")}
                  />
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <ProjectFormDialog
        initialValue={
          formState?.mode === "edit"
            ? {
                description: formState.project.description ?? "",
                title: formState.project.title,
              }
            : undefined
        }
        mode={formState?.mode ?? "create"}
        onOpenChange={(open) => !open && setFormState(null)}
        onSubmit={(value) =>
          formState?.mode === "edit"
            ? updateMutation.mutateAsync({
                projectId: formState.project.id,
                value,
              })
            : createMutation.mutateAsync(value)
        }
        open={Boolean(formState)}
      />

      <AlertDialog
        onOpenChange={(open) => !open && setDestructive(null)}
        open={Boolean(destructive)}
      >
        <AlertDialogContent>
          <AlertDialogTitle>
            {t(`confirm.${destructive?.action ?? "delete"}.title`)}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t(`confirm.${destructive?.action ?? "delete"}.description`, {
              title: destructive?.project.title ?? "",
            })}
          </AlertDialogDescription>
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialogCancel asChild>
              <Button variant="secondary">{t("confirm.cancel")}</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                loading={pendingDestructive}
                onClick={() => void confirmDestructive()}
                variant="danger"
              >
                {t(`confirm.${destructive?.action ?? "delete"}.action`)}
              </Button>
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </WorkspaceShell>
  );
}

export function ProjectsPage() {
  const router = useRouter();
  const t = useTranslations("Projects.session");
  const session = useAuthSession();

  React.useEffect(() => {
    if (session.status === "anonymous") {
      router.replace(`/login?returnTo=${encodeURIComponent("/projects")}`);
    }
  }, [router, session.status]);

  if (session.status === "bootstrapping" || session.status === "anonymous") {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <div className="w-full max-w-sm">
          <LoadingState label={t("checking")} />
        </div>
      </main>
    );
  }
  if (session.status === "unavailable") {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <AsyncFeedback
          action={{ label: t("retry"), onClick: session.retryBootstrap }}
          description={t("unavailableDescription")}
          state="offline"
          title={t("unavailableTitle")}
        />
      </main>
    );
  }
  if (!session.actor) return null;
  return <ProjectsWorkspace actor={session.actor} />;
}
