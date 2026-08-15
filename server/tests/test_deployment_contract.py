"""Static contracts for the production deployment package."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
PRODUCTION = ROOT / "deploy" / "production"


def load_compose() -> dict[str, object]:
    return yaml.safe_load((PRODUCTION / "compose.yaml").read_text(encoding="utf-8"))


def test_only_public_application_edges_join_shared_network() -> None:
    compose = load_compose()
    services = compose["services"]

    assert services["client"]["networks"] == {"edge": {"aliases": ["scholens-client"]}}
    assert services["api"]["networks"]["edge"] == {"aliases": ["scholens-api"]}
    for service in ("jobs-api", "worker", "beat", "rabbitmq", "redis", "migrate"):
        assert "edge" not in services[service]["networks"]
    assert compose["networks"]["internal"]["internal"] is True
    assert compose["networks"]["edge"]["external"] is True
    assert all("ports" not in service for service in services.values())


def test_release_images_are_required_and_runtime_containers_are_non_root() -> None:
    compose_text = (PRODUCTION / "compose.yaml").read_text(encoding="utf-8")
    compose = load_compose()
    for variable in (
        "SCHOLENS_API_IMAGE",
        "SCHOLENS_CLIENT_IMAGE",
        "SCHOLENS_JOBS_IMAGE",
    ):
        assert f"${{{variable}:?" in compose_text

    for dockerfile in ("server/Dockerfile", "client/Dockerfile", "jobs/Dockerfile"):
        content = (ROOT / dockerfile).read_text(encoding="utf-8")
        assert re.search(r"^USER (?!root$).+", content, re.MULTILINE)

    assert "HEALTHCHECK" in (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    assert "HEALTHCHECK" in (ROOT / "client" / "Dockerfile").read_text(encoding="utf-8")
    assert "healthcheck:" in compose_text
    for service in ("rabbitmq", "redis"):
        assert re.fullmatch(
            r"[^\s]+@sha256:[0-9a-f]{64}", compose["services"][service]["image"]
        )


def test_production_uses_the_unified_migration_cli_and_gunicorn_runtime() -> None:
    compose = load_compose()
    dockerfile = (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")

    assert compose["services"]["migrate"]["command"] == [
        "scholens",
        "db",
        "upgrade",
        "--yes",
    ]
    assert 'CMD ["gunicorn", "-c", "gunicorn.config.py", "app.main:app"]' in dockerfile


def test_python_images_copy_shared_packages_before_locked_sync() -> None:
    for dockerfile_path in (
        ROOT / "server" / "Dockerfile",
        ROOT / "jobs" / "Dockerfile",
    ):
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        sync_index = dockerfile.index("RUN uv sync --frozen")
        for shared_package in ("scholens_observability", "scholens_ai"):
            copy_instruction = (
                f"COPY packages/{shared_package}/ /packages/{shared_package}/"
            )
            assert dockerfile.index(copy_instruction) < sync_index


def test_reflow_block_migration_includes_inherited_timestamps() -> None:
    migration = (
        ROOT
        / "server"
        / "migrations"
        / "versions"
        / "2026_07_28_1030_scholens_initial.py"
    ).read_text(encoding="utf-8")
    reflow_blocks = migration.split(
        'op.create_table(\n        "document_reflow_blocks",', 1
    )[1].split("op.create_index(", 1)[0]

    assert '"created_at"' in reflow_blocks
    assert '"updated_at"' in reflow_blocks


def test_entitlement_downgrade_keeps_append_only_cli_origin_vocabulary() -> None:
    migration = (
        ROOT
        / "server"
        / "migrations"
        / "versions"
        / "2026_08_16_1200_entitlement_grants_and_cli_origin.py"
    ).read_text(encoding="utf-8")
    downgrade = migration.split("def downgrade() -> None:", 1)[1]

    assert "one-way vocabulary extension" in downgrade
    assert "ck_operation_journal_origin" not in downgrade


def test_runtime_passage_backfill_never_requires_trigger_ddl() -> None:
    adapter = (
        ROOT
        / "server"
        / "app"
        / "modules"
        / "papers"
        / "infrastructure"
        / "passage_maintenance.py"
    ).read_text(encoding="utf-8")

    assert "ALTER TABLE" not in adapter
    assert "DISABLE TRIGGER" not in adapter
    assert "sanitize_for_postgres" in adapter
    assert "LIMIT :limit" in adapter


def test_database_contract_shares_auth_and_isolates_scholens() -> None:
    runtime = (PRODUCTION / "runtime.env.example").read_text(encoding="utf-8")
    bootstrap = (PRODUCTION / "bootstrap-db.sql").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert runtime.count("/sanchezcloud?") == 2
    assert "search_path" not in runtime
    assert "CREATE SCHEMA IF NOT EXISTS auth" in bootstrap
    assert "CREATE SCHEMA IF NOT EXISTS scholens" in bootstrap
    assert "GRANT CREATE ON DATABASE" not in bootstrap
    assert "auth_migrator_role" in bootstrap
    assert "product_migrator_role" in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE auth.users" in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE auth.users" not in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE auth.user_clients" in bootstrap
    assert "GRANT SELECT, INSERT ON TABLE auth.security_events" in bootstrap
    assert "security_events_id_seq" in bootstrap
    assert 'FOR ROLE :"auth_migrator_role"' not in bootstrap
    assert (
        'REVOKE CREATE ON SCHEMA auth FROM :"app_role", :"product_migrator_role"'
        in bootstrap
    )
    assert (
        "REVOKE UPDATE, DELETE ON TABLE scholens.operation_journal_entries" in bootstrap
    )
    assert ci.count("'scholens.operation_journal_entries'") >= 3
    assert "'UPDATE'" in ci
    assert "'DELETE'" in ci
    assert "ALTER DEFAULT PRIVILEGES" in bootstrap
    for current_table in (
        "scholens.documents",
        "scholens.library_papers",
        "scholens.projects",
        "scholens.project_collaborators",
        "scholens.project_papers",
    ):
        assert current_table in ci
    for removed_table in (
        "scholens.papers",
        "scholens.project",
        "scholens.project_role",
        "scholens.project_paper",
    ):
        assert not re.search(rf"{re.escape(removed_table)}(?![a-z_])", ci)


def test_identity_revision_is_consistent_across_runtime_and_ci() -> None:
    lock = (ROOT / "server" / "uv.lock").read_text(encoding="utf-8")
    dockerfile = (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    match = re.search(
        r"sanchezcloud-identity\.git\?(?:rev|tag)=[^#\"\s]+#([0-9a-f]{40})", lock
    )
    assert match is not None
    revision = match.group(1)
    assert f"ARG SANCHEZCLOUD_IDENTITY_REVISION={revision}" in dockerfile
    assert "server/.venv/bin/sanchezcloud-identity migrate" in ci
    assert ".ci/sanchezcloud-identity" not in ci
    assert f"ref: {revision}" not in ci


def test_workflows_use_the_scoped_dependency_reader_app() -> None:
    workflows = "\n".join(
        (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for name in ("ci.yml", "release.yml")
    )

    assert "actions/create-github-app-token@" in workflows
    assert "vars.IDENTITY_READER_APP_ID" in workflows
    assert "secrets.IDENTITY_READER_PRIVATE_KEY" in workflows
    assert "permission-contents: read" in workflows
    assert "CLOUD_AUTH_READ_TOKEN" not in workflows
    assert "origin/master" not in workflows
    assert "default: master" not in workflows


def test_candidate_identity_compatibility_workflow_is_standardized() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "sanchezcloud-identity-compat.yml"
    ).read_text(encoding="utf-8")

    for input_name in (
        "identity_ref",
        "version",
        "schema_version",
        "correlation_id",
    ):
        assert f"{input_name}:" in workflow
    assert "actions/create-github-app-token@" in workflow
    assert "permission-contents: read" in workflow
    assert "secrets.IDENTITY_READER_PRIVATE_KEY" in workflow
    assert "uv pip install" in workflow
    assert "AUTH_SCHEMA_VERSION" in workflow
    assert "sanchezcloud-identity migrate" in workflow
    assert "audit-database-role --profile product-runtime" in workflow
    assert "app_role=scholens_app" in workflow
    assert "SANCHEZCLOUD_IDENTITY_REVISION" in workflow
    assert "CLOUD_AUTH_READ_TOKEN" not in workflow


def test_environment_catalog_matches_shared_identity_conventions() -> None:
    catalog = (ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (PRODUCTION / "compose.yaml").read_text(encoding="utf-8")
    runtime = (PRODUCTION / "runtime.env.example").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for variable in (
        "DATABASE_URL",
        "AUTH_DATABASE_URL",
        "AUTH_JWT_SECRET",
        "AUTH_ACCOUNT_LOCKOUT_THRESHOLD",
        "AUTH_ACCOUNT_LOCKOUT_DURATION_MINUTES",
        "AUTH_ALIYUN_DM_ACCESS_KEY_ID",
        "AUTH_ALIYUN_DM_ACCESS_KEY_SECRET",
        "AUTH_ALIYUN_DM_ACCOUNT_NAME",
        "AUTH_ALIYUN_DM_FROM_ALIAS",
        "AUTH_ALIYUN_DM_REPLY_TO_ADDRESS",
        "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY",
        "SCHOLIGHT_MCP_URL",
        "SCHOLIGHT_MCP_DELEGATION_JWT_SECRET",
        "SCHOLENS_AI_DEEPSEEK_API_KEY",
        "SCHOLENS_AI_OPENAI_API_KEY",
        "SCHOLENS_AI_STANDARD_MODEL",
        "SCHOLENS_AI_TRANSLATION_MODEL",
        "MOSS_API_KEY",
        "MOSS_MAX_AUDIO_BYTES",
        "JOBS_WEBHOOK_SIGNING_SECRET",
        "PAPER_SEARCH_CURSOR_SECRET",
        "NEXT_PUBLIC_API_URL",
    ):
        assert f"{variable}=" in catalog

    assert not (ROOT / "server" / ".env.example").exists()
    assert "SCHOLENS_AUTH_ACCOUNT_LOCKOUT_THRESHOLD=" in runtime
    assert "SCHOLENS_ALIYUN_DM_REPLY_TO_ADDRESS=" in runtime
    assert "AUTH_ACCOUNT_LOCKOUT_THRESHOLD:" in compose
    assert "AUTH_ALIYUN_DM_REPLY_TO_ADDRESS:" in compose
    assert "SCHOLENS_INTEGRATION_CREDENTIAL_ENCRYPTION_KEY=" in runtime
    assert "SCHOLENS_SCHOLIGHT_MCP_DELEGATION_JWT_SECRET=" in runtime
    assert "SCHOLENS_AI_DEEPSEEK_API_KEY=" in runtime
    assert "SCHOLENS_MINERU_API_TOKEN=" not in runtime
    assert "SCHOLENS_MOSS_API_KEY=" in runtime
    assert "SCHOLENS_MOSS_MAX_AUDIO_BYTES=" in runtime
    assert "SCHOLENS_JOBS_WEBHOOK_SIGNING_SECRET=" in runtime
    assert "SCHOLENS_PAPER_SEARCH_CURSOR_SECRET=" in runtime
    assert "NEXT_PUBLIC_ACCOUNT_CENTER_URL=" not in runtime
    assert "NEXT_PUBLIC_ACCOUNT_CENTER_URL:" not in compose
    assert "INTEGRATION_CREDENTIAL_ENCRYPTION_KEY:" in compose
    assert "SCHOLIGHT_MCP_URL:" in compose
    assert "MOSS_MAX_AUDIO_BYTES:" in compose
    assert "SCHOLENS_AI_STRUCTURED_RETRIES:" in compose
    assert "PAPER_SEARCH_CURSOR_SECRET:" in compose
    for legacy_variable in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "SCHOLENS_DEEPSEEK_API_KEY",
        "SCHOLIGHT_ACCESS_KEY",
        "JOBS_INTERNAL_SECRET",
    ):
        assert (
            re.search(
                rf"(?m)^\s*{re.escape(legacy_variable)}\s*[=:]",
                catalog + runtime + compose + ci,
            )
            is None
        )
    assert "EXA_API_KEY" not in catalog + runtime + compose
    assert "FIRECRAWL_API_KEY" not in catalog + runtime + compose


def test_account_center_url_is_a_web_build_value_not_runtime_configuration() -> None:
    readme = (PRODUCTION / "README.md").read_text(encoding="utf-8")
    runtime = (PRODUCTION / "runtime.env.example").read_text(encoding="utf-8")
    compose = (PRODUCTION / "compose.yaml").read_text(encoding="utf-8")

    assert "NEXT_PUBLIC_ACCOUNT_CENTER_URL" in readme
    assert "build-time public value" in readme
    assert re.search(r"future\s+canonical Web cutover", readme)
    assert "NEXT_PUBLIC_ACCOUNT_CENTER_URL" not in runtime
    assert "NEXT_PUBLIC_ACCOUNT_CENTER_URL" not in compose


def test_local_development_uses_the_scholens_migrator_name() -> None:
    development = (ROOT / "DEVELOPMENT.md").read_text(encoding="utf-8")

    assert "scholens_migrator" in development
    assert "openpaper_local" not in development


def test_environment_catalog_covers_code_and_compose_references() -> None:
    assignment = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)
    catalog_variables = set(
        assignment.findall((ROOT / ".env.example").read_text(encoding="utf-8"))
    )
    runtime_variables = set(
        assignment.findall(
            (PRODUCTION / "runtime.env.example").read_text(encoding="utf-8")
        )
    )

    code_patterns = (
        re.compile(r'(?:os\.getenv|os\.environ\.get)\(\s*["\']([A-Z][A-Z0-9_]*)'),
        re.compile(r'os\.environ\[\s*["\']([A-Z][A-Z0-9_]*)'),
        re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)"),
    )
    code_variables: set[str] = set()
    for source_root in (
        ROOT / "server" / "app",
        ROOT / "jobs" / "src",
        ROOT / "client" / "src",
    ):
        for path in source_root.rglob("*"):
            if path.suffix not in {".py", ".js", ".mjs", ".ts", ".tsx"}:
                continue
            source = path.read_text(encoding="utf-8")
            for pattern in code_patterns:
                code_variables.update(pattern.findall(source))

    assert code_variables - {"NODE_ENV"} <= catalog_variables

    compose = (PRODUCTION / "compose.yaml").read_text(encoding="utf-8")
    compose_variables = set(re.findall(r"\$\{(SCHOLENS_[A-Z0-9_]+)", compose))
    generated_release_variables = {
        "SCHOLENS_API_IMAGE",
        "SCHOLENS_CLIENT_IMAGE",
        "SCHOLENS_JOBS_IMAGE",
    }
    assert compose_variables - generated_release_variables <= runtime_variables


def test_migration_chain_starts_with_the_consolidated_baseline() -> None:
    versions = sorted((ROOT / "server" / "migrations" / "versions").glob("*.py"))

    assert [path.name for path in versions] == [
        "2026_07_28_1030_scholens_initial.py",
        "2026_08_16_1200_entitlement_grants_and_cli_origin.py",
    ]
    baseline = versions[0].read_text(encoding="utf-8")
    assert "down_revision: str | None = None" in baseline
    assert "scholens.document_content_trigger" in baseline
    assert "scholens.document_passages_tsvector_trigger" in baseline
    assert "ON scholens.documents" in baseline
    assert "ON scholens.document_passages" in baseline
    assert "conversation_context_projects" in baseline
    assert "conversation_context_documents" in baseline
    assert '"tool_invocations"' in baseline
    assert '"access_keys"' in baseline
    for field in ("title", "authors", "keywords", "abstract", "raw_content"):
        assert f"NEW.{field}" in baseline
    assert "paper_passages" not in baseline
    assert "discover_searches" not in baseline
    assert '"integration_connections"' in baseline
    assert "'mineru'" in baseline


def test_global_discovery_surfaces_are_absent_from_client_sources() -> None:
    protected_routes = ROOT / "client" / "src" / "app" / "(main)" / "(protected)"
    assert not (protected_routes / "discover").exists()
    assert not (protected_routes / "finder").exists()

    product_surfaces = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "README.md",
            ROOT / "client" / "design.md",
            ROOT / "client" / "src" / "app" / "sitemap.ts",
            ROOT / "client" / "src" / "components" / "QuickActions.tsx",
            ROOT / "client" / "src" / "components" / "sidebar" / "navItems.ts",
            ROOT / "client" / "src" / "content" / "introducing.mdx",
            ROOT / "client" / "src" / "content" / "systematic_review.mdx",
            ROOT / "server" / "app" / "helpers" / "templates" / "project_invite.html",
        )
    )
    for removed_identifier in (
        "/discover",
        "/finder",
        "Discover Research",
        "Document Finder",
    ):
        assert removed_identifier not in product_surfaces


def test_server_keeps_the_typed_sqlalchemy_two_mainline() -> None:
    app_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "server" / "app").rglob("*.py")
    )
    model_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "server" / "app" / "database" / "models").glob("*.py")
    )
    pyproject = (ROOT / "server" / "pyproject.toml").read_text(encoding="utf-8")

    assert "db.query(" not in app_sources
    assert "type: ignore" not in app_sources
    assert re.search(r"\bColumn\(", model_sources) is None
    assert "sqlalchemy.ext.mypy.plugin" not in pyproject


def test_pdf_viewer_has_one_browser_only_loading_boundary() -> None:
    wrapper = (
        ROOT / "client" / "src" / "components" / "PdfHighlighterViewer.tsx"
    ).read_text(encoding="utf-8")
    implementation = (
        ROOT / "client" / "src" / "components" / "PdfHighlighterViewerClient.tsx"
    ).read_text(encoding="utf-8")
    package = (ROOT / "client" / "package.json").read_text(encoding="utf-8")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert 'import("./PdfHighlighterViewerClient")' in wrapper
    assert "ssr: false" in wrapper
    assert "react-pdf-highlighter-extended" not in wrapper
    assert "react-pdf-highlighter-extended" in implementation
    assert '"predev": "node scripts/sync-pdf-worker.mjs"' in package
    assert "sync-pdf-worker.mjs && node scripts/generate-blog-metadata.mjs" in package
    assert "client/public/pdf.worker.mjs" in ignore


def test_caddy_contract_hides_internal_health_and_routes_same_origin_api() -> None:
    caddy = (PRODUCTION / "Caddyfile.snippet").read_text(encoding="utf-8")

    assert "{$SCHOLENS_DOMAIN}" in caddy
    assert "respond @internal_health 404" in caddy
    assert "handle /api/v1/*" in caddy
    assert "handle /webhooks/v1/*" in caddy
    assert "/internal/v1" not in caddy
    assert "reverse_proxy scholens-api:8000" in caddy
    assert "reverse_proxy scholens-client:3000" in caddy


def test_ci_builds_images_and_runs_independent_migrations_twice() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    gate_runner = (ROOT / "scripts" / "run-gates.sh").read_text(encoding="utf-8")

    assert "tags: scholens-api:ci" in workflow
    assert "for _ in 1 2; do" in workflow
    assert "sanchezcloud-identity migrate" in workflow
    assert "scholens db upgrade --yes" in workflow
    assert "scholens dev reset-product" in workflow
    assert "RESET-SCHOLENS-LOCAL" in workflow
    assert "account_plan_grants" in workflow
    assert "account_quota_overrides" in workflow
    assert "alembic downgrade b12d7d620e91" in workflow
    assert "WHERE origin_kind = 'cli'" in workflow
    assert "test_postgres_quota_invariants.py" in workflow
    assert "scholens-api:ci alembic check" in workflow
    assert "CREATE TABLE auth.product_migrator_must_not_create" in workflow
    assert "CREATE TABLE scholens.auth_migrator_must_not_create" in workflow

    server_dockerfile = (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY --from=builder /app/migrations/ /app/migrations/" in server_dockerfile
    assert "SCHOLENS_SERVER_ROOT=/app" in server_dockerfile

    for lane in (
        "server",
        "jobs",
        "shared-packages",
        "web",
        "client",
        "deployment",
    ):
        assert f"./scripts/run-gates.sh {lane}" in workflow

    assert '"$environment/mypy" app' in gate_runner
    assert '"$environment/mypy" src' in gate_runner
    assert '"$environment/ruff" format --check app tests migrations' in gate_runner
    assert '"$environment/ruff" format --check src tests' in gate_runner
    assert "window is not defined|document is not defined" in gate_runner


def test_ci_has_one_stable_aggregate_required_check() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "all-checks-passed:" in workflow
    assert "name: all checks passed" in workflow
    for dependency in (
        "server",
        "jobs",
        "shared-packages",
        "web",
        "client",
        "deployment-contract",
    ):
        assert f"      - {dependency}" in workflow


def test_root_gate_runner_has_no_provisioning_or_runtime_side_effects() -> None:
    gate_runner = (ROOT / "scripts" / "run-gates.sh").read_text(encoding="utf-8")

    for forbidden_command in (
        "uv sync",
        "pnpm install",
        "yarn install",
        "alembic upgrade",
        "migrate_product",
        "docker compose up",
        "pnpm dev",
    ):
        assert forbidden_command not in gate_runner


def test_external_actions_are_pinned_to_full_commit_shas() -> None:
    action_reference = re.compile(r"^\s*uses:\s*([^\s]+)@([^\s#]+)", re.MULTILINE)
    for name in ("ci.yml", "release.yml"):
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for action, revision in action_reference.findall(workflow):
            if action.startswith("./"):
                continue
            assert re.fullmatch(r"[0-9a-f]{40}", revision), (
                f"{action}@{revision} is mutable"
            )
