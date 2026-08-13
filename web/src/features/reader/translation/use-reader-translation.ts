"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { ApiError } from "@/lib/api";
import type { ReaderSelection } from "../components/pdf-page";
import {
  streamSelectionTranslation,
  translationKeys,
  translationQueries,
  updateTranslationPreferences,
  type TranslationPreferences,
} from "./api";

export const AUTO_TRANSLATION_DELAY_MS = 300;

export type SelectionTranslationState = {
  cacheHit: boolean;
  errorCode?: string;
  errorMessage?: string;
  retryable: boolean;
  selection?: ReaderSelection;
  status: "idle" | "ready" | "streaming" | "completed" | "error";
  targetLanguage?: string;
  translatedText: string;
  trigger?: "auto" | "manual";
};

const initialState: SelectionTranslationState = {
  cacheHit: false,
  retryable: false,
  status: "idle",
  translatedText: "",
};

function selectionKey(selection: ReaderSelection | undefined) {
  if (!selection) return undefined;
  return JSON.stringify([
    selection.document_id,
    selection.page_number,
    selection.selected_text,
    selection.anchor,
  ]);
}

export function useReaderTranslation({
  documentId,
  selection,
}: {
  documentId: string;
  selection?: ReaderSelection;
}) {
  const queryClient = useQueryClient();
  const preferencesQuery = useQuery(translationQueries.preferences());
  const preferencesMutation = useMutation({
    mutationFn: updateTranslationPreferences,
    onSuccess: (preferences) =>
      queryClient.setQueryData(translationKeys.preferences(), preferences),
  });
  const [state, setState] =
    React.useState<SelectionTranslationState>(initialState);
  const abortRef = React.useRef<AbortController | undefined>(undefined);
  const requestIdRef = React.useRef(0);
  const key = selectionKey(selection);
  const selectionRef = React.useRef(selection);
  selectionRef.current = selection;
  const preferencesFingerprint = preferencesQuery.data
    ? JSON.stringify([
        preferencesQuery.data.source_language,
        preferencesQuery.data.target_language,
        preferencesQuery.data.custom_instructions,
      ])
    : "loading";
  const inputKey = `${key ?? "none"}:${preferencesFingerprint}`;
  const previousInputKeyRef = React.useRef<string | undefined>(undefined);

  const translate = React.useCallback(
    async (
      targetSelection: ReaderSelection,
      trigger: "auto" | "manual" = "manual",
    ) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const requestId = ++requestIdRef.current;
      setState({
        cacheHit: false,
        retryable: false,
        selection: targetSelection,
        status: "streaming",
        translatedText: "",
        trigger,
      });
      try {
        await streamSelectionTranslation({
          documentId,
          text: targetSelection.selected_text,
          signal: controller.signal,
          onEvent: (event) => {
            if (requestIdRef.current !== requestId) return;
            setState((current) => {
              if (event.type === "start") {
                return {
                  ...current,
                  cacheHit: event.cacheHit,
                  targetLanguage: event.targetLanguage,
                };
              }
              if (event.type === "delta") {
                return {
                  ...current,
                  translatedText: current.translatedText + event.text,
                };
              }
              if (event.type === "complete") {
                return {
                  ...current,
                  cacheHit: event.cacheHit,
                  status: "completed",
                };
              }
              return {
                ...current,
                errorCode: event.code,
                errorMessage: event.message,
                retryable: event.retryable,
                status: "error",
              };
            });
          },
        });
      } catch (error) {
        if (controller.signal.aborted || requestIdRef.current !== requestId) {
          return;
        }
        setState((current) => ({
          ...current,
          errorCode: error instanceof ApiError ? error.code : undefined,
          errorMessage: error instanceof Error ? error.message : undefined,
          retryable: !(error instanceof ApiError) || error.status >= 500,
          status: "error",
        }));
      }
    },
    [documentId],
  );

  React.useEffect(() => {
    abortRef.current?.abort();
    requestIdRef.current += 1;
    const currentSelection = selectionRef.current;
    const inputChanged = previousInputKeyRef.current !== inputKey;
    previousInputKeyRef.current = inputKey;
    if (!currentSelection) {
      setState((current) =>
        current.status === "ready" || current.status === "streaming"
          ? initialState
          : current,
      );
      return;
    }

    if (inputChanged) {
      setState({
        ...initialState,
        selection: currentSelection,
        status: "ready",
      });
    }
    if (!preferencesQuery.data?.auto_translate_selection) return;
    const timeout = window.setTimeout(() => {
      void translate(currentSelection, "auto");
    }, AUTO_TRANSLATION_DELAY_MS);
    return () => window.clearTimeout(timeout);
  }, [inputKey, preferencesQuery.data?.auto_translate_selection, translate]);

  React.useEffect(
    () => () => {
      abortRef.current?.abort();
      requestIdRef.current += 1;
    },
    [],
  );

  const effectivePreferences: TranslationPreferences | undefined =
    preferencesMutation.isPending && preferencesMutation.variables
      ? {
          ...preferencesMutation.variables,
          custom_instructions:
            preferencesMutation.variables.custom_instructions ?? null,
        }
      : preferencesQuery.data;

  return {
    effectivePreferences,
    preferencesError:
      preferencesMutation.error ?? preferencesQuery.error ?? undefined,
    preferencesLoading: preferencesQuery.isPending,
    preferencesSaving: preferencesMutation.isPending,
    retry: () =>
      state.selection
        ? translate(state.selection, state.trigger ?? "manual")
        : Promise.resolve(),
    state,
    translate: (trigger: "auto" | "manual" = "manual") =>
      selection ? translate(selection, trigger) : Promise.resolve(),
    updatePreferences: (
      patch: Partial<TranslationPreferences>,
    ): Promise<TranslationPreferences> => {
      const current = effectivePreferences;
      if (!current)
        return Promise.reject(new Error("Preferences are not loaded"));
      return preferencesMutation.mutateAsync({ ...current, ...patch });
    },
  };
}
