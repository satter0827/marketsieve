# Roadmap

The roadmap orders independently testable outcomes. Implemented behavior belongs in formal design
and release history.

## Later outcomes

- Refresh built-in constituent assets through a reviewed, reproducible process when official index
  membership changes.
- Improve Market Snapshot acquisition efficiency only when failure semantics, content identity, and the
  yfinance-only source boundary remain unchanged.
- Expose the existing typed build, capture, query, compare, diff, research, and serve application
  requests through MCP only after more than one client needs the boundary. MCP remains a transport
  adapter; it does not own provider access, persistence, or analysis instructions.
- Invoke the one-shot JP and US close Capture commands from an external scheduler only after local
  recovery history is sufficient. Scheduling, notification, cron, and daemons remain out of scope.

External interpretation, discussion, messaging, and model execution remain outside canonical
MarketSieve state. They may consume self-contained Snapshot and Research Pack objects.
