# MarketSieve

MarketSieveは、日本株・米国株を再現可能な形で分析するワークベンチです。日経225、TOPIX 500、
S&P 500、Dow 30、Nasdaq-100を横断し、1銘柄を1行、同一の指標を列に持つ全銘柄マトリックスを
中心に据えます。

マトリックスの実行時データソースはyfinanceだけです。登録、APIキー、環境変数は不要です。
取得できない値を別ソースや推定値で補わず、欠損セルごとに固定の理由コードを残します。
スコア、ランキング、売買推奨、注文、通知、Excelファイルは生成しません。

## 全銘柄マトリックス

```shell
make sync
make market-matrix
uv run marketsieve matrix show latest
uv run marketsieve matrix row XTKS:7203
uv run marketsieve matrix compare XTKS:7203 XNAS:MSFT --fields return_252d --fields volatility_252d
make analysis-build
```

`make market-matrix`は3年分の調整済み日足をバッチ取得し、企業・財務情報を制限付き並列で
取得します。組込の指数資産は構成銘柄と出典を固定する定義であり、実行時の代替データソース
ではありません。

成果物は`.marketsieve/matrices/objects/MATRIX_ID/`へ不変保存します。

- `securities.jsonl`：1銘柄1行の正本
- `fields.json`：全フィールドの式、単位、期間、出典、定義版
- `manifest.json`、`index-summary.json`、`failures.jsonl`：由来、品質、欠損理由
- `matrix.csv`、`overview.html`：JSONLから作る閲覧用投影。HTMLは外部CDNを使いません
- `analysis.md`：市場幅、分布、リスク、流動性、財務、集中度、セクター、欠損傾向の分析

`matrix row`と`matrix compare`は保存済みJSONLだけを読み、通信や再計算を行いません。
`analysis build`は全行を複製せず、選択したマトリックスを参照する`analysis-context/v2`を生成します。

## その他の運用

| 操作 | ターミナル | VS Code | 通信 | 生成物 |
| --- | --- | --- | --- | --- |
| 設定作成 | `make setup-config` | `01 First Run: Create Configuration` | なし | `marketsieve.toml` |
| 楽天CSV取込 | `make portfolio-import BROKER=rakuten PORTFOLIO=/absolute/path.csv` | `02 First Run: Import Rakuten Portfolio` | なし | 保有状態 |
| 準備確認 | `make daily-status` | `03 Daily Use: Check Readiness` | なし | 次操作の診断 |
| 全銘柄更新 | `make market-matrix` | `10 Market Matrix: Refresh All Indices (Network)` | あり | マトリックスと分析 |
| watchlist追加 | `make watchlist-add INSTRUMENT=XTKS:7203` | `30 Watchlist: Add Instrument` | なし | watchlist履歴 |
| 日本株日次分析 | `make daily-jp` | `40 Daily Use: Analyze JP Watchlist (Network)` | あり | 静的レポート |
| 米国株日次分析 | `make daily-us` | `50 Daily Use: Analyze US Watchlist (Network)` | あり | 静的レポート |
| 週次まとめ | `make weekly` | `60 Weekly Use: Build Brief` | なし | 静的レポート |
| AI分析文脈生成 | `make analysis-build` | `70 Analysis: Build Workspace` | なし | `context.json`、`analysis.md` |

yfinanceの説明上、利用は調査・教育・個人利用が前提です。成果物は個人のローカル分析に限定します。
応答が部分的またはレート制限となった場合も、別ソースへ切り替えずその状態を記録します。

品質確認には`make format-check`、`make lint`、`make typecheck`、`make test`、`make check`を
使用します。詳しい契約は[正式設計](docs/design/README.md)を参照してください。
