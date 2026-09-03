"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { ApiError } from "@/lib/api";
import { readerSelectionKey, type ReaderSelection } from "../reader-selection";
import {
  streamSelectionTranslation,
  translationKeys,
  translationPreferenceQuery,
  updateTranslationPreferences,
  type TranslationPreferences,
} from "./api";

export const AUTO_TRANSLATION_DELAY_MS = 300;
export const TRANSLATION_DELTA_FLUSH_INTERVAL_MS = 50;

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

export function useReaderTranslation({
  documentId,
  selection,
}: {
  documentId: string;
  selection?: ReaderSelection;
}) {
  const queryClient = useQueryClient();
  const preferencesQuery = useQuery(translationPreferenceQuery());
  const preferencesMutation = useMutation({
    mutationFn: updateTranslationPreferences,
    onSuccess: (preferences) =>
      queryClient.setQueryData(translationKeys.current(), preferences),
  });
  const [state, setState] =
    React.useState<SelectionTranslationState>(initialState);
  const abortRef = React.useRef<AbortController | undefined>(undefined);
  const requestIdRef = React.useRef(0);
  const pendingDeltaRef = React.useRef("");
  const deltaFrameRef = React.useRef<number | undefined>(undefined);
  const deltaTimerRef = React.useRef<number | undefined>(undefined);
  const key = readerSelectionKey(selection);
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

  const clearDeltaBuffer = React.useCallback(() => {
    if (deltaFrameRef.current !== undefined) {
      window.cancelAnimationFrame?.(deltaFrameRef.current);
      deltaFrameRef.current = undefined;
    }
    if (deltaTimerRef.current !== undefined) {
      window.clearTimeout(deltaTimerRef.current);
      deltaTimerRef.current = undefined;
    }
    pendingDeltaRef.current = "";
  }, []);

  const flushDeltaBuffer = React.useCallback((requestId: number) => {
    if (requestIdRef.current !== requestId) return;
    if (deltaFrameRef.current !== undefined) {
      window.cancelAnimationFrame?.(deltaFrameRef.current);
      deltaFrameRef.current = undefined;
    }
    if (deltaTimerRef.current !== undefined) {
      window.clearTimeout(deltaTimerRef.current);
      deltaTimerRef.current = undefined;
    }
    const pendingText = pendingDeltaRef.current;
    pendingDeltaRef.current = "";
    if (!pendingText) return;
    setState((current) =>
      requestIdRef.current === requestId
        ? { ...current, translatedText: current.translatedText + pendingText }
        : current,
    );
  }, []);

  const scheduleDeltaFlush = React.useCallback(
    (requestId: number) => {
      if (
        deltaFrameRef.current === undefined &&
        typeof window.requestAnimationFrame === "function"
      ) {
        deltaFrameRef.current = window.requestAnimationFrame(() => {
          deltaFrameRef.current = undefined;
          flushDeltaBuffer(requestId);
        });
      }
      if (deltaTimerRef.current === undefined) {
        deltaTimerRef.current = window.setTimeout(() => {
          deltaTimerRef.current = undefined;
          if (deltaFrameRef.current !== undefined) {
            window.cancelAnimationFrame?.(deltaFrameRef.current);
            deltaFrameRef.current = undefined;
          }
          flushDeltaBuffer(requestId);
        }, TRANSLATION_DELTA_FLUSH_INTERVAL_MS);
      }
    },
    [flushDeltaBuffer],
  );

  const translate = React.useCallback(
    async (
      targetSelection: ReaderSelection,
      trigger: "auto" | "manual" = "manual",
    ) => {
      abortRef.current?.abort();
      clearDeltaBuffer();
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
            if (event.type === "start") {
              setState((current) => ({
                ...current,
                cacheHit: event.cacheHit,
                targetLanguage: event.targetLanguage,
              }));
              return;
            }
            if (event.type === "delta") {
              pendingDeltaRef.current += event.text;
              scheduleDeltaFlush(requestId);
              return;
            }
            flushDeltaBuffer(requestId);
            if (event.type === "complete") {
              setState((current) => ({
                ...current,
                cacheHit: event.cacheHit,
                status: "completed",
              }));
              return;
            }
            setState((current) => ({
              ...current,
              errorCode: event.code,
              errorMessage: event.message,
              retryable: event.retryable,
              status: "error",
            }));
          },
        });
      } catch (error) {
        if (controller.signal.aborted || requestIdRef.current !== requestId) {
          if (requestIdRef.current === requestId) clearDeltaBuffer();
          return;
        }
        flushDeltaBuffer(requestId);
        const edgeBlocked =
          error instanceof ApiError && error.status === 403 && !error.code;
        setState((current) => ({
          ...current,
          errorCode: edgeBlocked
            ? "edge_blocked"
            : error instanceof ApiError
              ? error.code
              : undefined,
          errorMessage: error instanceof Error ? error.message : undefined,
          retryable: !(error instanceof ApiError) || error.status >= 500,
          status: "error",
        }));
      }
    },
    [clearDeltaBuffer, documentId, flushDeltaBuffer, scheduleDeltaFlush],
  );

  React.useEffect(() => {
    abortRef.current?.abort();
    clearDeltaBuffer();
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
  }, [
    clearDeltaBuffer,
    inputKey,
    preferencesQuery.data?.auto_translate_selection,
    translate,
  ]);

  React.useEffect(
    () => () => {
      abortRef.current?.abort();
      clearDeltaBuffer();
      requestIdRef.current += 1;
    },
    [clearDeltaBuffer],
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
