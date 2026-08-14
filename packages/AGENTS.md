# Shared package development rules

These rules apply to everything under `packages/` in addition to the root
[`AGENTS.md`](../AGENTS.md).

- Every distributable package uses `src/<import_name>/`, includes `py.typed`,
  documents its public contract and current consumers, and has direct tests.
- Shared package runtime code must not import from `server/`, `jobs/`, `app`,
  or the Jobs `src` package. Applications compose packages, never the reverse.
- Keep public exports explicit in `__init__.py`. A consumer must not depend on
  another package's private module as an accidental API.
- Package code is service-neutral. Authorization, database transactions,
  HTTP/Celery transport, and product workflow policy remain with their owner.
- Add a third package only when it satisfies the admission checklist in
  [`README.md`](./README.md); do not create speculative shared abstractions.
- When package metadata or dependencies change, regenerate `packages/uv.lock`
  and every affected consumer lockfile, then run the workspace contract.
- Daily checks use `--frozen --no-sync`; they never install dependencies,
  start services, or apply migrations as a side effect.
