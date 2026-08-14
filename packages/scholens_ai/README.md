# scholens-ai

`scholens-ai` is the provider-neutral AI configuration boundary shared by
Server and Jobs. It owns named workload profiles, validated environment
configuration, deterministic profile revisions, provider selection, and model
settings. It does not own prompts, product workflows, authorization, provider
credentials, or retry orchestration outside model construction.

## Public contract

Import the supported surface from `scholens_ai`:

- `AIProfile`, `AIProfileName`
- `AIThinkingMode`, `AIThinkingEffort`
- `ProviderConfigurationError`
- `resolve_profile`, `profile_model_settings`, `build_model`

Profile model identifiers always use `provider:model`. Server and Jobs are the
current consumers. New providers must be added as an explicit adapter rather
than silently treated as OpenAI-compatible.

The package is typed and ships `py.typed`. Its direct tests live in `tests/`
and run through the shared package workspace documented in
[`../README.md`](../README.md).
