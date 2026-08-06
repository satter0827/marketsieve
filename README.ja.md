# MarketSieve

MarketSieveは、日本株・米国株を対象とする決定論的な分析ワークベンチです。市場データを明示的に取得し、変更不能な根拠、静的な判断レポート、候補抽出結果、履歴比較可能な分析ワークスペースを生成します。

MarketSieve自身はAIモデルを実行せず、通知を送信せず、注文を生成しません。ニュース調査と人間との議論は、通常アプリとして利用するCodexなどの外部ツールが担当します。

## 日常利用

VS Codeの「実行とデバッグ」に番号順の入口があります。初回は`01`から`03`を実行します。ポートフォリオとwatchlistが空でも正常です。`10`または`20`で限定候補探索を行うか、既知の銘柄を`30`で登録します。

| 操作 | ターミナル | VS Code | 通信 | 生成物 |
| --- | --- | --- | --- | --- |
| 設定作成 | `make setup-config` | `01 First Run: Create Configuration` | なし | `marketsieve.toml` |
| 楽天CSV取込 | `make portfolio-import BROKER=rakuten PORTFOLIO=/absolute/path.csv` | `02 First Run: Import Rakuten Portfolio` | なし | 保有状態 |
| 準備確認 | `make daily-status` | `03 Daily Use: Check Readiness` | なし | 次操作の診断 |
| 日本株候補探索 | `make screen-refresh-jp` | `10 Discovery: Refresh JP Candidates (Network)` | あり | screening report |
| 米国株候補探索 | `make screen-refresh-us` | `20 Discovery: Refresh US Candidates (Network)` | あり | screening report |
| watchlist追加 | `make watchlist-add INSTRUMENT=XTKS:7203` | `30 Watchlist: Add Instrument` | なし | watchlist履歴 |
| 日本株日次分析 | `make daily-jp` | `40 Daily Use: Analyze JP Watchlist (Network)` | あり | 静的レポート |
| 米国株日次分析 | `make daily-us` | `50 Daily Use: Analyze US Watchlist (Network)` | あり | 静的レポート |
| 週次まとめ | `make weekly` | `60 Weekly Use: Build Brief` | なし | 静的レポート |
| 分析ワークスペース生成 | `make analysis-build` | `70 Analysis: Build Workspace` | なし | `context.json`、`analysis.md` |

分析開始時は`.marketsieve/analysis/context.json`と`.marketsieve/analysis/analysis.md`をCodexへ読ませます。数量、取得価格、口座種別、CSVパス、個人情報、認証情報は含まれません。ニュースや対話内容はMarketSieveの正本へ保存しません。

開発と品質確認は`make format-check`、`make lint`、`make typecheck`、`make test`、`make check`を使用します。詳しい契約は[正式設計](docs/design/README.md)を参照してください。
