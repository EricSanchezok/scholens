#!/usr/bin/env python3
"""Local wire-level MCP E2E driver for the Scholens tool set (PR4).

Talks to a live local Server at ``SCHOLENS_E2E_URL`` (default
``http://127.0.0.1:7301/mcp``) with a real Scholens Access Key
(``SCHOLENS_ACCESS_KEY``), lists the advertised tools, and exercises the
full tool matrix. For every call it validates ``structuredContent``
against the tool's advertised ``outputSchema`` with a strict JSON Schema
validator (Draft 2020-12 + format checks, the ajv-equivalent behaviour of
the TypeScript SDK). A response that fails schema validation is exactly
the production ``-32602`` masking failure this Blueprint eliminates.

Classification rule (per Blueprint):
  - success result                 -> OK
  - structured error (isError)     -> ERROR (must carry a real error code)
  - schema-validation failure      -> MASKED (failure)
  - transport/JSON-RPC error       -> FAILURE

The driver is self-contained (stdlib + httpx + jsonschema, both already
in the server venv). It discovers the seeded library paper instead of
hardcoding UUIDs so it can run against any disposable local product
schema.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass

import httpx
import jsonschema

BASE_URL = os.environ.get("SCHOLENS_E2E_URL", "http://127.0.0.1:7301/mcp")
ACCESS_KEY = os.environ.get("SCHOLENS_ACCESS_KEY", "")
PROTOCOL_VERSION = "2025-11-25"

if not ACCESS_KEY:
    sys.exit("SCHOLENS_ACCESS_KEY is required")


class E2EFailure(RuntimeError):
    pass


@dataclass
class Case:
    tool: str
    arguments: dict[str, object]
    expect: str = "either"  # success | error | either
    note: str = ""


@dataclass
class Outcome:
    tool: str
    expect: str
    result: str  # OK | ERROR | MASKED | FAILURE
    detail: str
    note: str = ""


class Driver:
    def __init__(self) -> None:
        self.outcomes: list[Outcome] = []
        self.tools: dict[str, dict[str, object]] = {}
        self.document_id: str | None = None
        self._validator_cache: dict[str, jsonschema.Draft202012Validator] = {}

    # -- protocol helpers ----------------------------------------------------

    def call(
        self, client: httpx.Client, method: str, params: dict[str, object]
    ) -> dict[str, object]:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        response = client.post(BASE_URL, json=payload, timeout=60)
        if response.status_code != 200:
            raise E2EFailure(
                f"{method}: HTTP {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        if "error" in body:
            raise E2EFailure(
                f"{method}: JSON-RPC error: {json.dumps(body['error'])[:300]}"
            )
        return body["result"]

    def validator(self, schema: dict[str, object]) -> jsonschema.Draft202012Validator:
        key = json.dumps(schema, sort_keys=True)
        cached = self._validator_cache.get(key)
        if cached is None:
            cached = jsonschema.Draft202012Validator(
                schema,
                format_checker=jsonschema.FormatChecker(),
            )
            self._validator_cache[key] = cached
        return cached

    def run_case(self, client: httpx.Client, case: Case) -> Outcome:
        try:
            result = self.call(
                client, "tools/call", {"name": case.tool, "arguments": case.arguments}
            )
        except E2EFailure as exc:
            return Outcome(case.tool, case.expect, "FAILURE", str(exc), case.note)

        structured = result.get("structuredContent")
        if structured is None:
            return Outcome(
                case.tool,
                case.expect,
                "FAILURE",
                "tools/call returned no structuredContent",
                case.note,
            )
        schema = self.tools.get(case.tool)
        if schema is None:
            return Outcome(
                case.tool, case.expect, "FAILURE", "tool not advertised", case.note
            )
        errors = list(self.validator(schema).iter_errors(structured))
        is_error = bool(result.get("isError"))

        if errors:
            message = "; ".join(error.message for error in errors[:3])
            return Outcome(case.tool, case.expect, "MASKED", message, case.note)
        if is_error:
            code = str(structured.get("error", {}).get("code", "missing"))
            if case.expect == "success":
                return Outcome(
                    case.tool,
                    case.expect,
                    "ERROR",
                    f"unexpected error {code}",
                    case.note,
                )
            return Outcome(case.tool, case.expect, "ERROR", f"code={code}", case.note)
        if case.expect == "error":
            return Outcome(
                case.tool,
                case.expect,
                "FAILURE",
                "expected structured error but got success",
                case.note,
            )
        return Outcome(case.tool, case.expect, "OK", "success", case.note)

    # -- main flow ------------------------------------------------------------

    def run(self) -> int:
        headers = {
            "Authorization": f"Bearer {ACCESS_KEY}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "mcp-protocol-version": PROTOCOL_VERSION,
        }
        with httpx.Client(headers=headers) as client:
            self.call(
                client,
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "local-mcp-e2e", "version": "1.0"},
                },
            )
            listed = self.call(client, "tools/list", {})
            tools = listed.get("tools", [])
            if len(tools) != 56:
                self.outcomes.append(
                    Outcome(
                        "tools/list",
                        "success",
                        "FAILURE",
                        f"expected 56 tools, got {len(tools)}",
                    )
                )
            for tool in tools:
                name = str(tool["name"])
                schema = tool.get("outputSchema")
                if not isinstance(schema, dict):
                    self.outcomes.append(
                        Outcome(name, "either", "FAILURE", "missing outputSchema")
                    )
                    continue
                self.tools[name] = schema

            self._discover_document(client)
            cases = self._matrix()
            for case in cases:
                self.outcomes.append(self.run_case(client, case))

        return self._report()

    def _discover_document(self, client: httpx.Client) -> None:
        """Find one library paper to drive the real read/write paths.

        The library list mixes ``entry_type == "paper"`` entries (the
        paper's own record, carrying ``document.document_id``) with
        ``entry_type == "ingestion"`` entries (active uploads that may
        reference a document not yet in the Library). Prefer the paper
        record so the discovered document is guaranteed usable by the
        read/write paths.
        """
        try:
            result = self.call(
                client,
                "tools/call",
                {"name": "list_library_papers", "arguments": {"limit": 10}},
            )
        except E2EFailure:
            return
        structured = result.get("structuredContent") or {}
        result_payload = structured.get("result")
        items = (
            result_payload.get("items", []) if isinstance(result_payload, dict) else []
        )
        paper_document_id: str | None = None
        fallback_document_id: str | None = None
        for item in items:
            if not isinstance(item, dict):
                continue
            entry_type = item.get("entry_type")
            document = (
                item.get("document") if isinstance(item.get("document"), dict) else None
            )
            document_id = None
            if document is not None:
                document_id = document.get("document_id") or item.get("document_id")
            if document_id is None and isinstance(item.get("ingestion"), dict):
                document_id = item["ingestion"].get("document_id")
            if not document_id:
                continue
            if entry_type == "paper" and paper_document_id is None:
                paper_document_id = str(document_id)
            elif fallback_document_id is None:
                fallback_document_id = str(document_id)
        document_id = paper_document_id or fallback_document_id
        if document_id:
            self.document_id = document_id
            self.outcomes.append(
                Outcome(
                    "list_library_papers",
                    "success",
                    "OK",
                    f"discovered document {document_id}",
                )
            )

    def _matrix(self) -> list[Case]:
        fake = self._fake_uuid()
        project_key = f"e2e-create-project-{uuid.uuid4().hex[:8]}"
        cases: list[Case] = [
            # -- read-only baseline -------------------------------------------
            Case("list_projects", {}, "success"),
            Case("list_library_papers", {"limit": 10}, "success"),
            Case("list_library_tags", {}, "success"),
            Case("get_library_summary", {}, "success"),
            Case("list_jobs", {"active": True}, "success"),
            Case("list_jobs", {"operation": "pdf_process"}, "success"),
            Case(
                "search_scholens_knowledge",
                {"query": "attention", "scope": {"kind": "library"}},
                "success",
            ),
            Case(
                "list_research_outputs",
                {"scope": {"kind": "library"}, "kinds": ["citation"]},
                "success",
                "research output listing with kind filter",
            ),
            Case(
                "list_research_outputs",
                {"scope": {"kind": "library"}, "kinds": ["annotation_thread"]},
                "error",
                "annotation_thread kind is managed by annotation tools and must be rejected",
            ),
            Case("create_project", {"title": "E2E Project"}, "success"),
            Case(
                "create_project",
                {"title": "E2E Project", "idempotency_key": project_key},
                "success",
                "idempotent replay: same key returns the same project",
            ),
            Case("update_project", {"project_id": fake, "title": "Nope"}, "error"),
            Case("delete_project", {"project_id": fake}, "error"),
            Case("leave_project", {"project_id": fake}, "error"),
            Case("get_project", {"project_id": fake}, "error"),
            Case("list_project_papers", {"project_id": fake}, "error"),
            Case("list_project_members", {"project_id": fake}, "error"),
            Case("list_project_invitations", {"project_id": fake}, "error"),
            Case(
                "create_project_invitation",
                {
                    "project_id": fake,
                    "email": "nobody@example.com",
                    "edit_project": False,
                    "manage_papers": False,
                    "manage_collaborators": False,
                },
                "error",
            ),
            Case(
                "resend_project_invitation",
                {"project_id": fake, "invitation_id": fake},
                "error",
            ),
            Case(
                "revoke_project_invitation",
                {"project_id": fake, "invitation_id": fake},
                "error",
            ),
            Case(
                "remove_project_member",
                {"project_id": fake, "user_id": 1},
                "error",
            ),
            Case(
                "update_project_member",
                {
                    "project_id": fake,
                    "user_id": 1,
                    "edit_project": False,
                    "manage_papers": False,
                    "manage_collaborators": False,
                },
                "error",
            ),
            Case(
                "transfer_project_ownership",
                {"project_id": fake, "new_owner_id": 1},
                "error",
            ),
            Case(
                "accept_project_invitation",
                {"token": "not-a-real-token-0123456789"},
                "error",
            ),
            # -- paper metadata ------------------------------------------------
            Case("get_paper", {"document_id": fake}, "error"),
            Case("get_library_paper", {"document_id": fake}, "error"),
            Case("get_paper_download_url", {"document_id": fake}, "error"),
            Case("get_paper_citation", {"document_id": fake, "style": "APA"}, "error"),
            Case(
                "resolve_paper_citation", {"document_id": fake, "style": "APA"}, "error"
            ),
            Case(
                "update_library_paper",
                {"document_id": fake, "status": "reading"},
                "error",
            ),
            Case("remove_library_papers", {"document_ids": [fake]}, "error"),
            Case("update_library_tag", {"tag_id": fake, "name": "nope"}, "error"),
            Case("delete_library_tag", {"tag_id": fake}, "error"),
            Case(
                "create_library_tag",
                {"name": f"e2e-tag-{uuid.uuid4().hex[:8]}"},
                "success",
                "unique tag name keeps the matrix repeatable",
            ),
            Case("get_annotation_thread", {"thread_id": fake}, "error"),
            Case(
                "create_annotation_comment",
                {"thread_id": fake, "content": "hi"},
                "error",
            ),
            Case(
                "update_annotation_comment",
                {"comment_id": fake, "content": "hi"},
                "error",
            ),
            Case("delete_annotation_comment", {"comment_id": fake}, "error"),
            Case("delete_annotation_thread", {"thread_id": fake}, "error"),
            # -- research outputs / jobs ---------------------------------------
            Case("get_research_output", {"item_id": fake}, "error"),
            Case("get_job", {"job_id": fake}, "error"),
            Case("retry_paper_ingestion", {"job_id": fake}, "error"),
            Case("cancel_paper_ingestion", {"job_id": fake}, "error"),
            # -- ingestion validation paths ------------------------------------
            Case(
                "prepare_paper_upload",
                {"filename": "paper.pdf", "size_bytes": 1, "sha256": "not-hex"},
                "error",
            ),
            Case(
                "ingest_paper",
                {"source": {"kind": "url", "url": "not-a-url"}},
                "error",
            ),
            Case(
                "collect_shared_paper",
                {"share_token": "definitely-not-a-real-token"},
                "error",
            ),
            Case(
                "collect_project_paper_to_library",
                {"source_project_id": fake, "document_id": fake},
                "error",
            ),
        ]
        document_id = self.document_id
        if document_id is not None:
            cases.extend(
                [
                    Case("get_paper", {"document_id": document_id}, "success"),
                    Case("get_library_paper", {"document_id": document_id}, "success"),
                    Case(
                        "get_paper_content",
                        {"document_id": document_id, "start_line": 1, "max_lines": 50},
                        "success",
                    ),
                    Case(
                        "search_paper_content",
                        {"document_id": document_id, "query": "attention"},
                        "success",
                    ),
                    Case(
                        "get_paper_citation",
                        {"document_id": document_id, "style": "APA"},
                        "success",
                    ),
                    Case(
                        "list_annotation_threads",
                        {"document_id": document_id},
                        "success",
                    ),
                    Case(
                        "list_paper_projects", {"document_id": document_id}, "success"
                    ),
                    Case(
                        "update_library_paper",
                        {"document_id": document_id, "status": "reading"},
                        "success",
                    ),
                    Case(
                        "replace_library_paper_tags",
                        {"document_ids": [document_id], "tag_ids": []},
                        "success",
                    ),
                    Case(
                        "create_annotation_thread",
                        {
                            "document_id": document_id,
                            "quote_text": "Attention is all you need",
                            "position": {
                                "kind": "parsed_text",
                                "start_offset": 0,
                                "end_offset": 25,
                            },
                            "audience": {"kind": "personal"},
                            "color": "yellow",
                        },
                        "success",
                        "PR2: exact quote anchor",
                    ),
                    Case(
                        "create_annotation_thread",
                        {
                            "document_id": document_id,
                            "quote_text": "not present anywhere in this paper",
                            "position": {
                                "kind": "parsed_text",
                                "start_offset": 0,
                                "end_offset": 10,
                            },
                            "audience": {"kind": "personal"},
                        },
                        "error",
                        "PR2: quote mismatch must be rejected",
                    ),
                    Case(
                        "create_annotation_thread",
                        {
                            "document_id": document_id,
                            "quote_text": "Attention is all you need",
                            "position": {
                                "kind": "parsed_text",
                                "start_offset": 4,
                                "end_offset": 7,
                            },
                            "audience": {"kind": "personal"},
                        },
                        "error",
                        "PR2: offsets not covering quote must be rejected",
                    ),
                ]
            )
        return cases

    def _report(self) -> int:
        masked = [o for o in self.outcomes if o.result == "MASKED"]
        failed = [o for o in self.outcomes if o.result == "FAILURE"]
        errors = [o for o in self.outcomes if o.result == "ERROR"]
        ok = [o for o in self.outcomes if o.result == "OK"]
        print(f"tools advertised: {len(self.tools)}")
        print(
            f"cases: {len(self.outcomes)}  ok={len(ok)}  error={len(errors)}  "
            f"masked={len(masked)}  failure={len(failed)}"
        )
        for outcome in self.outcomes:
            marker = {
                "OK": "  ok ",
                "ERROR": " err ",
                "MASKED": "MASK ",
                "FAILURE": "FAIL ",
            }[outcome.result]
            print(f"{marker} {outcome.tool:<42} {outcome.detail}")
        if masked:
            print(
                "\nMASKED responses replicate the production -32602 failure; "
                "fix the tool."
            )
        if failed:
            print("\nFAILURE responses are transport or expectation violations.")
        return 1 if (masked or failed) else 0

    @staticmethod
    def _fake_uuid() -> str:
        return str(uuid.uuid4())


def main() -> int:
    driver = Driver()
    return driver.run()


if __name__ == "__main__":
    raise SystemExit(main())
