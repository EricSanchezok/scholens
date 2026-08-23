import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/generated/schema";
import { conversationKeys } from "./api/keys";
import { useConversationSession } from "./use-conversation-session";

const api = vi.hoisted(() => ({
  cancelConversationGeneration: vi.fn(),
  createConversation: vi.fn(),
  selectConversationBranch: vi.fn(),
  selectConversationResponse: vi.fn(),
  streamConversationBranch: vi.fn(),
  streamConversationRetry: vi.fn(),
  streamConversationTurn: vi.fn(),
  subscribeConversationEvents: vi.fn(),
  updateConversationContext: vi.fn(),
}));

vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => key,
}));

vi.mock("./api/conversations", () => api);

type ConversationDetail = components["schemas"]["ConversationDetailResponse"];
type ConversationTurns = components["schemas"]["ConversationTurnsResponse"];

function detail(id: string): ConversationDetail {
  return {
    archived_at: null,
    capabilities: {
      archive: true,
      delete: true,
      detach: true,
      move: true,
      pin: true,
      rename: true,
      send: true,
      share: false,
    },
    id,
    paper_context: { kind: "library" },
    pinned_at: null,
    read_only: false,
    read_only_reason: null,
    scope_access: "active",
    scope_id: null,
    scope_label: null,
    scope_type: "global",
    title: `Conversation ${id}`,
    tool_permissions: ["read"],
    updated_at: "2026-08-23T00:00:00Z",
  };
}

function setupQueryClient(conversationIds: string[]) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Number.POSITIVE_INFINITY },
    },
  });
  const turns: ConversationTurns = {
    items: [],
    next_cursor: null,
    path_revision: 0,
  };
  for (const id of conversationIds) {
    client.setQueryData(conversationKeys.detail(id), detail(id));
    client.setQueryData(conversationKeys.turns(id), turns);
  }
  return {
    client,
    Wrapper({ children }: PropsWithChildren) {
      return (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
    },
  };
}

describe("useConversationSession", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("detaches one conversation locally and lets another submit immediately", async () => {
    const pendingStreams: Array<{
      fail: () => void;
      resolve: () => void;
      signal: AbortSignal;
    }> = [];
    api.streamConversationTurn.mockImplementation(
      ({
        onEvent,
        request,
        signal,
      }: {
        onEvent: (event: {
          type: "error";
          response_id: string;
          error: { retryable: boolean };
        }) => void;
        request: { response_id: string };
        signal: AbortSignal;
      }) =>
        new Promise<void>((resolve) => {
          pendingStreams.push({
            fail: () =>
              onEvent({
                type: "error",
                response_id: request.response_id,
                error: { retryable: false },
              }),
            resolve,
            signal,
          });
        }),
    );
    const { Wrapper } = setupQueryClient(["conversation-a", "conversation-b"]);
    const onConversationCreated = vi.fn();
    const { result, rerender } = renderHook(
      ({ conversationId }: { conversationId: string }) =>
        useConversationSession({
          conversationId,
          onConversationCreated,
          reasoningLevel: "standard",
          scopeType: "global",
        }),
      {
        initialProps: { conversationId: "conversation-a" },
        wrapper: Wrapper,
      },
    );

    let firstSubmission: Promise<void> | undefined;
    act(() => {
      firstSubmission = result.current.sendMessage("Question A");
    });
    await waitFor(() => expect(pendingStreams).toHaveLength(1));
    expect(result.current.conversationBusy).toBe(true);
    await act(async () => {
      await result.current.sendMessage("Blocked duplicate in A");
    });
    expect(api.streamConversationTurn).toHaveBeenCalledTimes(1);

    rerender({ conversationId: "conversation-b" });
    await waitFor(() => {
      expect(pendingStreams[0]?.signal.aborted).toBe(true);
      expect(result.current.conversationBusy).toBe(false);
    });

    let secondSubmission: Promise<void> | undefined;
    act(() => {
      secondSubmission = result.current.sendMessage("Question B");
    });
    await waitFor(() => expect(pendingStreams).toHaveLength(2));
    expect(pendingStreams[1]?.signal.aborted).toBe(false);
    expect(result.current.conversationBusy).toBe(true);

    await act(async () => {
      pendingStreams[0]?.resolve();
      await firstSubmission;
    });
    expect(result.current.activeConversationId).toBe("conversation-b");
    expect(result.current.conversationBusy).toBe(true);

    await act(async () => {
      pendingStreams[1]?.fail();
      pendingStreams[1]?.resolve();
      await secondSubmission;
    });
    expect(result.current.conversationBusy).toBe(false);
    expect(api.streamConversationTurn).toHaveBeenCalledTimes(2);
    expect(onConversationCreated).not.toHaveBeenCalled();
  });
});
