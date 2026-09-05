import { describe, expect, it } from "vitest";

import {
  DEVELOPMENT_CONNECTOR_REF,
  MCP_TOOL_COUNT,
  connectorSourceFromReleaseSha,
  createDocumentationFacts,
  documentationClients,
  isDocumentationClient,
  mcpCapabilityGroups,
  mcpEndpointFromApiUrl,
  renderDocumentationMarkdown,
  renderLlmsText,
} from "./documentation-content";

describe("documentation content", () => {
  it("derives the root MCP endpoint from any API base path", () => {
    expect(
      mcpEndpointFromApiUrl("https://scholens.sanchezcloud.net/api/v1"),
    ).toBe("https://scholens.sanchezcloud.net/mcp");
    expect(mcpEndpointFromApiUrl("http://127.0.0.1:7301")).toBe(
      "http://127.0.0.1:7301/mcp",
    );
  });

  it("pins production connectors and labels the development fallback", () => {
    const releaseSha = "1".repeat(40);
    expect(connectorSourceFromReleaseSha(releaseSha)).toEqual({
      kind: "release",
      ref: releaseSha,
      url: `git+https://github.com/EricSanchezok/scholens.git@${releaseSha}#subdirectory=mcp-connector`,
    });
    expect(connectorSourceFromReleaseSha("development")).toEqual({
      kind: "development",
      ref: DEVELOPMENT_CONNECTOR_REF,
      url: "git+https://github.com/EricSanchezok/scholens.git@main#subdirectory=mcp-connector",
    });
  });

  it("keeps the reviewed capability groups aligned with the catalog total", () => {
    expect(
      mcpCapabilityGroups.reduce((total, group) => total + group.count, 0),
    ).toBe(MCP_TOOL_COUNT);
  });

  it("publishes all supported client examples without embedding a real key", () => {
    const releaseSha = "a".repeat(40);
    const facts = createDocumentationFacts(
      "https://scholens.sanchezcloud.net/api/v1",
      "https://scholens.sanchezcloud.net",
      releaseSha,
    );

    expect(Object.keys(facts.clients)).toEqual(documentationClients);
    expect(facts.clients.codex.configuration).toContain(
      'bearer_token_env_var = "SCHOLENS_ACCESS_KEY"',
    );
    expect(facts.clients.codex.configuration).toContain(
      "tool_timeout_sec = 270",
    );
    expect(facts.clients.cursor.configuration).toContain(
      "Bearer ${env:SCHOLENS_ACCESS_KEY}",
    );
    expect(facts.clients["claude-desktop"].configuration).toContain(
      "YOUR_ACCESS_KEY",
    );
    expect(facts.localConnector).toContain(`@${releaseSha}#subdirectory=`);
    expect(facts.localConnector).not.toContain("@main#subdirectory=");
    expect(JSON.stringify(facts)).toContain("YOUR_ACCESS_KEY");
    expect(JSON.stringify(facts)).not.toMatch(/sk_scholens_[A-Za-z0-9_-]{43}/);
  });

  it("validates shareable client selections", () => {
    expect(isDocumentationClient("codex")).toBe(true);
    expect(isDocumentationClient("claude-desktop")).toBe(true);
    expect(isDocumentationClient(["cursor"])).toBe(false);
    expect(isDocumentationClient("unknown")).toBe(false);
  });

  it("renders complete markdown and concise llms indexes from the same facts", () => {
    const facts = createDocumentationFacts(
      "https://scholens.sanchezcloud.net/api/v1",
    );
    const markdown = renderDocumentationMarkdown(facts);
    const llms = renderLlmsText(facts);

    expect(markdown).toContain("# Scholens MCP setup");
    expect(markdown).toContain(facts.mcpUrl);
    expect(markdown).toContain(facts.setupUrl);
    expect(markdown).toContain(`${MCP_TOOL_COUNT} tools`);
    expect(markdown).toContain("scholens://projects/{project_id}");
    expect(llms).toContain(facts.docsMarkdownUrl);
    expect(llms).toContain(facts.setupUrl);
    expect(llms).toContain(facts.repositoryUrl);
  });
});
