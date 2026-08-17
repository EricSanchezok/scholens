import { clientEnvironment } from "@/lib/env/client";
import {
  ACCESS_KEYS_SETTINGS_PATH,
  DOCUMENTATION_PATH,
  PRODUCTION_APP_ORIGIN,
  SOURCE_REPOSITORY_URL,
} from "@/lib/product";

export const MCP_TOOL_COUNT = 56;
export const MCP_MAX_LOCAL_PDF_BYTES = 30 * 1024 * 1024;
export const DEVELOPMENT_CONNECTOR_REF = "main";

const releaseShaPattern = /^[0-9a-f]{40}$/;
const connectorRepository =
  "git+https://github.com/EricSanchezok/scholens.git";

export const documentationAnchors = {
  quickStart: "quick-start",
  mcpSetup: "mcp-setup",
  permissions: "permissions",
  capabilities: "capabilities",
  repositoryBinding: "repository-binding",
  security: "security",
  troubleshooting: "troubleshooting",
} as const;

export const documentationClients = [
  "codex",
  "claude-desktop",
  "cursor",
  "generic",
] as const;

export type DocumentationClient = (typeof documentationClients)[number];

export function isDocumentationClient(
  value: unknown,
): value is DocumentationClient {
  return documentationClients.includes(value as DocumentationClient);
}

export const mcpPermissions = [
  {
    id: "read",
    summary: "Search and read stored papers, Projects, annotations, and outputs.",
  },
  {
    id: "write",
    summary: "Create and update research content and start ingestion jobs.",
  },
  {
    id: "manage",
    summary: "Manage collaborators, invitations, ownership, and public sharing.",
  },
  {
    id: "delete",
    summary: "Run destructive lifecycle operations after explicit confirmation.",
  },
] as const;

export const mcpCapabilityGroups = [
  {
    id: "papers",
    count: 7,
    summary: "Stored paper search, bounded content, citation, and download",
  },
  {
    id: "projects",
    count: 19,
    summary: "Projects, papers, membership, invitations, and ownership",
  },
  {
    id: "library",
    count: 14,
    summary: "Personal Library, sharing, and tags",
  },
  {
    id: "ingestion",
    count: 6,
    summary: "Known-source ingestion, upload preparation, and jobs",
  },
  {
    id: "annotations",
    count: 8,
    summary: "Annotation threads and comments",
  },
  {
    id: "outputs",
    count: 2,
    summary: "Reading existing research outputs",
  },
] as const;

export const mcpResources = [
  "scholens://library",
  "scholens://projects",
] as const;

export const mcpResourceTemplates = [
  "scholens://projects/{project_id}",
  "scholens://papers/{document_id}",
  "scholens://annotation-threads/{thread_id}",
  "scholens://research-outputs/{item_id}",
] as const;

export function mcpEndpointFromApiUrl(apiUrl: string): string {
  const api = new URL(apiUrl);
  return new URL("/mcp", api.origin).toString();
}

export function connectorSourceFromReleaseSha(releaseSha: string) {
  const pinned = releaseShaPattern.test(releaseSha);
  const ref = pinned ? releaseSha : DEVELOPMENT_CONNECTOR_REF;
  return {
    kind: pinned ? ("release" as const) : ("development" as const),
    ref,
    url: `${connectorRepository}@${ref}#subdirectory=mcp-connector`,
  };
}

export type DocumentationFacts = ReturnType<typeof createDocumentationFacts>;

export function createDocumentationFacts(
  apiUrl = clientEnvironment.NEXT_PUBLIC_API_URL,
  appOrigin = PRODUCTION_APP_ORIGIN,
  releaseSha = clientEnvironment.NEXT_PUBLIC_RELEASE_SHA,
) {
  const mcpUrl = mcpEndpointFromApiUrl(apiUrl);
  const origin = new URL(appOrigin).origin;
  const connectorSource = connectorSourceFromReleaseSha(releaseSha);
  const localConnector = JSON.stringify(
    {
      mcpServers: {
        scholens: {
          command: "uvx",
          args: ["--from", connectorSource.url, "scholens-mcp"],
          env: {
            SCHOLENS_MCP_URL: mcpUrl,
            SCHOLENS_ACCESS_KEY: "YOUR_ACCESS_KEY",
          },
        },
      },
    },
    null,
    2,
  );

  return {
    mcpUrl,
    origin,
    anchors: documentationAnchors,
    docsUrl: `${origin}${DOCUMENTATION_PATH}`,
    setupUrl: `${origin}${DOCUMENTATION_PATH}#${documentationAnchors.mcpSetup}`,
    docsMarkdownUrl: `${origin}/docs.md`,
    accessKeysUrl: `${origin}${ACCESS_KEYS_SETTINGS_PATH}`,
    repositoryUrl: SOURCE_REPOSITORY_URL,
    toolCount: MCP_TOOL_COUNT,
    maxLocalPdfMegabytes: MCP_MAX_LOCAL_PDF_BYTES / 1024 / 1024,
    connectorSource,
    clients: {
      codex: {
        language: "toml",
        referenceUrl: "https://learn.chatgpt.com/docs/extend/mcp.md",
        configuration: `[mcp_servers.scholens]\nurl = "${mcpUrl}"\nbearer_token_env_var = "SCHOLENS_ACCESS_KEY"`,
        credential: `export SCHOLENS_ACCESS_KEY="YOUR_ACCESS_KEY"`,
      },
      "claude-desktop": {
        language: "json",
        referenceUrl:
          "https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop",
        configuration: localConnector,
        credential: "Store the key only in your private Claude Desktop configuration.",
      },
      cursor: {
        language: "json",
        referenceUrl: "https://cursor.com/docs/mcp",
        configuration: JSON.stringify(
          {
            mcpServers: {
              scholens: {
                url: mcpUrl,
                headers: {
                  Authorization: "Bearer ${env:SCHOLENS_ACCESS_KEY}",
                },
              },
            },
          },
          null,
          2,
        ),
        credential: `export SCHOLENS_ACCESS_KEY="YOUR_ACCESS_KEY"`,
      },
      generic: {
        language: "text",
        referenceUrl: null,
        configuration: `Transport: Streamable HTTP\nURL: ${mcpUrl}\nAuthorization: Bearer \${SCHOLENS_ACCESS_KEY}`,
        credential: `export SCHOLENS_ACCESS_KEY="YOUR_ACCESS_KEY"`,
      },
    },
    localConnector,
    bindingMarkdown: [
      "Scholens project: YOUR_PROJECT_TITLE",
      "Project ID: 11111111-1111-1111-1111-111111111111",
      "Resource: scholens://projects/11111111-1111-1111-1111-111111111111",
    ].join("\n"),
  };
}

export function renderDocumentationMarkdown(
  facts = createDocumentationFacts(),
): string {
  const capabilities = mcpCapabilityGroups
    .map((group) => `- **${group.count} tools** — ${group.summary}`)
    .join("\n");
  const permissions = mcpPermissions
    .map((permission) => `- \`${permission.id}\` — ${permission.summary}`)
    .join("\n");
  const templates = mcpResourceTemplates
    .map((resource) => `- \`${resource}\``)
    .join("\n");

  return `# Scholens MCP setup

Scholens gives research agents durable access to papers, Projects, Library items, annotations, ingestion jobs, and existing research outputs. It manages stored knowledge; it does not discover literature on the public internet or generate new research outputs.

Human guide: ${facts.setupUrl}

## Quick start

1. Open [Access keys](${facts.accessKeysUrl}) and create a key with only the permissions your client needs.
2. Copy the secret immediately. Scholens shows it only once.
3. Export it as \`SCHOLENS_ACCESS_KEY\` or place the placeholder value in a private client configuration.
4. Connect to \`${facts.mcpUrl}\`, restart the client, and inspect the Scholens tools.

## Codex

Set the credential in the environment:

\`\`\`sh
${facts.clients.codex.credential}
\`\`\`

Add this to \`~/.codex/config.toml\` or a trusted project's \`.codex/config.toml\`:

\`\`\`toml
${facts.clients.codex.configuration}
\`\`\`

Restart the Codex app, CLI, or IDE extension after changing MCP configuration.

Official client reference: ${facts.clients.codex.referenceUrl}

## Claude Desktop

Claude Desktop uses the official local connector so the Scholens Access Key stays in a local stdio configuration and local PDF upload is available. This avoids relying on the remote custom-connector flow, which does not currently accept a static Bearer token:

\`\`\`json
${facts.clients["claude-desktop"].configuration}
\`\`\`

Replace \`YOUR_ACCESS_KEY\` in the private Claude Desktop configuration, then restart Claude Desktop.

Official client reference: ${facts.clients["claude-desktop"].referenceUrl}

## Cursor

Set \`SCHOLENS_ACCESS_KEY\` in the environment and add this to a project \`.cursor/mcp.json\` or the global Cursor MCP configuration:

\`\`\`json
${facts.clients.cursor.configuration}
\`\`\`

Official client reference: ${facts.clients.cursor.referenceUrl}

## Generic Streamable HTTP client

\`\`\`text
${facts.clients.generic.configuration}
\`\`\`

The client must send the Access Key as an Authorization Bearer token on every MCP request.

## Local PDF upload

Use the local \`uvx\` connector when an agent must read a PDF from a repository. It replaces \`prepare_paper_upload\` with \`upload_local_paper\`, accepts only PDFs beneath an exposed MCP root or explicit \`--allowed-root\`, rejects files larger than ${facts.maxLocalPdfMegabytes} MB, and never sends the absolute local path to Scholens.

${
  facts.connectorSource.kind === "release"
    ? `The connector source is pinned to the deployed Scholens release \`${facts.connectorSource.ref}\`.`
    : "Development preview: the connector source uses the mutable `main` branch. Production documentation replaces it with the exact 40-character deployed release SHA."
}

\`\`\`json
${facts.localConnector}
\`\`\`

## Permissions

${permissions}

Start with \`read\`; add \`write\` for ingestion and content updates, \`manage\` for collaboration or public sharing, and \`delete\` only when destructive lifecycle actions are required. Concrete resources are authorized again even when the key exposes a tool.

## Capabilities

A fully authorized remote or local MCP connection exposes ${facts.toolCount} tools:

${capabilities}

Static resources:

${mcpResources.map((resource) => `- \`${resource}\``).join("\n")}

Resource templates:

${templates}

## Bind a research repository

Call \`create_project\` or \`get_project\` once and paste the returned \`binding_markdown\` into the repository's \`AGENTS.md\` or \`README.md\`. Always bind with the immutable Project UUID, not its editable title.

\`\`\`markdown
${facts.bindingMarkdown}
\`\`\`

## Security and confirmations

- Store Access Keys in secret environment/configuration facilities; never place them in source control, URLs, logs, or screenshots.
- Use the shortest practical expiration and the minimum permission set.
- Destructive or externally visible tools return a state-bound preview first. Repeat the same call with the unexpired confirmation token to execute it.
- The local connector sends the Access Key only to Scholens; object-storage uploads use separate checksummed authorization.

## Troubleshooting

- **401 Unauthorized:** the key is missing, expired, revoked, or was copied incorrectly. Create or export a valid key, then restart the client.
- **A tool is missing:** the key lacks the permission that exposes it. Edit the key or create a narrowly scoped replacement.
- **Client does not refresh:** restart Codex, Claude Desktop, or Cursor after changing MCP configuration.
- **Local file rejected:** expose the repository as an MCP root or pass \`--allowed-root\`; use a non-empty PDF no larger than ${facts.maxLocalPdfMegabytes} MB.
- **Long operation:** ingestion is asynchronous. Poll \`get_job\` with the returned job UUID.

Web documentation: ${facts.docsUrl}

Repository: ${facts.repositoryUrl}
`;
}

export function renderLlmsText(facts = createDocumentationFacts()): string {
  return `# Scholens

> Scholens is a durable research workspace for stored papers, Projects, Library items, annotations, ingestion jobs, and existing research outputs.

- Human MCP guide: ${facts.docsUrl}
- MCP client setup: ${facts.setupUrl}
- Complete machine-readable MCP guide: ${facts.docsMarkdownUrl}
- Streamable HTTP endpoint: ${facts.mcpUrl}
- Connector source: ${facts.connectorSource.kind === "release" ? `release ${facts.connectorSource.ref}` : "development fallback @main (mutable)"}
- Access key settings: ${facts.accessKeysUrl}
- Source repository: ${facts.repositoryUrl}

Important boundary: Scholens MCP does not discover literature on the public internet and does not generate new research outputs. A fully authorized connection exposes ${facts.toolCount} tools. Use the local uvx connector for repository PDF upload.
`;
}
