import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/generated/schema";
import { ApiError } from "@/lib/api/errors";
import {
  type PreparedPaperUpload,
  usePaperIngestions,
} from "./use-paper-ingestions";

const api = vi.hoisted(() => ({
  cancelPaperIngestion: vi.fn(),
  libraryKeys: {
    all: ["library"] as const,
    summary: () => ["library", "summary"] as const,
  },
  retryPaperIngestion: vi.fn(),
  uploadPaperFile: vi.fn(),
  uploadPaperSource: vi.fn(),
}));

vi.mock("./api", () => api);

type Ingestion = components["schemas"]["LibraryPaperIngestionResponse"];

function accepted(id: string, displayName: string): Ingestion {
  return {
    created_at: "2026-08-12T02:00:00Z",
    display_name: displayName,
    document_id: "00000000-0000-4000-8000-000000000099",
    failure: null,
    id,
    project_id: null,
    source_kind: "upload",
    stage: "queued",
    state: "queued",
  };
}

function upload(index: number): PreparedPaperUpload {
  return {
    contentDigest: `digest-${index}`,
    file: new File([`pdf-${index}`], `paper-${index}.pdf`, {
      type: "application/pdf",
    }),
    id: `local-${index}`,
    idempotencyKey: `key-${index}`,
  };
}

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

describe("usePaperIngestions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.cancelPaperIngestion.mockResolvedValue(undefined);
  });

  it("uploads at most three files concurrently", async () => {
    const resolvers: Array<(value: Ingestion) => void> = [];
    api.uploadPaperFile.mockImplementation(
      () =>
        new Promise<Ingestion>((resolve) => {
          resolvers.push((value) => resolve(value));
        }),
    );
    const files = [upload(1), upload(2), upload(3), upload(4)];
    const { result } = renderHook(() => usePaperIngestions([]), {
      wrapper: wrapper(),
    });

    act(() => result.current.startUploads(files));

    await waitFor(() => expect(api.uploadPaperFile).toHaveBeenCalledTimes(3));
    expect(result.current.rows.find((row) => row.id === "local-4")?.state).toBe(
      "queued",
    );

    await act(async () => {
      resolvers[0]?.(accepted("server-1", "paper-1.pdf"));
    });
    await waitFor(() => expect(api.uploadPaperFile).toHaveBeenCalledTimes(4));

    await act(async () => {
      resolvers[1]?.(accepted("server-2", "paper-2.pdf"));
      resolvers[2]?.(accepted("server-3", "paper-3.pdf"));
      resolvers[3]?.(accepted("server-4", "paper-4.pdf"));
    });
  });

  it("keeps one failed file retryable without hiding accepted siblings", async () => {
    api.uploadPaperFile.mockImplementation((file: File) =>
      file.name === "paper-1.pdf"
        ? Promise.reject(new Error("offline"))
        : Promise.resolve(accepted("server-2", file.name)),
    );
    const { result } = renderHook(() => usePaperIngestions([]), {
      wrapper: wrapper(),
    });

    act(() => result.current.startUploads([upload(1), upload(2)]));

    await waitFor(() => {
      expect(
        result.current.rows.find((row) => row.id === "local-1")?.state,
      ).toBe("failed");
      expect(
        result.current.rows.find((row) => row.id === "server-2")?.state,
      ).toBe("queued");
    });
  });

  it("does not start duplicate content twice", async () => {
    api.uploadPaperFile.mockResolvedValue(accepted("server-1", "paper-1.pdf"));
    const first = upload(1);
    const duplicate = {
      ...upload(2),
      contentDigest: first.contentDigest,
    };
    const { result } = renderHook(() => usePaperIngestions([]), {
      wrapper: wrapper(),
    });

    act(() => result.current.startUploads([first, duplicate]));

    await waitFor(() => expect(api.uploadPaperFile).toHaveBeenCalledTimes(1));
    expect(api.uploadPaperFile).toHaveBeenCalledWith(
      first.file,
      first.contentDigest,
      expect.objectContaining({ idempotencyKey: first.idempotencyKey }),
    );
  });

  it("removes a queued file without ever starting its request", async () => {
    const resolvers: Array<(value: Ingestion) => void> = [];
    api.uploadPaperFile.mockImplementation(
      () =>
        new Promise<Ingestion>((resolve) => {
          resolvers.push(resolve);
        }),
    );
    const files = [upload(1), upload(2), upload(3), upload(4)];
    const { result } = renderHook(() => usePaperIngestions([]), {
      wrapper: wrapper(),
    });

    act(() => result.current.startUploads(files));
    await waitFor(() => expect(api.uploadPaperFile).toHaveBeenCalledTimes(3));
    await act(() => result.current.cancel("local-4"));
    expect(result.current.rows.some((row) => row.id === "local-4")).toBe(false);

    await act(async () => {
      resolvers[0]?.(accepted("server-1", "paper-1.pdf"));
    });
    await waitFor(() =>
      expect(
        api.uploadPaperFile.mock.calls.every(
          ([file]) => (file as File).name !== "paper-4.pdf",
        ),
      ).toBe(true),
    );

    await act(async () => {
      resolvers[1]?.(accepted("server-2", "paper-2.pdf"));
      resolvers[2]?.(accepted("server-3", "paper-3.pdf"));
    });
  });

  it("replays an aborted upload with the same key and cancels an accepted race", async () => {
    let first = true;
    api.uploadPaperFile.mockImplementation(
      (
        file: File,
        _contentDigest: string,
        options: { idempotencyKey: string; signal: AbortSignal },
      ) => {
        if (!first) return Promise.resolve(accepted("server-race", file.name));
        first = false;
        return new Promise<Ingestion>((_resolve, reject) => {
          options.signal.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
      },
    );
    const { result } = renderHook(() => usePaperIngestions([]), {
      wrapper: wrapper(),
    });

    act(() => result.current.startUploads([upload(1)]));
    await waitFor(() => expect(api.uploadPaperFile).toHaveBeenCalledTimes(1));
    await act(() => result.current.cancel("local-1"));

    expect(result.current.rows).toEqual([]);
    await waitFor(() => expect(api.uploadPaperFile).toHaveBeenCalledTimes(2));
    expect(api.uploadPaperFile.mock.calls[0]?.[2].idempotencyKey).toBe("key-1");
    expect(api.uploadPaperFile.mock.calls[1]?.[2].idempotencyKey).toBe("key-1");
    await waitFor(() =>
      expect(api.cancelPaperIngestion).toHaveBeenCalledWith(
        "server-race",
        expect.any(AbortSignal),
      ),
    );
  });

  it("does not replay a definitively rejected upload when the user removes it", async () => {
    api.uploadPaperFile.mockRejectedValue(
      new ApiError("Unreadable PDF", 422, "invalid_pdf"),
    );
    const { result } = renderHook(() => usePaperIngestions([]), {
      wrapper: wrapper(),
    });

    act(() => result.current.startUploads([upload(1)]));
    await waitFor(() => expect(result.current.rows[0]?.state).toBe("failed"));
    await act(() => result.current.cancel("local-1"));

    expect(result.current.rows).toEqual([]);
    expect(api.uploadPaperFile).toHaveBeenCalledTimes(1);
  });

  it("cancels a source accepted at the same moment as a local abort", async () => {
    let resolveSource: ((value: Ingestion) => void) | undefined;
    api.uploadPaperSource.mockImplementation(
      () =>
        new Promise<Ingestion>((resolve) => {
          resolveSource = resolve;
        }),
    );
    const { result } = renderHook(() => usePaperIngestions([]), {
      wrapper: wrapper(),
    });
    const controller = new AbortController();
    const source = { kind: "arxiv" as const, value: "1706.03762" };
    let submission: Promise<unknown> | undefined;

    act(() => {
      submission = result.current.submitSource({
        idempotencyKey: "source-key",
        signal: controller.signal,
        source,
      });
    });
    await waitFor(() => expect(api.uploadPaperSource).toHaveBeenCalledTimes(1));
    controller.abort();
    await act(async () => {
      resolveSource?.(accepted("source-race", "arXiv 1706.03762"));
      await expect(submission).rejects.toMatchObject({ name: "AbortError" });
    });

    expect(api.cancelPaperIngestion).toHaveBeenCalledWith("source-race");
    expect(api.uploadPaperSource).toHaveBeenCalledTimes(1);
    expect(result.current.rows).toEqual([]);
  });
});
