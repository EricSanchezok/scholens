# Scholens MCP connector

For client-specific setup, permissions, capability boundaries, and
troubleshooting, use the public guide at
[`https://scholens.sanchezcloud.net/docs`](https://scholens.sanchezcloud.net/docs).
That production guide pins `uvx --from` to the exact deployed 40-character
release SHA. The repository example below uses the explicitly mutable `main`
development fallback and must not be presented as a release-pinned command.

This official local bridge exposes the same stored-knowledge, Project,
collaboration, Library, ingestion, job, annotation, and research-output tools as
the remote Scholens MCP server. It intentionally does not expose internet paper
discovery. The remote-only `prepare_paper_upload` primitive is replaced with
`upload_local_paper`, which safely reads one PDF beneath an MCP root and uploads
it directly to Scholens staging.

Run it from an MCP host with `uvx`:

```json
{
  "mcpServers": {
    "scholens": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/EricSanchezok/scholens.git@main#subdirectory=mcp-connector",
        "scholens-mcp"
      ],
      "env": {
        "SCHOLENS_MCP_URL": "https://YOUR-SCHOLENS-HOST/mcp",
        "SCHOLENS_ACCESS_KEY": "YOUR_ACCESS_KEY"
      }
    }
  }
}
```

Expose the research repository as an MCP root in the host. If the host cannot
provide roots, add `--allowed-root /absolute/path/to/repository`. Relative paths
must resolve to exactly one file beneath the exposed roots. Symlink escapes,
directories, non-PDF signatures, empty files, and PDFs over 30 MB are rejected.
The remote service receives only the plain filename, size, checksum, and bytes;
the local absolute path is never sent or included in results.

With `read`, `write`, `manage`, and `delete` permission, the bridge exposes 57
tools. It forwards the 56 canonical tools shared by the remote and in-product
Agent, hides the remote-only `prepare_paper_upload` transport primitive, and
adds `upload_local_paper`. Narrower Access Keys see only their authorized
subset. Internet literature discovery and research-output generation remain
intentionally absent.

## Bind a research repository

Create or locate the Scholens Project once, then paste the
`binding_markdown` returned by `create_project` or `get_project` into the
repository's `AGENTS.md` or `README.md`. It has this shape:

```markdown
Scholens project: Chain-of-thought compression
Project ID: 11111111-1111-1111-1111-111111111111
Resource: scholens://projects/11111111-1111-1111-1111-111111111111
```

Agents should use the UUID from that binding and never choose a Project by its
mutable title. `scholens://` resources restore bounded Project, paper,
annotation-thread, and existing-output context. Human researchers can use the
Web URL returned with the same Project manifest to open the corpus and read the
original papers in Scholens.

## Upload behavior

`upload_local_paper` accepts an absolute path beneath an exposed root or a
relative path that resolves beneath exactly one root. It reads at most 30 MB,
checks the extension and PDF signature, hashes the exact bytes, prepares a
short-lived checksummed upload, transfers the bytes, and starts the canonical
asynchronous ingestion. Supply the bound `project_id` to add the completed
paper to that Project; omit it for the personal Library. The completed paper
is also added to the caller's personal Library by default
(`add_to_library=true`); pass `add_to_library=false` to keep a Project upload
Project-only. The tool waits up to 30 seconds by default and returns terminal
state or the latest durable job snapshot; use its next-action guidance and a
bounded `get_job` wait instead of rapid polling.

The authenticated MCP connection and object-storage PUT use separate HTTP
clients. The Scholens Access Key is never attached to the upload request. The
connector opens no listening socket, so NAT and the absence of a public IP do
not affect it. Both endpoints must use HTTPS; plain HTTP is accepted only for
an explicit loopback host during local development. Redirects, URL credentials,
and fragments are rejected before any Access Key or PDF bytes are sent.

For a retry after an uncertain response, reuse the same non-secret
`idempotency_key`. If the PDF transfer completed but Scholens did not confirm
ingestion, the structured error returns `retry_tool=ingest_paper` and exact
`retry_arguments` containing the original `upload_id`; call that last step
directly instead of uploading again. Use a new key for a genuinely new import.
If the Agent host cannot advertise filesystem roots, scope one or more explicit
roots:

```bash
SCHOLENS_MCP_URL=https://scholens.example/mcp \
SCHOLENS_ACCESS_KEY=... \
uv run --directory mcp-connector scholens-mcp \
  --allowed-root /absolute/path/to/research-repository
```

Prefer setting the Access Key through the MCP host's secret environment rather
than a command-line argument, where it may be visible in process listings.

## Verify

From the repository root, after explicit dependency provisioning:

```bash
./scripts/run-gates.sh mcp-connector
```
