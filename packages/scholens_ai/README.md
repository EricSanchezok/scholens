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

OpenAI Platform is not a supported provider and `openai:*` identifiers are
rejected. The `openai` Python SDK remains a runtime dependency because the
DeepSeek adapter deliberately uses its OpenAI-compatible client against the
fixed default `https://api.deepseek.com` endpoint; this does not require or
consume an OpenAI API key.

The package is typed and ships `py.typed`. Its direct tests live in `tests/`
and run through the shared package workspace documented in
[`../README.md`](../README.md).
