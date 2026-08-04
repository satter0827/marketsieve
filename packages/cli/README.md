# MarketSieve CLI

`marketsieve-cli` is the public command-line workbench for the MarketSieve SDK. It owns command
parsing, use-case orchestration, terminal and JSON projections, and operational diagnostics while
keeping market semantics in the independent `marketsieve` distribution.

The current commands are offline and require no credentials:

```shell
marketsieve doctor
marketsieve capabilities
marketsieve report
```

See the repository documentation for the 0.2 data-workbench roadmap and supported installation
procedure.
