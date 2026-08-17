import { describe, expect, it } from "vitest";

import { GET as getDocumentationMarkdown } from "@/app/docs.md/route";
import { GET as getLlmsText } from "@/app/llms.txt/route";

describe("machine documentation routes", () => {
  it("serves the complete guide as markdown", async () => {
    const response = getDocumentationMarkdown(
      new Request("https://scholens.example/docs.md"),
    );

    expect(response.headers.get("content-type")).toBe(
      "text/markdown; charset=utf-8",
    );
    const body = await response.text();
    expect(body).toContain("# Scholens MCP setup");
    expect(body).toContain("https://scholens.example/docs");
  });

  it("serves the compact LLM index as plain text", async () => {
    const response = getLlmsText(
      new Request("https://scholens.example/llms.txt"),
    );

    expect(response.headers.get("content-type")).toBe(
      "text/plain; charset=utf-8",
    );
    expect(await response.text()).toContain(
      "Complete machine-readable MCP guide",
    );
  });
});
