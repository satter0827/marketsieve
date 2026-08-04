# Repository constraints for coding agents

Read `docs/README.md`, `docs/design/architecture.md`, and the affected formal design before changing
package boundaries, public APIs, delivery behavior, or release procedures.

Keep the public SDK independent from `marketsieve_app`, configuration sources, logging setup,
network clients, databases, delivery providers, and LLM providers. Do not add a public port until a
working implementation and tests define its actual inputs and outputs.

Run focused checks while developing and the complete gate before handoff:

```shell
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv run python scripts/quality_gate.py check all
```

Follow `CONTRIBUTING.md` for branch, review, and release procedures. Do not commit secrets, personal
recipient data, live portfolio data, generated reports, or local caches.

Keep current and approved system design in `docs/design`, planned outcomes in `docs/roadmap.md`, and
temporary non-normative investigation in dated `docs/notes` files. Do not make notes a prerequisite
for understanding the system contract.
