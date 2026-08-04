# Repository constraints for coding agents

Read `docs/README.md`, `docs/design/architecture.md`, and the affected formal design before changing
package boundaries, public APIs, delivery behavior, or release procedures.

Keep the public SDK independent from `marketsieve_cli`, configuration sources, logging setup,
network clients, databases, delivery providers, and LLM providers. Do not add a public port until a
working implementation and tests define its actual inputs and outputs.

Use the repository Makefile so local, editor, and CI commands stay aligned. Run focused checks while
developing and the complete gate before handoff:

```shell
make format-check
make lint
make typecheck
make test
make check
```

Follow `CONTRIBUTING.md` for branch, review, and release procedures. Do not commit secrets, personal
recipient data, live portfolio data, generated reports, or local caches.

Prefer the GitHub connector for repository, pull request, and issue data. In managed Codex
environments, run commands that require GitHub network access or the macOS Keychain, such as
`gh auth status`, Actions log inspection, and `git fetch`, with narrowly scoped host access. Treat a
sandbox-only `invalid token` result as an access limitation until host-side verification also fails.
Keep HTTPS credentials in the macOS Keychain; never copy a token into environment variables,
repository files, or command output. Perform GitHub write operations only when the user explicitly
requests them.

Keep current and approved system design in `docs/design`, planned outcomes in `docs/roadmap.md`, and
temporary non-normative investigation in dated `docs/notes` files. Do not make notes a prerequisite
for understanding the system contract.

Keep local caches, coverage, logs, and generated evidence under `.marketsieve`. The executable
dependency rules live in `pyproject.toml`; document ownership and composition rules that cannot be
tested in `docs/design/architecture.md`.
