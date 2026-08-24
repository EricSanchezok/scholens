import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const conversationApi = vi.hoisted(() => ({
  cancelConversationGeneration: vi.fn(),
  streamConversationBranch: vi.fn(),
  streamConversationRetry: vi.fn(),
  streamConversationStart: vi.fn(),
  streamConversationTurn: vi.fn(),
  subscribeConversationEvents: vi.fn(),
  updateConversationContext: vi.fn(),
}));
const performanceTracker = vi.hoisted(() => ({
  markAccepted: vi.fn(),
  markContentVisible: vi.fn(),
  markEvent: vi.fn(),
  markFeedback: vi.fn(),
  markReady: vi.fn(),
  markTerminal: vi.fn(),
}));

vi.mock("next-intl", () => ({ useLocale: () => "en" }));
vi.mock("@/lib/observability/conversation-performance", () => ({
  createConversationPerformanceTracker: () => performanceTracker,
}));
vi.mock("./api/conversations", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api/conversations")>()),
  cancelConversationGeneration: conversationApi.cancelConversationGeneration,
  streamConversationBranch: conversationApi.streamConversationBranch,
  streamConversationRetry: conversationApi.streamConversationRetry,
  streamConversationStart: conversationApi.streamConversationStart,
  streamConversationTurn: conversationApi.streamConversationTurn,
  subscribeConversationEvents: conversationApi.subscribeConversationEvents,
  updateConversationContext: conversationApi.updateConversationContext,
}));

import { useConversationSession } from "./use-conversation-session";
import { conversationKeys } from "./api/keys";

const conversationId = "40000000-0000-4000-8000-000000000001";

function createdConversation(id = conversationId) {
  return {
    id,
    capabilities: { archive: true, delete: true, rename: true, send: true },
    paper_context: { kind: "library" as const },
  };
}

function readyTurn(turnId: string, responseId: string) {
  return {
    branch: { count: 1, index: 1 },
    contexts: [],
    depth: 1,
    id: turnId,
    locale: "en" as const,
    paper_context: { kind: "library" as const },
    parent_turn_id: null,
    reasoning_level: "standard" as const,
    responses: [
      {
        artifacts: null,
        content: "Canonical answer",
        duration_ms: 100,
        id: responseId,
        references: null,
        status: "completed" as const,
        trace: null,
        variant_index: 1,
      },
    ],
    selected_response_id: responseId,
    suggestions: null,
    time_zone: "Asia/Shanghai",
    user_query: "Question",
  };
}

type SessionProps = {
  conversationId?: string;
  context?: Parameters<typeof useConversationSession>[0]["context"];
  scopeId?: string;
  scopeType?: "global" | "paper" | "project";
  updateExistingContext?: boolean;
};

type RenderSessionOptions = {
  initialProps?: SessionProps;
  seedQueryClient?: (queryClient: QueryClient) => void;
  strict?: boolean;
};

function renderSession(
  onSubmissionError = vi.fn(),
  options: RenderSessionOptions = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  options.seedQueryClient?.(queryClient);
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const onConversationCreated = vi.fn();
  return {
    onSubmissionError,
    onConversationCreated,
    queryClient,
    ...renderHook(
      ({
        context,
        conversationId,
        scopeId,
        scopeType = "global",
        updateExistingContext,
      }: SessionProps) =>
        useConversationSession({
          context,
          conversationId,
          onConversationCreated,
          onSubmissionError,
          reasoningLevel: "standard",
          scopeId,
          scopeType,
          updateExistingContext,
        }),
      {
        initialProps:
          options.initialProps ??
          ({ conversationId: undefined } as SessionProps),
        reactStrictMode: options.strict,
        wrapper,
      },
    ),
  };
}

describe("useConversationSession optimistic submission", () => {
  beforeEach(() => {
    conversationApi.cancelConversationGeneration.mockReset();
    conversationApi.streamConversationBranch.mockReset();
    conversationApi.streamConversationRetry.mockReset();
    conversationApi.streamConversationStart.mockReset();
    conversationApi.streamConversationTurn.mockReset();
    conversationApi.subscribeConversationEvents.mockReset();
    conversationApi.updateConversationContext.mockReset();
    Object.values(performanceTracker).forEach((mock) => mock.mockReset());
  });

  it("publishes immediately and uses one atomic start request", async () => {
    let startInput:
      | Parameters<
          typeof import("./api/conversations").streamConversationStart
        >[0]
      | undefined;
    let finishStream: (() => void) | undefined;
    conversationApi.streamConversationStart.mockImplementation((input) => {
      startInput = input;
      return new Promise<void>((resolve) => {
        finishStream = resolve;
      });
    });
    const { onConversationCreated, queryClient, result } = renderSession();
    act(() => result.current.composerForm.setValue("message", "Exact draft"));

    let submission: Promise<void> | undefined;
    act(() => {
      submission = result.current.sendMessage("Exact draft");
    });

    expect(result.current.liveTurn.getSnapshot()).toMatchObject({
      phase: "submitting",
      userMessage: "Exact draft",
    });
    expect(result.current.composerForm.getValues("message")).toBe("");
    expect(result.current.submissionPending).toBe(true);
    expect(result.current.activeConversationId).toBe(
      startInput?.conversationId,
    );
    expect(startInput?.request).toMatchObject({
      conversation: {
        scope_type: "global",
        paper_context: { kind: "library" },
      },
      turn: { user_query: "Exact draft" },
    });
    expect(conversationApi.streamConversationTurn).not.toHaveBeenCalled();

    await act(async () => {
      if (!startInput) throw new Error("Atomic start was not invoked");
      queryClient.setQueryData(
        conversationKeys.detail(startInput.conversationId),
        createdConversation(startInput.conversationId),
      );
      queryClient.setQueryData(
        conversationKeys.turns(startInput.conversationId),
        {
          items: [],
          next_cursor: null,
          path_revision: 0,
        },
      );
      startInput.onAccepted?.("direct");
      startInput.onEvent({
        type: "error",
        response_id: startInput.request.turn.response_id,
        error: { code: "test_complete", retryable: false },
      });
      finishStream?.();
      await submission;
    });
    expect(onConversationCreated).toHaveBeenCalledWith(
      startInput?.conversationId,
    );
  });

  it("restores the exact draft after a pre-accept failure", async () => {
    conversationApi.streamConversationStart.mockRejectedValue(
      new Error("creation failed"),
    );
    const onSubmissionError = vi.fn();
    const { result } = renderSession(onSubmissionError);

    await act(async () => {
      await result.current.sendMessage("Draft with  exact spacing");
    });

    expect(result.current.liveTurn.getSnapshot()).toBeNull();
    expect(result.current.composerForm.getValues("message")).toBe(
      "Draft with  exact spacing",
    );
    expect(onSubmissionError).toHaveBeenCalledTimes(1);
  });

  it("reuses the same start identity after an ambiguous pre-accept failure", async () => {
    const attempts: Array<
      Parameters<
        typeof import("./api/conversations").streamConversationStart
      >[0]
    > = [];
    const { queryClient, result } = renderSession();
    conversationApi.streamConversationStart
      .mockImplementationOnce(async (input) => {
        attempts.push(input);
        throw new TypeError("connection lost");
      })
      .mockImplementationOnce(async (input) => {
        attempts.push(input);
        queryClient.setQueryData(
          conversationKeys.detail(input.conversationId),
          createdConversation(input.conversationId),
        );
        queryClient.setQueryData(conversationKeys.turns(input.conversationId), {
          items: [],
          next_cursor: null,
          path_revision: 0,
        });
        input.onAccepted?.("direct");
        input.onEvent({
          type: "error",
          response_id: input.request.turn.response_id,
          error: { code: "test_complete", retryable: false },
        });
      });

    await act(async () => {
      await result.current.sendMessage("Retry the identical request");
    });
    await act(async () => {
      await result.current.sendMessage("Retry the identical request");
    });

    expect(attempts).toHaveLength(2);
    expect(attempts[1]?.conversationId).toBe(attempts[0]?.conversationId);
    expect(attempts[1]?.request.turn.turn_id).toBe(
      attempts[0]?.request.turn.turn_id,
    );
    expect(attempts[1]?.request.turn.response_id).toBe(
      attempts[0]?.request.turn.response_id,
    );
  });

  it("keeps the optimistic user message after acceptance fails", async () => {
    const { queryClient, result } = renderSession();
    conversationApi.streamConversationStart.mockImplementation(
      async (input) => {
        queryClient.setQueryData(
          conversationKeys.detail(input.conversationId),
          createdConversation(input.conversationId),
        );
        queryClient.setQueryData(conversationKeys.turns(input.conversationId), {
          items: [],
          next_cursor: null,
          path_revision: 0,
        });
        input.onAccepted?.("direct");
        input.onEvent({
          type: "start",
          conversation_id: input.conversationId,
          turn_id: input.request.turn.turn_id,
          response_id: input.request.turn.response_id,
          variant_index: 1,
          generation_kind: "initial",
        });
        throw new Error("stream failed after acceptance");
      },
    );

    await act(async () => {
      await result.current.sendMessage("Keep this question");
    });

    await waitFor(() =>
      expect(result.current.liveTurn.getSnapshot()).toMatchObject({
        phase: "error",
        userMessage: "Keep this question",
      }),
    );
    expect(result.current.composerForm.getValues("message")).toBe("");
  });

  it("marks canonical completed content as the first visible answer", async () => {
    let startInput:
      | Parameters<
          typeof import("./api/conversations").streamConversationStart
        >[0]
      | undefined;
    let finishStream: (() => void) | undefined;
    const { queryClient, result } = renderSession();
    conversationApi.streamConversationStart.mockImplementation((input) => {
      startInput = input;
      return new Promise<void>((resolve) => {
        finishStream = resolve;
      });
    });
    let submission: Promise<void> | undefined;
    act(() => {
      submission = result.current.sendMessage("Question");
    });
    if (!startInput) throw new Error("Atomic start was not invoked");

    await act(async () => {
      queryClient.setQueryData(
        conversationKeys.detail(startInput!.conversationId),
        createdConversation(startInput!.conversationId),
      );
      queryClient.setQueryData(
        conversationKeys.turns(startInput!.conversationId),
        {
          items: [],
          next_cursor: null,
          path_revision: 0,
        },
      );
      startInput!.onAccepted?.("direct");
      startInput!.onEvent({
        type: "assistant_item_complete",
        response_id: startInput!.request.turn.response_id,
        item: {
          id: "answer",
          sequence: 1,
          phase: "final",
          content: "Canonical answer",
        },
      });
      result.current.markContentVisible(startInput!.request.turn.response_id);
    });

    expect(performanceTracker.markContentVisible).toHaveBeenCalledTimes(1);
    await act(async () => {
      startInput!.onEvent({
        type: "error",
        response_id: startInput!.request.turn.response_id,
        error: { code: "test_complete", retryable: false },
      });
      finishStream?.();
      await submission;
    });
  });

  it("keeps the stream alive for suggestions after response ready", async () => {
    let startInput:
      | Parameters<
          typeof import("./api/conversations").streamConversationStart
        >[0]
      | undefined;
    let finishStream: (() => void) | undefined;
    conversationApi.streamConversationStart.mockImplementation((input) => {
      startInput = input;
      return new Promise<void>((resolve) => {
        finishStream = resolve;
      });
    });
    const { queryClient, result } = renderSession();
    let submission: Promise<void> | undefined;
    act(() => {
      submission = result.current.sendMessage("Question");
    });
    if (!startInput) throw new Error("Atomic start was not invoked");
    const turn = readyTurn(
      startInput.request.turn.turn_id,
      startInput.request.turn.response_id,
    );

    await act(async () => {
      queryClient.setQueryData(
        conversationKeys.detail(startInput!.conversationId),
        createdConversation(startInput!.conversationId),
      );
      queryClient.setQueryData(
        conversationKeys.turns(startInput!.conversationId),
        {
          items: [],
          next_cursor: null,
          path_revision: 0,
        },
      );
      startInput!.onAccepted?.("direct");
      startInput!.onEvent({ type: "response_ready", turn });
    });

    expect(startInput.signal.aborted).toBe(false);
    await act(async () => {
      startInput!.onEvent({
        type: "suggestions",
        response_id: startInput!.request.turn.response_id,
        turn_id: startInput!.request.turn.turn_id,
        suggestions: ["One", "Two", "Three"],
      });
      startInput!.onEvent({
        type: "complete",
        response_id: startInput!.request.turn.response_id,
        turn_id: startInput!.request.turn.turn_id,
      });
      finishStream?.();
      await submission;
    });

    expect(
      queryClient.getQueryData<{
        items: Array<{ suggestions: string[] | null }>;
      }>(conversationKeys.turns(startInput.conversationId))?.items[0]
        ?.suggestions,
    ).toEqual(["One", "Two", "Three"]);
  });

  it("reports canonical content and completion when ready and complete share a batch", async () => {
    let responseId = "";
    conversationApi.streamConversationStart.mockImplementation(
      async (input) => {
        responseId = input.request.turn.response_id;
        input.onAccepted?.("direct");
        input.onEvent({
          type: "response_ready",
          turn: readyTurn(input.request.turn.turn_id, responseId),
        });
        input.onEvent({
          type: "complete",
          turn_id: input.request.turn.turn_id,
          response_id: responseId,
        });
      },
    );
    const { result } = renderSession();

    await act(async () => {
      await result.current.sendMessage("Fast answer");
    });

    expect(result.current.liveTurn.getSnapshot()).toBeNull();
    expect(result.current.completionAnnouncementId).toBe(responseId);
    act(() => result.current.markContentVisible(responseId));
    expect(performanceTracker.markContentVisible).toHaveBeenCalledTimes(1);
  });

  it("keeps completion through URL canonicalization and clears it on identity changes", async () => {
    let completedConversationId = "";
    let completedResponseId = "";
    conversationApi.streamConversationStart.mockImplementation(
      async (input) => {
        completedConversationId = input.conversationId;
        completedResponseId = input.request.turn.response_id;
        input.onAccepted?.("direct");
        input.onEvent({
          type: "response_ready",
          turn: readyTurn(input.request.turn.turn_id, completedResponseId),
        });
        input.onEvent({
          type: "complete",
          turn_id: input.request.turn.turn_id,
          response_id: completedResponseId,
        });
      },
    );
    const { rerender, result } = renderSession();

    await act(async () => {
      await result.current.sendMessage("Fast answer");
    });
    expect(result.current.completionAnnouncementId).toBe(completedResponseId);

    rerender({ conversationId: completedConversationId });
    expect(result.current.completionAnnouncementId).toBe(completedResponseId);

    rerender({ conversationId: undefined });
    expect(result.current.completionAnnouncementId).toBeUndefined();
  });

  it("clears completion when the conversation scope identity changes", async () => {
    let completedConversationId = "";
    let completedResponseId = "";
    conversationApi.streamConversationStart.mockImplementation(
      async (input) => {
        completedConversationId = input.conversationId;
        completedResponseId = input.request.turn.response_id;
        input.onAccepted?.("direct");
        input.onEvent({
          type: "response_ready",
          turn: readyTurn(input.request.turn.turn_id, completedResponseId),
        });
        input.onEvent({
          type: "complete",
          turn_id: input.request.turn.turn_id,
          response_id: completedResponseId,
        });
      },
    );
    const { rerender, result } = renderSession();

    await act(async () => {
      await result.current.sendMessage("Fast answer");
    });
    expect(result.current.completionAnnouncementId).toBe(completedResponseId);

    rerender({
      conversationId: completedConversationId,
      scopeId: "20000000-0000-4000-8000-000000000001",
      scopeType: "project",
    });
    expect(result.current.completionAnnouncementId).toBeUndefined();
  });

  it("keeps a replacement send gated while the ready stream settles", async () => {
    let startInput:
      | Parameters<
          typeof import("./api/conversations").streamConversationStart
        >[0]
      | undefined;
    let turnInput:
      | Parameters<
          typeof import("./api/conversations").streamConversationTurn
        >[0]
      | undefined;
    let finishStart: (() => void) | undefined;
    let finishTurn: (() => void) | undefined;
    conversationApi.streamConversationStart.mockImplementation((input) => {
      startInput = input;
      return new Promise<void>((resolve) => {
        finishStart = resolve;
      });
    });
    conversationApi.streamConversationTurn.mockImplementation((input) => {
      turnInput = input;
      return new Promise<void>((resolve) => {
        finishTurn = resolve;
      });
    });
    const { queryClient, result } = renderSession();
    let firstSubmission: Promise<void> | undefined;
    let replacementSubmission: Promise<void> | undefined;

    act(() => {
      firstSubmission = result.current.sendMessage("First question");
    });
    if (!startInput) throw new Error("Atomic start was not invoked");
    await act(async () => {
      queryClient.setQueryData(
        conversationKeys.detail(startInput!.conversationId),
        createdConversation(startInput!.conversationId),
      );
      queryClient.setQueryData(
        conversationKeys.turns(startInput!.conversationId),
        { items: [], next_cursor: null, path_revision: 0 },
      );
      startInput!.onAccepted?.("direct");
      startInput!.onEvent({
        type: "response_ready",
        turn: readyTurn(
          startInput!.request.turn.turn_id,
          startInput!.request.turn.response_id,
        ),
      });
    });

    act(() => {
      replacementSubmission = result.current.sendMessage("Second question");
    });
    expect(turnInput?.request.user_query).toBe("Second question");
    await act(async () => {
      await result.current.sendMessage("Must not race");
    });

    expect(conversationApi.streamConversationTurn).toHaveBeenCalledTimes(1);
    expect(result.current.liveTurn.getSnapshot()?.userMessage).toBe(
      "Second question",
    );

    await act(async () => {
      if (!turnInput) throw new Error("Replacement turn was not invoked");
      turnInput.onAccepted?.("direct");
      turnInput.onEvent({
        type: "error",
        response_id: turnInput.request.response_id,
        error: { code: "test_complete", retryable: false },
      });
      finishTurn?.();
      finishStart?.();
      await Promise.all([firstSubmission, replacementSubmission]);
    });
  });

  it("keeps retry generation gated while the ready stream settles", async () => {
    let startInput:
      | Parameters<
          typeof import("./api/conversations").streamConversationStart
        >[0]
      | undefined;
    let retryInput:
      | Parameters<
          typeof import("./api/conversations").streamConversationRetry
        >[0]
      | undefined;
    let finishStart: (() => void) | undefined;
    let finishRetry: (() => void) | undefined;
    conversationApi.streamConversationStart.mockImplementation((input) => {
      startInput = input;
      return new Promise<void>((resolve) => {
        finishStart = resolve;
      });
    });
    conversationApi.streamConversationRetry.mockImplementation((input) => {
      retryInput = input;
      return new Promise<void>((resolve) => {
        finishRetry = resolve;
      });
    });
    const { queryClient, result } = renderSession();
    let firstSubmission: Promise<void> | undefined;
    let retrySubmission: Promise<void> | undefined;

    act(() => {
      firstSubmission = result.current.sendMessage("First question");
    });
    if (!startInput) throw new Error("Atomic start was not invoked");
    const completed = readyTurn(
      startInput.request.turn.turn_id,
      startInput.request.turn.response_id,
    );
    await act(async () => {
      queryClient.setQueryData(
        conversationKeys.detail(startInput!.conversationId),
        createdConversation(startInput!.conversationId),
      );
      queryClient.setQueryData(
        conversationKeys.turns(startInput!.conversationId),
        { items: [], next_cursor: null, path_revision: 0 },
      );
      startInput!.onAccepted?.("direct");
      startInput!.onEvent({ type: "response_ready", turn: completed });
    });

    act(() => {
      retrySubmission = result.current.retryResponse(completed);
    });
    expect(retryInput).toBeDefined();
    await act(async () => {
      await result.current.sendMessage("Must not race retry");
    });

    expect(conversationApi.streamConversationTurn).not.toHaveBeenCalled();
    expect(conversationApi.streamConversationRetry).toHaveBeenCalledTimes(1);

    await act(async () => {
      if (!retryInput) throw new Error("Retry was not invoked");
      retryInput.onAccepted?.("direct");
      retryInput.onEvent({
        type: "error",
        response_id: retryInput.request.response_id,
        error: { code: "test_complete", retryable: false },
      });
      finishRetry?.();
      finishStart?.();
      await Promise.all([firstSubmission, retrySubmission]);
    });
  });

  it("does not publish a late acceptance into a different conversation", async () => {
    let startInput:
      | Parameters<
          typeof import("./api/conversations").streamConversationStart
        >[0]
      | undefined;
    let finishStream: (() => void) | undefined;
    conversationApi.streamConversationStart.mockImplementation((input) => {
      startInput = input;
      return new Promise<void>((resolve) => {
        finishStream = resolve;
      });
    });
    const { onConversationCreated, queryClient, rerender, result } =
      renderSession();
    let submission: Promise<void> | undefined;
    act(() => {
      submission = result.current.sendMessage("Question for the old view");
    });

    const otherConversationId = "40000000-0000-4000-8000-000000000099";
    queryClient.setQueryData(conversationKeys.detail(otherConversationId), {
      ...createdConversation(),
      id: otherConversationId,
    });
    queryClient.setQueryData(conversationKeys.turns(otherConversationId), {
      items: [],
      next_cursor: null,
      path_revision: 0,
    });
    rerender({ conversationId: otherConversationId });
    expect(result.current.liveTurn.getSnapshot()).toBeNull();

    await act(async () => {
      startInput?.onAccepted?.("direct");
      finishStream?.();
      await submission;
    });

    expect(result.current.liveTurn.getSnapshot()).toBeNull();
    expect(onConversationCreated).not.toHaveBeenCalled();
  });

  it("does not start a stream after an unmounted context update settles", async () => {
    let finishContextUpdate: (() => void) | undefined;
    conversationApi.updateConversationContext.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finishContextUpdate = resolve;
        }),
    );
    const { queryClient, rerender, result, unmount } = renderSession();
    act(() => {
      queryClient.setQueryData(
        conversationKeys.detail(conversationId),
        createdConversation(),
      );
      queryClient.setQueryData(conversationKeys.turns(conversationId), {
        items: [],
        next_cursor: null,
        path_revision: 0,
      });
      rerender({
        context: {
          kind: "selection",
          document_ids: [],
          project_ids: ["20000000-0000-4000-8000-000000000001"],
        },
        conversationId,
        updateExistingContext: true,
      });
    });

    let submission: Promise<void> | undefined;
    act(() => {
      submission = result.current.sendMessage("Question after context change");
    });
    await waitFor(() =>
      expect(conversationApi.updateConversationContext).toHaveBeenCalledTimes(
        1,
      ),
    );
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");

    unmount();
    await act(async () => {
      finishContextUpdate?.();
      await submission;
    });

    expect(conversationApi.streamConversationTurn).not.toHaveBeenCalled();
    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  it("keeps a recovered subscription through ready sidecars and complete", async () => {
    const recoveredTurnId = "50000000-0000-4000-8000-000000000020";
    const recoveredResponseId = "60000000-0000-4000-8000-000000000020";
    const completed = readyTurn(recoveredTurnId, recoveredResponseId);
    const running = {
      ...completed,
      selected_response_id: recoveredResponseId,
      responses: completed.responses.map((response) => ({
        ...response,
        content: "Partial answer",
        status: "running" as const,
      })),
    };
    let subscriptionInput:
      | Parameters<
          typeof import("./api/conversations").subscribeConversationEvents
        >[0]
      | undefined;
    let finishSubscription: (() => void) | undefined;
    conversationApi.subscribeConversationEvents.mockImplementation((input) => {
      subscriptionInput = input;
      return new Promise<void>((resolve) => {
        finishSubscription = resolve;
      });
    });
    const { queryClient, rerender, result } = renderSession();

    act(() => {
      queryClient.setQueryData(
        conversationKeys.detail(conversationId),
        createdConversation(),
      );
      queryClient.setQueryData(conversationKeys.turns(conversationId), {
        items: [running],
        next_cursor: null,
        path_revision: 1,
      });
      rerender({ conversationId });
    });
    await waitFor(() => expect(subscriptionInput).toBeDefined());

    await act(async () => {
      subscriptionInput!.onEvent({ type: "response_ready", turn: completed });
    });
    expect(subscriptionInput!.signal.aborted).toBe(false);

    await act(async () => {
      subscriptionInput!.onEvent({
        type: "suggestions",
        turn_id: recoveredTurnId,
        response_id: recoveredResponseId,
        suggestions: ["One", "Two", "Three"],
      });
      subscriptionInput!.onEvent({
        type: "complete",
        turn_id: recoveredTurnId,
        response_id: recoveredResponseId,
      });
      finishSubscription?.();
    });

    expect(
      queryClient.getQueryData<{
        items: Array<{ suggestions: string[] | null }>;
      }>(conversationKeys.turns(conversationId))?.items[0]?.suggestions,
    ).toEqual(["One", "Two", "Three"]);
    expect(result.current.submissionPending).toBe(false);
  });

  it("ignores a recovered stream failure after its replacement starts", async () => {
    const recoveredTurnId = "50000000-0000-4000-8000-000000000030";
    const recoveredResponseId = "60000000-0000-4000-8000-000000000030";
    const completedRecovered = readyTurn(recoveredTurnId, recoveredResponseId);
    const runningRecovered = {
      ...completedRecovered,
      responses: completedRecovered.responses.map((response) => ({
        ...response,
        content: "Partial answer",
        status: "running" as const,
      })),
    };
    let subscriptionInput:
      | Parameters<
          typeof import("./api/conversations").subscribeConversationEvents
        >[0]
      | undefined;
    let rejectSubscription: ((reason?: unknown) => void) | undefined;
    let replacementInput:
      | Parameters<
          typeof import("./api/conversations").streamConversationTurn
        >[0]
      | undefined;
    let finishReplacement: (() => void) | undefined;
    conversationApi.subscribeConversationEvents.mockImplementation((input) => {
      subscriptionInput = input;
      return new Promise<void>((_resolve, reject) => {
        rejectSubscription = reject;
      });
    });
    conversationApi.streamConversationTurn.mockImplementation((input) => {
      replacementInput = input;
      return new Promise<void>((resolve) => {
        finishReplacement = resolve;
      });
    });
    const { queryClient, rerender, result } = renderSession();

    act(() => {
      queryClient.setQueryData(
        conversationKeys.detail(conversationId),
        createdConversation(),
      );
      queryClient.setQueryData(conversationKeys.turns(conversationId), {
        items: [runningRecovered],
        next_cursor: null,
        path_revision: 1,
      });
      rerender({ conversationId });
    });
    await waitFor(() => expect(subscriptionInput).toBeDefined());

    await act(async () => {
      subscriptionInput!.onEvent({
        type: "response_ready",
        turn: completedRecovered,
      });
    });

    let replacementSubmission: Promise<void> | undefined;
    act(() => {
      replacementSubmission = result.current.sendMessage("Replacement");
    });
    if (!replacementInput) throw new Error("Replacement turn was not invoked");
    await act(async () => {
      replacementInput!.onAccepted?.("direct");
      replacementInput!.onConnectionState?.("reconnecting");
    });
    expect(result.current.submissionPending).toBe(true);

    await act(async () => {
      rejectSubscription?.(new Error("Late recovered stream failure"));
      await Promise.resolve();
    });

    const completedReplacement = readyTurn(
      replacementInput.request.turn_id,
      replacementInput.request.response_id,
    );
    act(() => {
      queryClient.setQueryData(conversationKeys.turns(conversationId), {
        items: [completedRecovered, completedReplacement],
        next_cursor: null,
        path_revision: 2,
      });
    });
    await waitFor(() => expect(result.current.submissionPending).toBe(false));

    await act(async () => {
      replacementInput!.onEvent({
        type: "complete",
        turn_id: replacementInput!.request.turn_id,
        response_id: replacementInput!.request.response_id,
      });
      finishReplacement?.();
      await replacementSubmission;
    });
  });

  it("does not write after a recovered stream rejects following unmount", async () => {
    const recoveredTurnId = "50000000-0000-4000-8000-000000000040";
    const recoveredResponseId = "60000000-0000-4000-8000-000000000040";
    const completed = readyTurn(recoveredTurnId, recoveredResponseId);
    const running = {
      ...completed,
      responses: completed.responses.map((response) => ({
        ...response,
        content: "Partial answer",
        status: "running" as const,
      })),
    };
    const subscriptionInputs: Array<
      Parameters<
        typeof import("./api/conversations").subscribeConversationEvents
      >[0]
    > = [];
    const rejectSubscriptions: Array<(reason?: unknown) => void> = [];
    conversationApi.subscribeConversationEvents.mockImplementation((input) => {
      subscriptionInputs.push(input);
      return new Promise<void>((_resolve, reject) => {
        rejectSubscriptions.push(reject);
      });
    });
    const { queryClient, result, unmount } = renderSession(vi.fn(), {
      initialProps: { conversationId },
      seedQueryClient: (client) => {
        client.setQueryData(
          conversationKeys.detail(conversationId),
          createdConversation(),
        );
        client.setQueryData(conversationKeys.turns(conversationId), {
          items: [running],
          next_cursor: null,
          path_revision: 1,
        });
      },
      strict: true,
    });

    await waitFor(() => expect(subscriptionInputs).toHaveLength(2));
    expect(subscriptionInputs[0]!.signal.aborted).toBe(true);
    expect(subscriptionInputs[1]!.signal.aborted).toBe(false);
    expect(result.current.submissionPending).toBe(true);
    await act(async () => {
      rejectSubscriptions[0]?.(new DOMException("Aborted", "AbortError"));
      await Promise.resolve();
    });
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");

    unmount();
    await act(async () => {
      rejectSubscriptions[1]?.(new Error("Late recovered stream failure"));
      await Promise.resolve();
    });

    expect(subscriptionInputs[1]!.signal.aborted).toBe(true);
    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  it("only sends durable cancellation after acceptance", async () => {
    let startInput:
      | Parameters<
          typeof import("./api/conversations").streamConversationStart
        >[0]
      | undefined;
    let finishStream: (() => void) | undefined;
    conversationApi.streamConversationStart.mockImplementation((input) => {
      startInput = input;
      return new Promise<void>((resolve) => {
        finishStream = resolve;
      });
    });
    conversationApi.cancelConversationGeneration.mockResolvedValue({
      conversation_id: conversationId,
      turn_id: "turn",
      response_id: "response",
      status: "cancelled",
    });
    const { queryClient, result } = renderSession();
    let submission: Promise<void> | undefined;
    act(() => {
      submission = result.current.sendMessage("Cancelable question");
      result.current.stop();
    });
    expect(conversationApi.cancelConversationGeneration).not.toHaveBeenCalled();

    await act(async () => {
      if (!startInput) throw new Error("Atomic start was not invoked");
      queryClient.setQueryData(
        conversationKeys.detail(startInput.conversationId),
        createdConversation(startInput.conversationId),
      );
      queryClient.setQueryData(
        conversationKeys.turns(startInput.conversationId),
        {
          items: [],
          next_cursor: null,
          path_revision: 0,
        },
      );
      startInput.onAccepted?.("direct");
      result.current.stop();
      result.current.stop();
    });
    await waitFor(() =>
      expect(conversationApi.cancelConversationGeneration).toHaveBeenCalledWith(
        {
          conversationId: startInput?.conversationId,
          turnId: startInput?.request.turn.turn_id,
          responseId: startInput?.request.turn.response_id,
        },
      ),
    );
    expect(conversationApi.cancelConversationGeneration).toHaveBeenCalledTimes(
      1,
    );
    await act(async () => {
      finishStream?.();
      await submission;
    });
  });
});
