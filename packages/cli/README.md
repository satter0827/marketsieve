# MarketSieve CLI

`marketsieve-cli` is the public command-line workbench for the MarketSieve SDK. It owns command
parsing, use-case orchestration, terminal and JSON projections, and operational diagnostics while
keeping market semantics in the independent `marketsieve` distribution.

The current commands are offline and require no credentials:

```shell
marketsieve doctor
marketsieve capabilities
marketsieve inspect XTKS:7203 --source-profile PROFILE
```

See the repository documentation for current commands, plugin boundaries, and supported
installation combinations.
