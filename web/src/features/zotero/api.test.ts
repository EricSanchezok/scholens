import { beforeEach, describe, expect, it, vi } from "vitest";

const client = vi.hoisted(() => ({
  DELETE: vi.fn(),
  GET: vi.fn(),
  POST: vi.fn(),
  PUT: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ apiClient: client }));

import {
  beginZoteroAuthorization,
  startZoteroImport,
  startZoteroSync,
} from "./api";

describe("Zotero API commands", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      "51000000-0000-4000-8000-000000000099",
    );
  });

  it("starts OAuth with an explicit intent and internal return path", async () => {
    client.POST.mockResolvedValue({
      data: { auth_url: "https://www.zotero.org/oauth/authorize" },
    });

    await beginZoteroAuthorization("import", "/library?zotero_import=1");

    expect(client.POST).toHaveBeenCalledWith(
      "/api/v1/integrations/zotero/oauth/authorizations",
      {
        body: {
          intent: "import",
          return_path: "/library?zotero_import=1",
        },
      },
    );
  });

  it("uses a fresh idempotency key for each import batch", async () => {
    client.POST.mockResolvedValue({
      data: { id: "operation-1", kind: "import", status: "queued" },
    });

    await startZoteroImport(["ITEM1", "ITEM2"]);

    expect(client.POST).toHaveBeenCalledWith(
      "/api/v1/integrations/zotero/imports",
      {
        body: { item_keys: ["ITEM1", "ITEM2"] },
        params: {
          header: {
            "Idempotency-Key": "51000000-0000-4000-8000-000000000099",
          },
        },
      },
    );
  });

  it("uses an idempotency key for manual annotation sync", async () => {
    client.POST.mockResolvedValue({
      data: { id: "operation-2", kind: "sync", status: "queued" },
    });

    await startZoteroSync();

    expect(client.POST).toHaveBeenCalledWith(
      "/api/v1/integrations/zotero/sync-runs",
      {
        params: {
          header: {
            "Idempotency-Key": "51000000-0000-4000-8000-000000000099",
          },
        },
      },
    );
  });
});
