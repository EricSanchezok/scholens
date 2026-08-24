import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ComponentProps } from "react";
import {
  expect,
  fireEvent,
  fn,
  userEvent,
  waitFor,
  within,
} from "storybook/test";

import {
  expectLayeredKeyboardFocus,
  focusWithKeyboard,
  readFocusVisual,
} from "@/components/ui/focus-contract.story-test";
import type { components } from "@/lib/api/generated/schema";
import type { LiveTurn } from "@/features/conversation";
import {
  ConversationLiveStore,
  ConversationView,
  type ConversationResponseVariant,
  type ConversationTurn,
} from "@/features/conversation";
import { homePapers, homeProjects, homeTurns } from "../api/fixtures";

type ReferenceBundle = components["schemas"]["ReferenceBundle"];

const turnId = "51000000-0000-4000-8000-000000000001";
const responseId = "41000000-0000-4000-8000-000000000001";

function response(
  overrides: Partial<ConversationResponseVariant> = {},
): ConversationResponseVariant {
  return {
    id: responseId,
    variant_index: 1,
    status: "completed",
    content: "Today is Wednesday, August 5, 2026.",
    references: null,
    artifacts: null,
    trace: null,
    ...overrides,
  };
}

function turn(
  overrides: Partial<ConversationTurn> & {
    responses?: ConversationResponseVariant[];
  } = {},
): ConversationTurn {
  const responses = overrides.responses ?? [response()];
  return {
    branch: { count: 1, index: 1 },
    depth: 1,
    id: turnId,
    user_query: "What day is it today?",
    locale: "en",
    time_zone: "Asia/Shanghai",
    reasoning_level: "standard",
    paper_context: { kind: "library" },
    parent_turn_id: null,
    contexts: [],
    selected_response_id: responses.at(-1)?.id ?? null,
    suggestions: [
      "What is tomorrow’s date?",
      "Which time zone are you using?",
      "Show this week as a calendar.",
    ],
    ...overrides,
    responses,
  };
}

const researchContent = `# 思维链压缩技术调研

思维链压缩关注如何在保留复杂推理能力的同时，减少中间推理步骤、延迟和推理成本。

## 主要研究方向

1. **短推理轨迹训练**：使用质量筛选或蒸馏，让模型学习更短但仍然可靠的推理路径。
2. **隐式推理表示**：把部分自然语言推理转移到隐藏状态，减少生成 token 的数量。
3. **动态推理预算**：根据问题难度决定推理深度，避免简单问题使用固定的长链路。

## 评估时需要注意

- 不能只比较输出长度，还要检查答案正确率和校准程度。
- 对数学、代码和开放式研究问题应分别评估。`;

const mathematicalResearchContent = [
  researchContent,
  "",
  "## 评测公式",
  "",
  String.raw`内联预算可写为 $B(x)=\mathbb{E}[T\mid x]$，条件质量为 \(Q(y \mid x)\)。`,
  "",
  "$$",
  String.raw`S = \sum_{i=1}^{n} w_i q_i`,
  "$$",
  "",
  String.raw`\[`,
  String.raw`\operatorname{score}(m)=\frac{\Delta q_m}{\Delta c_m}`,
  String.raw`\]`,
].join("\n");

const searchActivity = {
  kind: "activity" as const,
  id: "search-1",
  sequence: 1,
  category: "search" as const,
  state: "succeeded" as const,
  subject: "chain-of-thought compression for efficient language models",
  source_count: 3,
  artifact_count: 0,
};

const readActivity = {
  kind: "activity" as const,
  id: "read-2",
  sequence: 2,
  category: "read" as const,
  state: "succeeded" as const,
  subject: "Reasoning Efficiently: Models, Methods, and Open Questions",
  source_count: 2,
  artifact_count: 0,
};

const researchTrace = {
  entries: [searchActivity, readActivity],
  citation_summary: {
    source_count: 3,
    annotation_count: 2,
    rejected_source_count: 0,
  },
};

const researchReferences: ReferenceBundle = {
  annotations: [
    {
      start_offset: researchContent.indexOf("思维链压缩关注"),
      end_offset:
        researchContent.indexOf("思维链压缩关注") + "思维链压缩".length,
      source_keys: [1],
    },
  ],
  sources: homePapers.slice(0, 3).map((paper, index) => ({
    key: index + 1,
    kind: "document" as const,
    document_id: paper.document.document_id,
    title: paper.document.title,
    authors: paper.document.authors ?? [],
    reference: `第 ${index + 1} 个研究依据`,
    locator: { section: "Introduction" },
  })),
};

function researchTurn(overrides: Partial<ConversationTurn> = {}) {
  return turn({
    id: "51000000-0000-4000-8000-000000000011",
    user_query: "帮我调研一下思维链压缩技术",
    locale: "zh-CN",
    selected_response_id: "41000000-0000-4000-8000-000000000011",
    suggestions: [
      "比较三种主流压缩路线",
      "如何设计统一评测？",
      "列出值得阅读的论文",
    ],
    responses: [
      response({
        id: "41000000-0000-4000-8000-000000000011",
        content: researchContent,
        references: researchReferences,
        trace: researchTrace,
      }),
    ],
    ...overrides,
  });
}

function liveTurn(overrides: Partial<LiveTurn> = {}) {
  return new ConversationLiveStore({
    turnId: "52000000-0000-4000-8000-000000000001",
    responseId: "42000000-0000-4000-8000-000000000001",
    variantIndex: null,
    generationKind: "initial",
    userMessage: "Compare the strongest reasoning-compression approaches.",
    content: "",
    entries: [],
    answerCandidate: null,
    provisionalItems: [],
    completedItemIds: [],
    trace: null,
    references: null,
    suggestions: null,
    readyTurn: null,
    failure: null,
    depth: 1,
    durationMs: null,
    startedAtMs: Date.now() - 4_000,
    phase: "working",
    connectionState: "connected",
    stopFailure: false,
    ...overrides,
  });
}

function responseReadyLiveTurn(suggestions: string[] | null) {
  const canonicalResponse = response({
    id: "42000000-0000-4000-8000-000000000001",
    content: "The answer is ready without waiting for a refetch.",
  });
  const canonicalTurn = turn({
    id: "52000000-0000-4000-8000-000000000001",
    user_query: "Compare the strongest reasoning-compression approaches.",
    selected_response_id: canonicalResponse.id,
    suggestions,
    responses: [canonicalResponse],
  });
  return liveTurn({
    variantIndex: 1,
    content: canonicalResponse.content ?? "",
    readyTurn: canonicalTurn,
    suggestions,
    phase: "ready",
  });
}

const meta = {
  title: "Features/Home/Conversation View",
  component: ConversationView,
  args: {
    layout: "workspace",
    turns: homeTurns,
    liveTurn: new ConversationLiveStore(),
    context: { kind: "library" },
    papers: homePapers,
    projects: homeProjects,
    reasoningLevel: "standard",
    onContextChange: fn(),
    onReasoningLevelChange: fn(),
    onSubmit: fn(async () => undefined),
    onStop: fn(),
    onRetry: fn(),
    onRetryResponse: fn(),
    onEditMessage: fn(async () => undefined),
    onSelectBranch: fn(),
    onSelectResponse: fn(),
    onUseSuggestion: fn(),
    canSend: true,
    stopAvailable: false,
  },
  decorators: [
    (Story) => (
      <main className="h-dvh overflow-y-auto">
        <Story />
      </main>
    ),
  ],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ConversationView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const DirectAnswer: Story = {
  args: { turns: [turn()] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("heading", { level: 1 })).toBeNull();
    await expect(canvas.getByText(/Today is Wednesday/)).toBeVisible();
    await expect(
      canvas.queryByText(/Research complete/),
    ).not.toBeInTheDocument();
  },
};

export const InlineLinkFocus: Story = {
  args: {
    turns: [
      turn({
        responses: [
          response({
            content:
              "Review the [research note](https://example.com/research-note) before continuing.",
          }),
        ],
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const link = within(canvasElement).getByRole("link", {
      name: "research note",
    });
    const resting = readFocusVisual(link);
    await focusWithKeyboard(link);
    await expectLayeredKeyboardFocus({ element: link, resting });
  },
};

export const LatestAnswerActions: Story = {
  args: { turns: [turn()], onRetryResponse: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByRole("button", { name: "Copy answer" })).toBeVisible(),
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "Try another response" }),
    );
    await expect(args.onRetryResponse).toHaveBeenCalledTimes(1);
  },
};

export const EditableHistoricalPrompt: Story = {
  args: {
    turns: [turn()],
    onEditMessage: fn(async () => undefined),
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit message" }));
    const editor = canvas.getByRole("textbox", { name: "Message text" });
    await userEvent.clear(editor);
    await userEvent.type(editor, "What date is it today?");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(args.onEditMessage).toHaveBeenCalledWith(
      expect.objectContaining({ id: turnId }),
      "What date is it today?",
    );
  },
};

export const EditRequestRejectedPreservesDraft: Story = {
  args: {
    turns: [turn()],
    onEditMessage: fn(async () => {
      throw new globalThis.Error("request rejected before start");
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit message" }));
    const editor = canvas.getByRole("textbox", { name: "Message text" });
    await userEvent.clear(editor);
    await userEvent.type(editor, "Keep this edited draft");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(canvas.getByText(/Your edit is still here/)).toBeVisible();
    await expect(editor).toHaveValue("Keep this edited draft");
    await expect(editor).toHaveFocus();
  },
};

export const PromptBranchPager: Story = {
  args: {
    turns: [
      turn({
        branch: {
          count: 2,
          index: 2,
          previous_turn_id: "51000000-0000-4000-8000-000000000099",
        },
        user_query: "What date is it today?",
      }),
    ],
    onSelectBranch: fn(),
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Message 2 of 2")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", {
        name: "Previous version of this message",
      }),
    );
    await expect(args.onSelectBranch).toHaveBeenCalledWith(
      "51000000-0000-4000-8000-000000000099",
    );
  },
};

export const TimedDirectAnswer: Story = {
  args: {
    turns: [
      turn({
        responses: [response({ duration_ms: 21_400 })],
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const worklog = canvasElement.querySelector('[data-state="ready"]');
    await expect(worklog).not.toBeNull();
    await expect(worklog).toHaveTextContent(/Research complete.*21s/);
    await expect(canvas.queryByRole("status")).not.toBeInTheDocument();
  },
};

export const FailedLeafAfterRefresh: Story = {
  args: {
    turns: [
      turn({
        responses: [
          response({
            content: null,
            duration_ms: 4_800,
            status: "failed",
          }),
        ],
        suggestions: null,
      }),
    ],
    onRetryResponse: fn(),
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByText("Could not complete")).toBeVisible(),
    );
    const worklog = canvasElement.querySelector('[data-state="error"]');
    await expect(worklog).not.toBeNull();
    await expect(worklog).toHaveTextContent("Could not complete · 4s");
    await userEvent.click(
      canvas.getByRole("button", { name: "Try another response" }),
    );
    await expect(args.onRetryResponse).toHaveBeenCalledTimes(1);
  },
};

export const SubmissionPendingHidesLatestOnlyControls: Story = {
  args: { turns: [turn()], submissionPending: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByRole("button", { name: "Copy answer" })).toBeVisible(),
    );
    await expect(
      canvas.queryByRole("button", { name: "Try another response" }),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByRole("region", { name: "Suggested follow-up questions" }),
    ).not.toBeInTheDocument();
  },
};

export const RetriedResponseVersions: Story = {
  args: {
    turns: [
      turn({
        selected_response_id: "41000000-0000-4000-8000-000000000002",
        responses: [
          response(),
          response({
            id: "41000000-0000-4000-8000-000000000002",
            variant_index: 2,
            content: "The regenerated answer is Wednesday.",
          }),
        ],
      }),
    ],
    onSelectResponse: fn(),
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByLabelText("Response 2 of 2")).toBeVisible(),
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "Previous response" }),
    );
    await expect(args.onSelectResponse).toHaveBeenCalledWith(
      turnId,
      responseId,
    );
  },
};

export const HistoricalAnswerHasNoRetry: Story = {
  args: {
    turns: [
      turn(),
      turn({
        id: "51000000-0000-4000-8000-000000000002",
        depth: 2,
        parent_turn_id: turnId,
        user_query: "And tomorrow?",
        selected_response_id: "41000000-0000-4000-8000-000000000003",
        suggestions: null,
        responses: [
          response({
            id: "41000000-0000-4000-8000-000000000003",
            content: "Tomorrow is Thursday.",
          }),
        ],
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getAllByRole("button", { name: "Try another response" }),
    ).toHaveLength(1);
    await expect(
      canvas.queryByLabelText("Response 1 of 1"),
    ).not.toBeInTheDocument();
  },
};

export const SuggestedFollowUps: Story = {
  args: { turns: [turn()], onUseSuggestion: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const suggestion = canvas.getByRole("button", {
      name: "What is tomorrow’s date?",
    });
    await userEvent.click(suggestion);
    await expect(args.onUseSuggestion).toHaveBeenCalledWith(
      "What is tomorrow’s date?",
    );
    await expect(
      canvas.queryByText("Suggested follow-up questions"),
    ).not.toBeInTheDocument();
    await expect(suggestion.querySelector("svg")).toBeNull();
    await expect(args.onSubmit).not.toHaveBeenCalled();
    const answer = canvas.getByText("Today is Wednesday, August 5, 2026.");
    const suggestionStyle = window.getComputedStyle(suggestion);
    const suggestionLabelLeft =
      suggestion.getBoundingClientRect().left +
      Number.parseFloat(suggestionStyle.paddingLeft);
    await expect(
      Math.abs(suggestionLabelLeft - answer.getBoundingClientRect().left),
    ).toBeLessThanOrEqual(1);
    suggestion.blur();
  },
};

export const MobileAnswerRhythm: Story = {
  globals: { locale: "zh-CN", viewport: { value: "mobile", isRotated: false } },
  args: {
    turns: [
      turn({
        locale: "zh-CN",
        user_query: "Scholens 可以怎样帮助我整理研究？",
        suggestions: [
          "先帮我建立一份阅读清单",
          "比较资料库里的三篇论文",
          "把研究重点整理成一个项目",
        ],
        responses: [
          response({
            content:
              "Scholens 可以帮你检索论文、整理阅读清单，并把研究资料组织进项目。",
          }),
        ],
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByRole("group", { name: "回答操作" })).toBeVisible(),
    );
    await expect(
      canvas.getByRole("region", { name: "建议的后续问题" }),
    ).toBeVisible();
  },
};

export const ResponseReadyWithSuggestions: Story = {
  args: {
    turns: [],
    liveTurn: responseReadyLiveTurn([
      "Compare the latency of each approach.",
      "Show the evaluation criteria.",
      "Which papers should I read first?",
    ]),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(
        canvas.getByRole("group", { name: "Answer actions" }),
      ).toBeVisible(),
    );
    await expect(
      canvas.getByRole("button", {
        name: "Compare the latency of each approach.",
      }),
    ).toBeVisible();
  },
};

export const ResponseReadyBeforeSuggestions: Story = {
  args: {
    turns: [],
    liveTurn: responseReadyLiveTurn(null),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(
        canvas.getByRole("group", { name: "Answer actions" }),
      ).toBeVisible(),
    );
    await expect(
      canvas.queryByRole("region", { name: "Suggested follow-up questions" }),
    ).not.toBeInTheDocument();
  },
};

export const RetryInProgress: Story = {
  args: {
    turns: [turn()],
    liveTurn: liveTurn({
      turnId,
      generationKind: "retry",
      provisionalItems: [
        {
          id: "assistant:retry:1",
          sequence: 1,
          phase: "provisional",
          content: "I’m checking the evidence again before answering.",
        },
      ],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("I’m checking the evidence again before answering."),
    ).toBeVisible();
    await expect(canvas.getAllByText("What day is it today?")).toHaveLength(1);
    await expect(
      canvas.queryByRole("button", { name: "Try another response" }),
    ).not.toBeInTheDocument();
  },
};

export const RetryFailed: Story = {
  args: {
    turns: [turn()],
    liveTurn: liveTurn({
      turnId,
      generationKind: "retry",
      phase: "error",
      failure: {
        code: "research_service_unavailable",
        kind: "unavailable",
        retryable: true,
        diagnosticId: "diagnostic-retry-123",
      },
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByRole("status")).toHaveTextContent(
        /Research service is temporarily unavailable/,
      ),
    );
    await expect(canvas.getAllByText("What day is it today?")).toHaveLength(1);
  },
};

export const MobileResearchAnswer: Story = {
  globals: { locale: "zh-CN", viewport: { value: "mobile", isRotated: false } },
  args: { turns: [researchTurn()] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: "思维链压缩技术调研" }),
    ).toBeVisible();
    await expect(canvas.getByText("主要研究方向")).toBeVisible();
  },
};

export const MobileResearchAnswerDark: Story = {
  ...MobileResearchAnswer,
  globals: {
    appearance: "dark",
    locale: "zh-CN",
    viewport: { value: "largeMobile", isRotated: false },
  },
};

export const AnswerSources: Story = {
  globals: { locale: "zh-CN" },
  args: { turns: [researchTurn()] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "打开来源 1" }));
    const page = within(canvasElement.ownerDocument.body);
    await expect(
      page.getByRole("dialog", { name: "引用来源 3" }),
    ).toBeVisible();
    await expect(
      page.getByText(homePapers[0]!.document.title ?? "Source 1"),
    ).toBeVisible();
  },
};

export const MathAndSources: Story = {
  globals: { locale: "zh-CN" },
  args: {
    turns: [
      researchTurn({
        responses: [
          response({
            id: "41000000-0000-4000-8000-000000000012",
            content: mathematicalResearchContent,
            references: researchReferences,
            trace: researchTrace,
          }),
        ],
        selected_response_id: "41000000-0000-4000-8000-000000000012",
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvasElement.querySelectorAll(".katex")).toHaveLength(4),
    );
    await expect(
      canvasElement.querySelectorAll(".katex-mathml math"),
    ).toHaveLength(4);
    await userEvent.click(canvas.getByRole("button", { name: "打开来源 1" }));
    await expect(
      within(canvasElement.ownerDocument.body).getByRole("dialog", {
        name: "引用来源 3",
      }),
    ).toBeVisible();
  },
};

export const MobileWorklogExpanded: Story = {
  globals: { locale: "zh-CN", viewport: { value: "mobile", isRotated: false } },
  args: {
    turns: [],
    liveTurn: liveTurn({
      entries: [
        {
          kind: "progress",
          id: "assistant:mobile:1",
          sequence: 1,
          content: "我会先检查资料库，再比较相邻的推理效率研究。",
        },
        { ...searchActivity, sequence: 2, subject: "思维链压缩与短推理轨迹" },
        {
          ...searchActivity,
          id: "search-mobile-2",
          sequence: 3,
          subject: "动态推理预算",
        },
        {
          kind: "progress",
          id: "assistant:mobile:2",
          sequence: 4,
          content: "初步结果较少，我将范围扩展到隐式推理与蒸馏方法。",
        },
        { ...readActivity, sequence: 5, subject: "Reasoning Efficiently" },
      ],
      content: "现有研究主要围绕短轨迹训练、隐式推理和动态预算展开。",
      phase: "ready",
      trace: researchTrace,
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const disclosure = canvas.getByRole("button", { name: /已完成研究/ });
    await userEvent.click(disclosure);
    await waitFor(() =>
      expect(canvas.getByText("检索了 2 次 · 已完成")).toBeVisible(),
    );
  },
};

export const ThinkingWithoutTools: Story = {
  args: { turns: [], liveTurn: liveTurn() },
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(within(canvasElement).getByRole("status")).toHaveTextContent(
        "Thinking…",
      ),
    );
  },
};

export const ProvisionalResponse: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({
      answerCandidate: {
        id: "assistant:turn:1",
        sequence: 1,
        phase: "provisional",
        content: "The evidence already supports an incremental answer.",
      },
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => {
      const content = canvas.getByText(
        "The evidence already supports an incremental answer.",
      );
      expect(content.closest("[data-message-content]")).toBeVisible();
      expect(content.closest("li")).toBeNull();
    });
  },
};

export const MobileReconnecting: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  args: {
    turns: [],
    liveTurn: liveTurn({ connectionState: "reconnecting" }),
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent(
      "Still running in the background · reconnecting…",
    );
  },
};

export const MobileReconnectingDark: Story = {
  ...MobileReconnecting,
  globals: {
    appearance: "dark",
    viewport: { value: "mobile", isRotated: false },
  },
};

export const StopCouldNotBeConfirmed: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({ stopFailure: true }),
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent(
      "Could not stop yet · still running in the background",
    );
  },
};

export const MobileStreamingLongTokenOverflow: Story = {
  globals: { locale: "zh-CN", viewport: { value: "mobile", isRotated: false } },
  args: {
    turns: [],
    liveTurn: liveTurn({
      userMessage: "调研一下长标题论文",
      answerCandidate: {
        id: "assistant:long:1",
        sequence: 1,
        phase: "provisional",
        content:
          "WhereDoesKnowledgeLiveExternalizingMemoryFromLargeLanguageModelsAndTheReasoningCoreHypothesis 是一个很长的英文标题，流式输出时它必须被安全换行而不能把页面撑宽，后面的中文正文也一样要正常换行。",
      },
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => {
      const content = canvas.getByText(/WhereDoesKnowledgeLive/);
      expect(content.closest("[data-message-content]")).toBeVisible();
      expect(content.closest("li")).toBeNull();
    });
    // A streaming answer must never widen the page horizontally, even with an
    // unbreakable long Latin token and CJK body.
    await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
      window.innerWidth + 1,
    );
    const messageContent = canvas
      .getByText(/WhereDoesKnowledgeLive/)
      .closest("[data-message-content]");
    await expect(messageContent).not.toBeNull();
    if (!messageContent) return;
    await expect(messageContent.scrollWidth).toBeLessThanOrEqual(
      messageContent.clientWidth + 1,
    );
  },
};

export const ProgressBeforeTools: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({
      entries: [
        {
          kind: "progress",
          id: "assistant:turn:1",
          sequence: 1,
          content: "I’ll first inspect the research available in your library.",
        },
        { ...searchActivity, sequence: 2, state: "running" },
      ],
    }),
  },
};

export const ConsecutiveToolBatch: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({
      entries: [
        searchActivity,
        readActivity,
        { ...searchActivity, id: "search-3", sequence: 3 },
      ],
    }),
  },
};

export const StrategyChange: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({
      entries: [
        searchActivity,
        {
          kind: "progress",
          id: "assistant:turn:2",
          sequence: 2,
          content:
            "The first search was too narrow, so I’ll compare adjacent work.",
        },
        { ...readActivity, sequence: 3, state: "running" },
      ],
    }),
  },
};

export const SingleToolRunning: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({ entries: [{ ...searchActivity, state: "running" }] }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const disclosure = canvas.getByRole("button", {
      name: "Searching your research…",
    });
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
    disclosure.focus();
    await userEvent.keyboard(" ");
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  },
};

export const CompletedCollapsed: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({
      entries: [searchActivity, readActivity],
      content: "The evidence supports a shorter distilled reasoning trace.",
      phase: "ready",
      trace: researchTrace,
    }),
  },
  play: async ({ canvasElement }) => {
    const disclosure = within(canvasElement).getByRole("button", {
      name: "Research complete · 2 actions · 3 cited sources",
    });
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  },
};

export const PartialFailure: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({
      entries: [searchActivity, { ...readActivity, state: "failed" }],
      content: "I found enough material to answer.",
      phase: "ready",
      trace: {
        ...researchTrace,
        entries: [searchActivity, { ...readActivity, state: "failed" }],
      },
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const disclosure = canvas.getByRole("button", {
      name: "Partially complete · 2 actions · 3 cited sources",
    });
    await userEvent.click(disclosure);
    await expect(canvas.getByText("Searched 1 time · Completed")).toBeVisible();
    await expect(canvas.getByText("Read 1 source · Failed")).toBeVisible();
  },
};

export const Cancelled: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({ entries: [searchActivity], phase: "cancelled" }),
  },
};

export const Error: Story = {
  args: {
    turns: [],
    liveTurn: liveTurn({
      phase: "error",
      failure: {
        code: "rate_limit_unavailable",
        kind: "unavailable",
        retryable: true,
        diagnosticId: "diagnostic-123",
      },
    }),
  },
};

export const NarrowLongSubject: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  args: {
    turns: [],
    liveTurn: liveTurn({
      entries: [
        {
          ...searchActivity,
          state: "running",
          subject:
            "A deliberately long research subject that must wrap safely without widening the conversation viewport",
        },
      ],
    }),
  },
};

export const SimplifiedChineseDark: Story = {
  globals: { appearance: "dark", locale: "zh-CN" },
  args: {
    turns: [],
    liveTurn: liveTurn({ entries: [{ ...searchActivity, state: "running" }] }),
  },
};

export const OptimisticTurnDeduplicated: Story = {
  args: {
    turns: [
      turn({
        id: "52000000-0000-4000-8000-000000000001",
        user_query: "Compare the strongest reasoning-compression approaches.",
        selected_response_id: null,
        responses: [],
      }),
    ],
    liveTurn: liveTurn({ entries: [{ ...searchActivity, state: "running" }] }),
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getAllByText(
        "Compare the strongest reasoning-compression approaches.",
      ),
    ).toHaveLength(1);
  },
};

function SidePanelStory(args: ComponentProps<typeof ConversationView>) {
  return (
    <div className="border-line h-dvh w-[23rem] max-w-full border-l">
      <ConversationView {...args} />
    </div>
  );
}

export const SidePanelEmpty: Story = {
  args: {
    context: {
      kind: "selection",
      document_ids: [homePapers[0]!.document.document_id],
      project_ids: [],
    },
    emptyState: {
      description:
        "Ask about this paper’s claims, methods, or conclusions, or select a passage to discuss.",
      title: "What would you like to understand?",
    },
    layout: "side-panel",
    turns: [],
  },
  render: SidePanelStory,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("What would you like to understand?"),
    ).toBeVisible();
    await expect(
      canvas.getByText(/paper’s claims, methods, or conclusions/),
    ).toBeVisible();
    await expect(canvas.getByRole("textbox")).toBeVisible();
  },
};

export const SidePanelEmptySimplifiedChineseDark: Story = {
  args: {
    ...SidePanelEmpty.args,
    emptyState: {
      description: "可以询问它的观点、方法或结论，也可以选中原文继续讨论。",
      title: "想从这篇论文中了解什么？",
    },
  },
  globals: { appearance: "dark", locale: "zh-CN" },
  render: SidePanelStory,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("想从这篇论文中了解什么？")).toBeVisible();
    await expect(canvas.getByText(/观点、方法或结论/)).toBeVisible();
    await expect(canvas.getByRole("textbox")).toBeVisible();
  },
};

export const SidePanelStreaming: Story = {
  args: {
    ...SidePanelEmpty.args,
    liveTurn: liveTurn({
      entries: [{ ...searchActivity, state: "running" }],
      provisionalItems: [
        {
          id: "assistant:side-panel:1",
          sequence: 2,
          phase: "provisional",
          content: "I’m comparing this passage with the paper’s evidence.",
        },
      ],
    }),
  },
  render: SidePanelStory,
};

export const SidePanelReady: Story = {
  args: {
    ...SidePanelEmpty.args,
    turns: [researchTurn()],
  },
  render: SidePanelStory,
};

export const SidePanelJumpToLatest: Story = {
  args: {
    ...SidePanelEmpty.args,
    turns: Array.from({ length: 4 }, (_, index) =>
      researchTurn({
        id: `51000000-0000-4000-8000-${String(index + 21).padStart(12, "0")}`,
        depth: index + 1,
        parent_turn_id: index === 0 ? null : turnId,
        user_query: `Research question ${index + 1}`,
      }),
    ),
  },
  render: SidePanelStory,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const scrollRoot = canvasElement.querySelector<HTMLElement>(
      "[data-conversation-scroll-root]",
    );
    await expect(scrollRoot).not.toBeNull();
    if (!scrollRoot) return;
    scrollRoot.scrollTop = 0;
    await fireEvent.scroll(scrollRoot);
    const jumpButton = await canvas.findByRole("button", {
      name: "Jump to the latest response",
    });
    const composer = canvas.getByRole("textbox").closest("form");
    await expect(composer).not.toBeNull();
    if (!composer) return;
    await waitFor(() => {
      expect(jumpButton.getBoundingClientRect().bottom).toBeLessThanOrEqual(
        composer.getBoundingClientRect().top,
      );
    });
  },
};
