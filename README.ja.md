# MarketSieve

MarketSieveは、APIキー不要のyfinanceから、日本株・米国株の再現可能な分析材料を生成します。
市場全体を捉えるMarket Snapshotと、必要な銘柄だけを深掘りするSecurity Researchを分離し、
解釈は人間または外部AIへ委ねます。

```shell
make sync
make doctor
make market-capture MARKET=jp
make market-capture MARKET=us
make market-preview
make market-query QUERY_ARGS='--market jp --profile swing --domain return --domain risk --order return_20d:desc --limit 30'
make research-build INSTRUMENTS='XTKS:7203 XNAS:MSFT'
```

分析対象、証拠領域、履歴期間は実行ごとにCLIへ入力します。任意の
`marketsieve.settings.toml`には、取得並列数、再試行、品質閾値などの運用設定だけを置きます。
既定値を変える場合は`make setup-settings`で作成できます。

Snapshotは`.marketsieve/market-snapshots/objects/SNAPSHOT_ID/`へ保存されます。JSON・JSONLを
正本とし、`explorer-data.json`を正本ファイル参照付きの決定的な画面契約、`summary.md`と
`explorer.html`を人間向け投影とします。Explorerは単一ファイルではなく成果物フォルダ
全体で自己完結し、`market serve`または`research serve`で閲覧します。個別調査は
`.marketsieve/research/objects/RESEARCH_ID/`へ保存し、元Snapshotとの対応を保持します。
Research Explorerは`research serve`経由で正本ファイルを直接読み、3か月から全期間までを
再取得なしで切り替えます。価格、会社、財務、決算、配当、分割、ベンチマークの取得状態は
独立しており、一部取得失敗が取得済み証拠を隠しません。
ExcelとCSVは生成しません。

公開CLIは`market`、`research`、`doctor`、`capabilities`だけです。Portfolio、Watchlist、定期
レポート、汎用Source／Snapshot、Experimentは提供しません。

詳細は[設計索引](docs/design/README.md)と[開発手順](CONTRIBUTING.md)を参照してください。
