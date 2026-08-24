"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { LoadingState } from "@/components/feedback";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  Button,
} from "@/components/ui";
import {
  adaptPaperInsights,
  deleteAllReadingActivity,
  deletePaperReadingActivity,
  deleteProjectReadingActivity,
  exportReadingActivity,
  researchActivityKeys,
  researchActivityQueries,
  startReadingSession,
  updateReadingActivityPreferences,
  updateReadingSession,
} from "./api";
import { PaperInsightsPanel } from "./components/paper-insights-panel";
import { PersonalActivityDashboard } from "./components/personal-activity-dashboard";
import { ProjectInsightsOverview } from "./components/project-insights-overview";
import { ReadingActivityPreferencesControl } from "./components/reading-activity-preferences-control";
import { downloadResearchActivityExport } from "./download";
import type { ReadingViewMode } from "./reading-activity-tracker";
import type { ResearchActivityRange } from "./types";
import { useReadingActivityTracker } from "./use-reading-activity-tracker";

function DeleteActivityDialog({
  description,
  error,
  onConfirm,
  onOpenChange,
  open,
  pending,
  title,
}: {
  description: string;
  error: boolean;
  onConfirm: () => Promise<void>;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  pending: boolean;
  title: string;
}) {
  const t = useTranslations("ResearchActivity.deleteDialog");
  return (
    <AlertDialog onOpenChange={onOpenChange} open={open}>
      <AlertDialogContent>
        <AlertDialogTitle>{title}</AlertDialogTitle>
        <AlertDialogDescription>{description}</AlertDialogDescription>
        <p
          aria-live="polite"
          className="text-danger mt-3 min-h-5 text-sm"
          role="status"
        >
          {error ? t("error") : ""}
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <AlertDialogCancel asChild>
            <Button disabled={pending} variant="ghost">
              {t("cancel")}
            </Button>
          </AlertDialogCancel>
          <AlertDialogAction asChild>
            <Button
              loading={pending}
              onClick={(event) => {
                event.preventDefault();
                void onConfirm();
              }}
              variant="danger"
            >
              {t("confirm")}
            </Button>
          </AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function ReadingActivityTracker({
  documentId,
  projectId,
  rootRef,
  viewMode,
}: {
  documentId: string;
  projectId?: string;
  rootRef: React.RefObject<HTMLDivElement | null>;
  viewMode: ReadingViewMode;
}) {
  const preferences = useQuery(researchActivityQueries.preferences());
  useReadingActivityTracker({
    contributionKey: projectId
      ? (preferences.data?.contributeAnonymousProjectAggregates ?? false)
      : false,
    documentId,
    enabled: preferences.isSuccess && preferences.data.recordingEnabled,
    projectId,
    rootRef,
    startSession: startReadingSession,
    updateSession: updateReadingSession,
    viewMode,
  });
  return null;
}

export function PaperInsightsContainer({
  documentId,
  onPageSelect,
  pageCount,
  projectId,
}: {
  documentId: string;
  onPageSelect: (page: number) => void;
  pageCount?: number;
  projectId?: string;
}) {
  const t = useTranslations("ResearchActivity");
  const queryClient = useQueryClient();
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const allTime = useQuery(
    researchActivityQueries.paper(documentId, projectId, "all"),
  );
  const recent = useQuery(
    researchActivityQueries.paper(documentId, projectId, "30d"),
  );
  const preferences = useQuery(researchActivityQueries.preferences());
  const remove = useMutation({
    mutationFn: () => deletePaperReadingActivity(documentId),
    onSuccess: async () => {
      setDeleteOpen(false);
      await queryClient.invalidateQueries({
        queryKey: researchActivityKeys.all,
      });
    },
  });
  const insights =
    allTime.data && recent.data
      ? adaptPaperInsights(allTime.data, recent.data, pageCount)
      : undefined;

  return (
    <>
      <PaperInsightsPanel
        error={allTime.isError || recent.isError}
        insights={insights}
        loading={allTime.isPending || recent.isPending}
        onPageSelect={onPageSelect}
        onRetry={() => {
          void allTime.refetch();
          void recent.refetch();
        }}
        recordingEnabled={preferences.data?.recordingEnabled}
        toolbar={
          <Button onClick={() => setDeleteOpen(true)} size="sm" variant="ghost">
            {t("actions.delete")}
          </Button>
        }
      />
      <DeleteActivityDialog
        description={t("deleteDialog.paperDescription")}
        error={remove.isError}
        onConfirm={() => remove.mutateAsync()}
        onOpenChange={(open) => {
          setDeleteOpen(open);
          if (open) remove.reset();
        }}
        open={deleteOpen}
        pending={remove.isPending}
        title={t("deleteDialog.paperTitle")}
      />
    </>
  );
}

export function ProjectInsightsContainer({
  onRangeChange,
  projectId,
  range,
}: {
  onRangeChange: (range: ResearchActivityRange) => void;
  projectId: string;
  range: ResearchActivityRange;
}) {
  const t = useTranslations("ResearchActivity");
  const queryClient = useQueryClient();
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const insights = useQuery(researchActivityQueries.project(projectId, range));
  const activity = useQuery(researchActivityQueries.projectActivity(projectId));
  const remove = useMutation({
    mutationFn: () => deleteProjectReadingActivity(projectId),
    onSuccess: async () => {
      setDeleteOpen(false);
      await queryClient.invalidateQueries({
        queryKey: researchActivityKeys.all,
      });
    },
  });
  return (
    <>
      <ProjectInsightsOverview
        activity={activity.data ?? []}
        activityError={activity.isError}
        error={insights.isError}
        insights={insights.data}
        loading={insights.isPending}
        onRangeChange={onRangeChange}
        onActivityRetry={() => void activity.refetch()}
        onRetry={() => {
          void insights.refetch();
          void activity.refetch();
        }}
        projectId={projectId}
        range={range}
        toolbar={
          <Button onClick={() => setDeleteOpen(true)} size="sm" variant="ghost">
            {t("actions.deleteProjectContribution")}
          </Button>
        }
      />
      <DeleteActivityDialog
        description={t("deleteDialog.projectDescription")}
        error={remove.isError}
        onConfirm={() => remove.mutateAsync()}
        onOpenChange={(open) => {
          setDeleteOpen(open);
          if (open) remove.reset();
        }}
        open={deleteOpen}
        pending={remove.isPending}
        title={t("deleteDialog.projectTitle")}
      />
    </>
  );
}

export function ReadingActivityPreferencesSettings() {
  const t = useTranslations("ResearchActivity.preferences");
  const queryClient = useQueryClient();
  const preferences = useQuery(researchActivityQueries.preferences());
  const update = useMutation({
    mutationFn: updateReadingActivityPreferences,
    onSuccess: (value) => {
      queryClient.setQueryData(researchActivityKeys.preferences(), value);
    },
  });

  if (preferences.isPending) {
    return <LoadingState label={t("loading")} />;
  }
  if (preferences.isError) {
    return (
      <section aria-labelledby="reading-activity-settings-error" role="alert">
        <h3
          className="text-sm font-semibold"
          id="reading-activity-settings-error"
        >
          {t("errorTitle")}
        </h3>
        <p className="text-secondary mt-1 text-sm leading-6">
          {t("errorDescription")}
        </p>
        <Button
          className="mt-3"
          onClick={() => void preferences.refetch()}
          size="sm"
          variant="secondary"
        >
          {t("retry")}
        </Button>
      </section>
    );
  }
  return (
    <ReadingActivityPreferencesControl
      error={update.isError}
      onChange={(value) => update.mutate(value)}
      pending={update.isPending}
      saved={update.isSuccess}
      value={preferences.data}
    />
  );
}

export function PersonalActivityContainer({
  onRangeChange,
  range,
}: {
  onRangeChange: (range: ResearchActivityRange) => void;
  range: ResearchActivityRange;
}) {
  const t = useTranslations("ResearchActivity");
  const queryClient = useQueryClient();
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const insights = useQuery(researchActivityQueries.personal(range));
  const preferences = useQuery(researchActivityQueries.preferences());
  const remove = useMutation({
    mutationFn: deleteAllReadingActivity,
    onSuccess: async () => {
      setDeleteOpen(false);
      await queryClient.invalidateQueries({
        queryKey: researchActivityKeys.all,
      });
    },
  });
  const exportActivity = useMutation({
    mutationFn: exportReadingActivity,
    onSuccess: downloadResearchActivityExport,
  });

  return (
    <>
      <PersonalActivityDashboard
        error={insights.isError}
        insights={insights.data}
        loading={insights.isPending}
        onRangeChange={onRangeChange}
        onRetry={() => void insights.refetch()}
        range={range}
        recordingEnabled={preferences.data?.recordingEnabled}
        toolbar={
          <div className="grid justify-items-end gap-1">
            <div className="flex flex-wrap items-center gap-1">
              <Button asChild size="sm" variant="ghost">
                <Link
                  href={"/me/settings/display?returnTo=/me/activity" as Route}
                >
                  {t("actions.settings")}
                </Link>
              </Button>
              <Button
                loading={exportActivity.isPending}
                onClick={() => exportActivity.mutate()}
                size="sm"
                variant="ghost"
              >
                {t("actions.export")}
              </Button>
              <Button
                onClick={() => setDeleteOpen(true)}
                size="sm"
                variant="ghost"
              >
                {t("actions.delete")}
              </Button>
            </div>
            <p
              aria-live="polite"
              className="text-danger min-h-5 text-sm"
              role="status"
            >
              {exportActivity.isError ? t("exportError") : ""}
            </p>
          </div>
        }
      />
      <DeleteActivityDialog
        description={t("deleteDialog.allDescription")}
        error={remove.isError}
        onConfirm={() => remove.mutateAsync()}
        onOpenChange={(open) => {
          setDeleteOpen(open);
          if (open) remove.reset();
        }}
        open={deleteOpen}
        pending={remove.isPending}
        title={t("deleteDialog.allTitle")}
      />
    </>
  );
}
