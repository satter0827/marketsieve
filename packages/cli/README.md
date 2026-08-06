# MarketSieve CLI

`marketsieve-cli` is the public command-line workbench for the MarketSieve SDK. It owns command
parsing, use-case orchestration, terminal and JSON projections, and operational diagnostics while
keeping market semantics in the independent `marketsieve` distribution.

The current commands are offline and require no credentials:

```shell
marketsieve doctor
marketsieve capabilities
marketsieve inspect XTKS:7203 --source-profile PROFILE
marketsieve ai prepare report latest
marketsieve ai import RESPONSE.json --controlled
marketsieve ai show latest
```

The manual AI commands exchange files with a human-operated ChatGPT Temporary Chat and make no
network request themselves. Existing optional `report explain` and `experiment explain` commands
continue to support explicitly configured local or cloud model providers.

See the repository documentation for current commands, plugin boundaries, and supported
installation combinations.
