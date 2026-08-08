# Roadmap

The roadmap orders independently testable outcomes. Implemented behavior belongs in formal design
and release history.

## Later outcomes

- Extend the Rakuten importer to non-empty holdings only after an anonymized real export defines
  its columns, account semantics, and instrument identifiers.
- Refresh built-in constituent assets through a reviewed, reproducible process when official index
  membership changes.
- Improve Market Snapshot acquisition efficiency only when failure semantics, content identity, and the
  yfinance-only source boundary remain unchanged.
- Expose Market Snapshot and Security Research application services through MCP only after the
  current typed CLI schemas and local operational flow are stable. MCP remains a transport adapter;
  it does not own provider access, persistence, or analysis instructions.
- Add more deterministic policy comparison metrics only when they retain exact dataset, decision,
  and evidence provenance.
- Add scheduling only after one-shot commands and local recovery have proved reliable.

External interpretation, discussion, messaging, and model execution remain outside canonical
MarketSieve state. They may consume self-contained Snapshot and Research Pack objects.
