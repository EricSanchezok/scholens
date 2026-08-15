"use client";

import {
  useMutation,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useToast } from "@/components/ui";
import {
  conversationKeys,
  deleteConversation,
  removeConversationSummary,
  updateConversation,
  updateConversationSummary,
  type ConversationListResponse,
  type ConversationUpdateRequest,
} from "@/features/conversation";
import type { components } from "@/lib/api/generated/schema";
import { withoutConversationSearchParam } from "./conversation-navigation";

type ConversationSummary = components["schemas"]["ConversationSummaryResponse"];

type ConversationUpdate = {
  conversationId: string;
  optimisticPatch: Partial<ConversationSummary>;
  request: ConversationUpdateRequest;
};

type ConversationListSnapshot = [
  QueryKey,
  ConversationListResponse | undefined,
][];

export type ConversationListController = {
  deleteConversation: (conversation: ConversationSummary) => Promise<void>;
  deletingConversationId?: string;
  renameConversation: (
    conversation: ConversationSummary,
    title: string,
  ) => Promise<void>;
  toggleConversationPinned: (
    conversation: ConversationSummary,
  ) => Promise<void>;
  updatingConversationId?: string;
};

export function useConversationListController({
  activeConversationId,
}: {
  activeConversationId?: string;
}): ConversationListController {
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const toast = useToast();
  const t = useTranslations("WorkspaceShell.sidebar");

  const updateMutation = useMutation<
    ConversationSummary,
    Error,
    ConversationUpdate,
    { snapshots: ConversationListSnapshot }
  >({
    mutationFn: ({ conversationId, request }) =>
      updateConversation(conversationId, request),
    onMutate: async ({ conversationId, optimisticPatch }) => {
      await queryClient.cancelQueries({ queryKey: conversationKeys.lists() });
      const snapshots = queryClient.getQueriesData<ConversationListResponse>({
        queryKey: conversationKeys.lists(),
      });
      queryClient.setQueriesData<ConversationListResponse>(
        { queryKey: conversationKeys.lists() },
        (current) =>
          updateConversationSummary(current, conversationId, optimisticPatch),
      );
      return { snapshots };
    },
    onError: (_error, _variables, context) => {
      for (const [queryKey, snapshot] of context?.snapshots ?? []) {
        queryClient.setQueryData(queryKey, snapshot);
      }
    },
    onSuccess: (conversation) => {
      queryClient.setQueriesData<ConversationListResponse>(
        { queryKey: conversationKeys.lists() },
        (current) =>
          updateConversationSummary(current, conversation.id, conversation),
      );
      queryClient.setQueryData(
        conversationKeys.detail(conversation.id),
        conversation,
      );
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({
        queryKey: conversationKeys.lists(),
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteConversation,
    onSuccess: (_result, conversationId) => {
      queryClient.setQueriesData<ConversationListResponse>(
        { queryKey: conversationKeys.lists() },
        (current) => removeConversationSummary(current, conversationId),
      );
      queryClient.removeQueries({
        queryKey: conversationKeys.detail(conversationId),
      });
      if (conversationId === activeConversationId) {
        router.replace(
          withoutConversationSearchParam(
            pathname,
            searchParams.toString(),
          ) as Route,
          { scroll: false },
        );
      }
    },
  });

  const notifyFailure = React.useCallback(() => {
    toast.notify({ title: t("actionFailed") });
  }, [t, toast]);

  const renameConversation = React.useCallback(
    async (conversation: ConversationSummary, title: string) => {
      try {
        await updateMutation.mutateAsync({
          conversationId: conversation.id,
          optimisticPatch: { title },
          request: { title },
        });
      } catch (error) {
        notifyFailure();
        throw error;
      }
    },
    [notifyFailure, updateMutation],
  );

  const toggleConversationPinned = React.useCallback(
    async (conversation: ConversationSummary) => {
      const pinned = !conversation.pinned_at;
      try {
        await updateMutation.mutateAsync({
          conversationId: conversation.id,
          optimisticPatch: {
            pinned_at: pinned ? new Date().toISOString() : null,
          },
          request: { pinned },
        });
      } catch (error) {
        notifyFailure();
        throw error;
      }
    },
    [notifyFailure, updateMutation],
  );

  const deleteConversationAction = React.useCallback(
    async (conversation: ConversationSummary) => {
      try {
        await deleteMutation.mutateAsync(conversation.id);
      } catch (error) {
        notifyFailure();
        throw error;
      }
    },
    [deleteMutation, notifyFailure],
  );

  return {
    deleteConversation: deleteConversationAction,
    deletingConversationId: deleteMutation.isPending
      ? deleteMutation.variables
      : undefined,
    renameConversation,
    toggleConversationPinned,
    updatingConversationId: updateMutation.isPending
      ? updateMutation.variables?.conversationId
      : undefined,
  };
}
