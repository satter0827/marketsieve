# MarketSieve

MarketSieveは、日本株・米国株を再現可能な形で分析するワークベンチです。Market Snapshotは、
日経225、TOPIX 500、S&P 500、Dow 30、Nasdaq-100を横断した市場全体の断面を不変保存します。
必要な銘柄だけ、Security Research Packで詳しい根拠を追加取得できます。

市場と個別調査の実行時データソースはyfinanceだけです。登録、APIキー、環境変数は不要です。
取得できない値を別ソースや推定値で補わず、欠損セルごとに固定の理由コードを残します。
スコア、ランキング、売買推奨、注文、通知、Excelファイルは生成しません。

## Market Snapshotと個別調査

```shell
make sync
make market-snapshot
uv run marketsieve market show latest
uv run marketsieve market list
uv run marketsieve market query --market jp --present close --fields close --fields return_252d
uv run marketsieve market security XTKS:7203
make security-research INSTRUMENT=XTKS:7203
uv run marketsieve research show latest --security XTKS:7203
```

`make market-snapshot`は3年分の調整済み日足をバッチ取得し、企業・財務情報を制限付き並列で
取得します。組込の指数資産は構成銘柄と出典を固定する定義であり、実行時の代替データソース
ではありません。

成果物は`.marketsieve/market-snapshots/objects/SNAPSHOT_ID/`へ不変保存します。

- `README.md`：外部説明なしでデータを理解するための案内
- `securities.jsonl`：1銘柄1行の正本
- `definitions.json`：全フィールドの式、単位、期間、出典、定義版と欠損理由
- `market.json`、`segments.jsonl`、`quality.json`、`failures.jsonl`：市場の要約と品質
- `securities.csv`、`explorer.html`、`summary.md`：JSONLから作る閲覧用投影

`market list`、`market query`、`market security`、`market compare`は保存済み成果物だけを読み、
通信、再計算、部分集合の保存を行いません。過去断面はSnapshot IDで明示的に選びます。

`research build`は、選択したSnapshotに存在する銘柄だけを対象にします。最大10年の調整済み日足、
取得時点の企業情報、年次・四半期財務、配当・分割・決算イベント、失敗理由、市場・指数・セクター・
業種の文脈を`.marketsieve/research/objects/RESEARCH_ID/`へ不変保存します。スコア、推奨、AI向け
プロンプト、分析順序は含めません。将来MCP化しても、取得と保存の契約を変えずに公開できます。

## その他の運用

`make daily-status`で、設定と日常分析に必要なローカル状態を確認できます。

| 操作 | ターミナル | VS Code | 通信 | 生成物 |
| --- | --- | --- | --- | --- |
| 最新市場を表示 | `make market-show` | `01 Market: Show Latest Snapshot` | なし | Snapshotの場所 |
| 市場全体を更新 | `make market-snapshot` | `02 Market: Refresh Snapshot (Network)` | あり | Market Snapshot |
| 市場を絞り込む | `make market-query MARKET=jp` | `03 Market: Query Snapshot` | なし | 絞り込みJSON |
| 個別銘柄を調査 | `make security-research INSTRUMENT=XTKS:7203` | `04 Research: Build Security Pack (Network)` | あり | Research Pack |
| 最新調査を表示 | `make research-show INSTRUMENT=XTKS:7203` | `05 Research: Show Latest Security Pack` | なし | Research Packの場所 |

yfinanceの説明上、利用は調査・教育・個人利用が前提です。成果物は個人のローカル分析に限定します。
応答が部分的またはレート制限となった場合も、別ソースへ切り替えずその状態を記録します。

品質確認には`make format-check`、`make lint`、`make typecheck`、`make test`、`make check`を
使用します。詳しい契約は[正式設計](docs/design/README.md)を参照してください。
