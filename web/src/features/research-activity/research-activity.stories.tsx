import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn } from "storybook/test";

import {
  activityDays,
  paperActivitySummaryFixture,
  paperInsightsFixture,
  personalInsightsFixture,
  projectActivityFixture,
  projectInsightsFixture,
  readingActivityPreferencesFixture,
} from "./fixtures";
import { ActivityTrendChart } from "./components/activity-visualizations";
import { CompactPaperActivity } from "./components/compact-paper-activity";
import { HomeActivitySnapshot } from "./components/home-activity-snapshot";
import { PaperInsightsPanel } from "./components/paper-insights-panel";
import { PersonalActivityDashboard } from "./components/personal-activity-dashboard";
import { ProjectInsightsOverview } from "./components/project-insights-overview";
import { ReadingActivityPreferencesControl } from "./components/reading-activity-preferences-control";
import type { ReadingActivityPreferences } from "./types";

const meta = {
  title: "Features/Research activity/Insights",
  component: PaperInsightsPanel,
  args: {
    insights: paperInsightsFixture,
    onPageSelect: fn(),
    onRetry: fn(),
    recordingEnabled: true,
  },
  render: (args) => (
    <div className="bg-canvas h-screen w-full max-w-[31.25rem] overflow-hidden">
      <PaperInsightsPanel {...args} />
    </div>
  ),
} satisfies Meta<typeof PaperInsightsPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Paper: Story = {};
export const PaperLoading: Story = { args: { loading: true } };
export const PaperEmpty: Story = {
  args: {
    insights: {
      activityHistoryCompleteSince: null,
      daily: [],
      historyPartial: false,
      metricDefinitionVersion: "active-reading-v1",
      pages: [],
      summary: [],
    },
  },
};
export const PaperError: Story = { args: { error: true } };
export const PaperRecordingOff: Story = {
  args: {
    insights: {
      activityHistoryCompleteSince: null,
      daily: [],
      historyPartial: false,
      metricDefinitionVersion: "active-reading-v1",
      pages: [],
      summary: [],
    },
    recordingEnabled: false,
  },
};
export const PaperPartialHistory: Story = {
  args: {
    insights: {
      ...paperInsightsFixture,
      activityHistoryCompleteSince: "2026-07-25T00:00:00Z",
      historyPartial: true,
    },
  },
};
export const PaperNarrowDarkChinese: Story = {
  globals: {
    appearance: "dark",
    locale: "zh-CN",
    viewport: { isRotated: false, value: "smallMobile" },
  },
};

export const Project: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <ProjectInsightsOverview
        activity={projectActivityFixture}
        insights={projectInsightsFixture}
        onRangeChange={fn()}
        onRetry={fn()}
        projectId="50000000-0000-4000-8000-000000000001"
        range="30d"
      />
    </div>
  ),
};

export const ProjectLoading: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <ProjectInsightsOverview
        activity={[]}
        loading
        onRangeChange={fn()}
        onRetry={fn()}
        projectId="50000000-0000-4000-8000-000000000001"
        range="30d"
      />
    </div>
  ),
};

export const ProjectAllTime: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <ProjectInsightsOverview
        activity={projectActivityFixture}
        insights={{
          ...projectInsightsFixture,
          mine: [
            ...projectInsightsFixture.mine,
            { key: "substantive_pages", unit: "count", value: 74 },
            { key: "coverage_percent", unit: "percent", value: 61 },
          ],
          papers: projectInsightsFixture.papers.map((paper, index) => ({
            ...paper,
            coveragePercent: 28 + index * 17,
          })),
          range: "all",
          team: [
            ...projectInsightsFixture.team,
            { key: "substantive_pages", unit: "count", value: 143 },
          ],
        }}
        onRangeChange={fn()}
        onRetry={fn()}
        projectId="50000000-0000-4000-8000-000000000001"
        range="all"
      />
    </div>
  ),
};

export const ProjectTeamSuppressed: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <ProjectInsightsOverview
        activity={projectActivityFixture}
        insights={{
          ...projectInsightsFixture,
          daily: projectInsightsFixture.daily.map((day) => ({
            ...day,
            teamActiveMs: null,
          })),
          team: projectInsightsFixture.team.filter(
            (metric) =>
              metric.key !== "active_ms" &&
              metric.key !== "visible_ms" &&
              metric.key !== "papers_with_activity" &&
              metric.key !== "substantive_pages",
          ),
          teamReadingAvailable: false,
        }}
        onRangeChange={fn()}
        onRetry={fn()}
        projectId="50000000-0000-4000-8000-000000000001"
        range="30d"
      />
    </div>
  ),
};

export const ProjectEmpty: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <ProjectInsightsOverview
        activity={[]}
        insights={{
          activityHistoryCompleteSince: null,
          daily: [],
          historyPartial: false,
          metricDefinitionVersion: "active-reading-v1",
          mine: [],
          papers: [],
          papersTotalCount: 0,
          range: "30d",
          team: [],
          teamReadingAvailable: false,
        }}
        onRangeChange={fn()}
        onRetry={fn()}
        projectId="50000000-0000-4000-8000-000000000001"
        range="30d"
      />
    </div>
  ),
};

export const ProjectError: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <ProjectInsightsOverview
        activity={[]}
        error
        onRangeChange={fn()}
        onRetry={fn()}
        projectId="50000000-0000-4000-8000-000000000001"
        range="30d"
      />
    </div>
  ),
};

export const ProjectActivityError: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <ProjectInsightsOverview
        activity={[]}
        activityError
        insights={projectInsightsFixture}
        onRangeChange={fn()}
        onRetry={fn()}
        projectId="50000000-0000-4000-8000-000000000001"
        range="30d"
      />
    </div>
  ),
};

export const ProjectMobileDark: Story = {
  ...Project,
  globals: {
    appearance: "dark",
    locale: "zh-CN",
    viewport: { isRotated: false, value: "smallMobile" },
  },
  play: async ({ canvasElement }) => {
    const root = canvasElement.ownerDocument.documentElement;
    await expect(root.scrollWidth).toBeLessThanOrEqual(root.clientWidth);
  },
};

export const Personal: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <PersonalActivityDashboard
        insights={personalInsightsFixture}
        onRangeChange={fn()}
        onRetry={fn()}
        range="365d"
        recordingEnabled
      />
    </div>
  ),
};

export const PersonalLoading: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <PersonalActivityDashboard
        loading
        onRangeChange={fn()}
        onRetry={fn()}
        range="365d"
      />
    </div>
  ),
};

export const PersonalPartialHistory: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <PersonalActivityDashboard
        insights={{
          ...personalInsightsFixture,
          activityHistoryCompleteSince: "2026-07-25T00:00:00Z",
          historyPartial: true,
        }}
        onRangeChange={fn()}
        onRetry={fn()}
        range="365d"
        recordingEnabled
      />
    </div>
  ),
};

export const PersonalEmpty: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <PersonalActivityDashboard
        insights={{
          activityHistoryCompleteSince: null,
          daily: [],
          historyPartial: false,
          metricDefinitionVersion: "active-reading-v1",
          papers: [],
          projects: [],
          range: "365d",
          summary: [],
        }}
        onRangeChange={fn()}
        onRetry={fn()}
        range="365d"
        recordingEnabled
      />
    </div>
  ),
};

export const PersonalError: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <PersonalActivityDashboard
        error
        onRangeChange={fn()}
        onRetry={fn()}
        range="365d"
      />
    </div>
  ),
};

export const PersonalRecordingOff: Story = {
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-6xl p-6">
      <PersonalActivityDashboard
        insights={{
          activityHistoryCompleteSince: null,
          daily: [],
          historyPartial: false,
          metricDefinitionVersion: "active-reading-v1",
          papers: [],
          projects: [],
          range: "365d",
          summary: [],
        }}
        onRangeChange={fn()}
        onRetry={fn()}
        range="365d"
        recordingEnabled={false}
      />
    </div>
  ),
};

export const PersonalMobileDark: Story = {
  ...Personal,
  globals: {
    appearance: "dark",
    locale: "zh-CN",
    viewport: { isRotated: false, value: "smallMobile" },
  },
  play: async ({ canvasElement }) => {
    const root = canvasElement.ownerDocument.documentElement;
    await expect(root.scrollWidth).toBeLessThanOrEqual(root.clientWidth);
  },
};

function PreferencesStory({
  error = false,
  pending = false,
  saved = false,
  value = readingActivityPreferencesFixture,
}: {
  error?: boolean;
  pending?: boolean;
  saved?: boolean;
  value?: ReadingActivityPreferences;
}) {
  return (
    <div className="bg-canvas mx-auto min-h-[24rem] max-w-2xl p-6">
      <ReadingActivityPreferencesControl
        error={error}
        onChange={fn()}
        pending={pending}
        saved={saved}
        value={value}
      />
    </div>
  );
}

export const PreferencesDefault: Story = {
  render: () => <PreferencesStory />,
};

export const PreferencesRecordingOff: Story = {
  render: () => (
    <PreferencesStory
      value={{
        ...readingActivityPreferencesFixture,
        recordingEnabled: false,
      }}
    />
  ),
};

export const PreferencesProjectOff: Story = {
  render: () => (
    <PreferencesStory
      value={{
        ...readingActivityPreferencesFixture,
        contributeAnonymousProjectAggregates: false,
      }}
    />
  ),
};

export const PreferencesPending: Story = {
  render: () => <PreferencesStory pending />,
};

export const PreferencesSaved: Story = {
  render: () => <PreferencesStory saved />,
};

export const PreferencesError: Story = {
  render: () => <PreferencesStory error />,
};

export const CompactLibraryActivity: Story = {
  render: () => (
    <div className="bg-canvas w-80 p-6">
      <CompactPaperActivity summary={paperActivitySummaryFixture} />
    </div>
  ),
};

export const HomeSnapshot: Story = {
  render: () => (
    <div className="bg-canvas mx-auto w-full max-w-xl p-6">
      <HomeActivitySnapshot
        insights={{ ...personalInsightsFixture, range: "30d" }}
        onRetry={fn()}
        recordingEnabled
      />
    </div>
  ),
};

export const HomeSnapshotSmallMobile: Story = {
  ...HomeSnapshot,
  globals: {
    viewport: { isRotated: false, value: "smallMobile" },
  },
  play: async ({ canvasElement }) => {
    const root = canvasElement.ownerDocument.documentElement;
    await expect(root.scrollWidth).toBeLessThanOrEqual(root.clientWidth);
  },
};

export const HomeSnapshotResearchOnly: Story = {
  render: () => (
    <div className="bg-canvas mx-auto w-full max-w-xl p-6">
      <HomeActivitySnapshot
        insights={{
          ...personalInsightsFixture,
          daily: [],
          range: "30d",
          summary: [
            { key: "active_ms", unit: "milliseconds", value: 0 },
            { key: "annotations", unit: "count", value: 5 },
            { key: "conversations", unit: "count", value: 2 },
            { key: "outputs", unit: "count", value: 1 },
          ],
        }}
        onRetry={fn()}
        recordingEnabled
      />
    </div>
  ),
};

export const HomeSnapshotEmptyDark: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  render: () => (
    <div className="bg-canvas mx-auto w-full max-w-xl p-6">
      <HomeActivitySnapshot onRetry={fn()} recordingEnabled />
    </div>
  ),
};

export const HomeSnapshotRecordingOff: Story = {
  render: () => (
    <div className="bg-canvas mx-auto w-full max-w-xl p-6">
      <HomeActivitySnapshot onRetry={fn()} recordingEnabled={false} />
    </div>
  ),
};

export const ChartTableLongChinese: Story = {
  globals: { locale: "zh-CN" },
  render: () => (
    <div className="bg-canvas mx-auto min-h-screen max-w-4xl p-6">
      <ActivityTrendChart
        days={activityDays}
        labels={{
          active: "我的主动阅读估算",
          chart: "这篇论文在所选时间范围内的每日主动阅读时间趋势",
          date: "记录日期",
          events: "发生的共享研究事件数量",
          sessions: "阅读次数",
          table: "查看完整的可访问数据表格",
          team: "满足匿名阈值后的项目团队主动阅读估算",
          visible: "前台可见时间",
        }}
        locale="zh-CN"
        showTeam
        tableInitiallyOpen
      />
    </div>
  ),
};
