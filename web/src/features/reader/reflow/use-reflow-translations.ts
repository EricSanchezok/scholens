"use client";

import * as React from "react";

import {
  streamReflowBlockTranslation,
  type SelectionTranslationEvent,
} from "./api";

const MAX_CONCURRENT_TRANSLATIONS = 2;
const EMPTY_TRANSLATIONS: Record<string, ReflowBlockTranslationState> = {};

export type ReflowBlockTranslationState = {
  status: "queued" | "streaming" | "completed" | "error";
  text: string;
  cacheHit?: boolean;
  errorCode?: string;
  retryable?: boolean;
};

type TranslationStream = typeof streamReflowBlockTranslation;

export class ReflowTranslationScheduler {
  private readonly active = new Map<string, AbortController>();
  private disposed = false;
  private readonly listeners = new Set<() => void>();
  private readonly queue: string[] = [];
  private snapshot: Record<string, ReflowBlockTranslationState> = {};

  constructor(
    private readonly documentId: string,
    private readonly enabled: boolean,
    private readonly stream: TranslationStream = streamReflowBlockTranslation,
  ) {}

  getSnapshot = () => this.snapshot;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  request = (blockId: string) => {
    if (!this.enabled || this.disposed || this.snapshot[blockId]) return;
    this.update(blockId, { status: "queued", text: "" });
    this.queue.push(blockId);
    this.pump();
  };

  retry = (blockId: string) => {
    if (
      !this.enabled ||
      this.disposed ||
      this.snapshot[blockId]?.status !== "error"
    ) {
      return;
    }
    this.update(blockId, { status: "queued", text: "" });
    this.queue.push(blockId);
    this.pump();
  };

  dispose = () => {
    this.disposed = true;
    this.queue.length = 0;
    this.active.forEach((controller) => controller.abort());
    this.active.clear();
    this.listeners.clear();
  };

  private emit() {
    this.listeners.forEach((listener) => listener());
  }

  private update(
    blockId: string,
    next:
      | ReflowBlockTranslationState
      | ((current: ReflowBlockTranslationState) => ReflowBlockTranslationState),
  ) {
    const current = this.snapshot[blockId] ?? { status: "queued", text: "" };
    const value = typeof next === "function" ? next(current) : next;
    this.snapshot = { ...this.snapshot, [blockId]: value };
    this.emit();
  }

  private handleEvent(blockId: string, event: SelectionTranslationEvent) {
    if (event.type === "start") {
      this.update(blockId, (current) => ({
        ...current,
        cacheHit: event.cacheHit,
        status: "streaming",
      }));
    } else if (event.type === "delta") {
      this.update(blockId, (current) => ({
        ...current,
        status: "streaming",
        text: current.text + event.text,
      }));
    } else if (event.type === "complete") {
      this.update(blockId, (current) => ({
        ...current,
        cacheHit: event.cacheHit,
        status: "completed",
      }));
    } else {
      this.update(blockId, (current) => ({
        ...current,
        errorCode: event.code,
        retryable: event.retryable,
        status: "error",
      }));
    }
  }

  private pump() {
    while (
      !this.disposed &&
      this.active.size < MAX_CONCURRENT_TRANSLATIONS &&
      this.queue.length > 0
    ) {
      const blockId = this.queue.shift();
      if (!blockId || this.snapshot[blockId]?.status !== "queued") continue;
      const controller = new AbortController();
      this.active.set(blockId, controller);
      this.update(blockId, { status: "streaming", text: "" });
      void this.stream({
        blockId,
        documentId: this.documentId,
        signal: controller.signal,
        onEvent: (event) => {
          if (!this.disposed) this.handleEvent(blockId, event);
        },
      })
        .catch((error: unknown) => {
          if (this.disposed || controller.signal.aborted) return;
          this.update(blockId, (current) => ({
            ...current,
            errorCode:
              error instanceof Error ? error.message : "translation_failed",
            retryable: true,
            status: "error",
          }));
        })
        .finally(() => {
          this.active.delete(blockId);
          this.pump();
        });
    }
  }
}

export function useReflowTranslations({
  cacheVersion,
  documentId,
  enabled,
}: {
  cacheVersion?: string;
  documentId: string;
  enabled: boolean;
}) {
  const scheduler = React.useMemo(() => {
    // Preferences are part of the server cache identity; a revision starts a
    // fresh visible-block session even though the scheduler does not inspect it.
    void cacheVersion;
    return new ReflowTranslationScheduler(documentId, enabled);
  }, [cacheVersion, documentId, enabled]);
  React.useEffect(() => () => scheduler.dispose(), [scheduler]);
  const translations = React.useSyncExternalStore(
    scheduler.subscribe,
    scheduler.getSnapshot,
    () => EMPTY_TRANSLATIONS,
  );
  return {
    request: scheduler.request,
    retry: scheduler.retry,
    translations,
  };
}
