# MarketSieve

[![CI](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml/badge.svg)](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MarketSieveは、日本株と米国株を再現可能な方法で分析するためのオープンソースPython基盤です。公開SDKとCLI applicationの依存境界を分け、市場ロジックをデータプロバイダー、レポートエージェント、配信チャネルから独立させます。

[English README](README.md)

## 目的

MarketSieveは、検証済みの市場情報から再現可能な分析、過去データ実験、根拠付きレポートを作成します。SDKをメール、LINE、LLMプロバイダー、データベースへ依存させず、交換可能なチャネルからレポートを配信します。

## 現在の状態

`develop`には0.8.0のリリース候補があります。CSV、J-Quants、Alpha Vantage、FRED、SEC、EDINETを独立した配布物として扱い、変更不能な検証済みスナップショット、価格・テクニカル・財務・valuation・risk・event・data qualityの総合確認、比較、レポート、説明専用Agentを提供します。設定済みの`daily jp`と`daily us`は、ポートフォリオ銘柄を明示的に取得し、変更不能なClose Briefを保存します。`weekly`は有効な日米レポートと期限内の候補をオフラインで週末作戦会議へまとめ、保有判断と`残った候補`を分けて表示します。日米の銘柄集合は上限を指定して明示的に更新し、検証済みのローカル価格からオフラインで候補を抽出できます。候補の順序は根拠を確認でき、不透明な総合点を使いません。手動AI交換はChatGPT画面を利用し、API keyを必要としません。既存Agentは変更不能な判断レポートだけを読み、LM Studio、OpenAI、Anthropic、Googleのいずれかを明示した場合だけ動作します。どちらの説明も別成果物として保存され、レポートを変更しません。

## 日常利用

VS Codeの「実行とデバッグ」を開くと、実行順を示す番号付き構成が先頭に並びます。初回は`01`から`03`を順番に実行します。保有銘柄または監視銘柄が変わった場合は`02`と`03`を再実行します。各市場の終値後に`10`または`20`、週末にだけ`30`を実行します。生成された依頼ファイルをChatGPTへ渡して回答JSONを保存したら、`40`で取込と表示まで完了します。同名のTasksも代替入口として利用できます。

基本のAI動線では、新しいChatGPT Temporary Chatとファイルを使用します。API keyもブラウザ自動操作も使用しません。出力された絶対パスの依頼ファイルをアップロードし、ChatGPTのJSON回答を推奨パスへ保存します。Project、Web検索、外部ツールは使用せず、Custom Instructionsは無効化します。

ChatGPT用のAPI keyは不要です。市場データ取得では、設定したproviderによって認証情報が必要になる場合があります。TaskはVS Codeプロセスの環境変数を引き継ぎます。`03`で不足と表示された場合は、必要な変数を設定した環境からVS Codeを起動し直します。値を`tasks.json`や`marketsieve.toml`へ書きません。

| 操作 | ターミナル | VS Code 実行構成 | 通信 | 生成物 |
| --- | --- | --- | --- | --- |
| 1. 設定作成 | `make setup-config` | `01 First Run: Create Configuration` | なし | `marketsieve.toml` |
| 2. ポートフォリオ取込 | `make portfolio-import PORTFOLIO=/absolute/path/holdings.csv` | `02 First Run: Import Portfolio CSV` | なし | 正規化済みポートフォリオ |
| 3. 準備確認 | `make daily-status` | `03 First Run: Check Readiness` | なし | 診断と次のTask |
| 10. 日本株終値分析 | `make daily-jp-ai` | `10 Daily: Analyze JP Close and Prepare ChatGPT Request (Network)` | 市場データ取得のみ | レポート、`request.json` |
| 20. 米国株終値分析 | `make daily-us-ai` | `20 Daily: Analyze US Close and Prepare ChatGPT Request (Network)` | 市場データ取得のみ | レポート、`request.json` |
| 30. 週次まとめ | `make weekly-ai` | `30 Weekly: Build Brief and Prepare ChatGPT Request (After JP and US)` | なし | レポート、`request.json` |
| 40. 回答取込・表示 | `make ai-import RESPONSE=/absolute/path/response.json` | `40 ChatGPT: Import Saved Response and Display Explanation` | なし | 回答、検証、説明 |

ChatGPTが返すのは、提示済みfact ID、表示順、数値を含まない事実間の関係だけです。MarketSieveが回答を検証し、変更不能なレポートの値から説明を生成します。既存のAPI・ローカルモデルAgentは高度な任意機能として引き続き利用できます。

新しいTemporary Chat、Custom Instructions無効、Project・Web検索・外部ツール無効を確認した場合だけ、取込時に`CONTROLLED=1`を選択します。通常の取込は確認済みと記録しません。API provider、個別のAI操作、デバッグは削除せず、番号付きの主動線より後ろにある詳細操作とRun and Debugへ分離しています。

## インストール

Python 3.12から3.14をサポートします。開発にはPython 3.13と[uv](https://docs.astral.sh/uv/)を使用します。

```shell
make sync
```

SDK、extension API、CLI、手動AI交換、Agent、CSV source、J-Quants source、Alpha Vantage source、FRED source、SEC source、EDINET sourceは独立した配布物としてビルドできます。

```shell
make build
```

公開時は、独立した配布物をPyPIへ送り、同じ成果物をchecksum付きGitHub Release
wheelhouseとして残します。通常はPyPIからinstallします。

```shell
python -m pip install "marketsieve-cli[all-sources]>=0.8,<0.9"
```

offlineで使用する場合は、assetを`release.json`で検証してwheelhouse ZIPを展開した後、
indexを使わずにinstallします。

```shell
python -m pip install --no-index --find-links ./marketsieve-wheelhouse \
  "marketsieve-cli[all-sources]"
```

同じwheelhouseから`marketsieve-cli[all]`を指定すると、全sourceに加えて任意機能のAgentもinstallできます。

## CLI

公開`marketsieve-cli` distributionはSDKへ依存しますが、SDK wheelには含まれません。参照系コマンドはオフラインで動作します。明示的な`source fetch`と`daily`取得だけが、選択したプロバイダーの環境変数を読み、ネットワークへ接続します。

```shell
uv run marketsieve --version
make doctor
make capabilities-json
```

`make capabilities-json`はAI client向けにcommand、option、schema、exit code、stream、副作用を説明します。inspect、analyze、compare、reportは検証済みlocal snapshotだけを読み、取得は常に明示的に実行します。

各output modeは直接指定できます。

```shell
uv run marketsieve doctor --output json
uv run marketsieve capabilities --output json
uv run marketsieve source list --output json
uv run marketsieve source import ./example-bundle --output json
uv run marketsieve --config marketsieve.toml source fetch us XNAS:MSFT --start 2026-01-01 --end 2026-07-31 --output json
uv run marketsieve snapshot verify SNAPSHOT_ID --output json
uv run marketsieve inspect XTKS:7203 --source-profile offline-jp --output json
uv run marketsieve analyze rsi XTKS:7203 --period 14 --source-profile offline-jp --output json
uv run marketsieve compare XTKS:7203 XTKS:6758 --source-profile offline-jp --output json
uv run marketsieve report list --output json
uv run marketsieve report show latest --output json
uv run marketsieve report export latest --format markdown
uv run marketsieve --config marketsieve.toml daily jp
uv run marketsieve --config marketsieve.toml weekly
uv run marketsieve --config marketsieve.toml screen update jp --output json
uv run marketsieve --config marketsieve.toml screen run jp --output json
uv run marketsieve --config marketsieve.toml screen show latest --market jp --output json
uv run marketsieve --config marketsieve.toml report explain latest --provider openai --dry-run --output json
```

canonical portfolio CSVのheaderは
`kind,mic,symbol,currency,timezone,quantity,average_acquisition_price,account_type`です。
`holding`は全項目を指定し、`watch`は末尾3項目を空にします。

```shell
uv run marketsieve portfolio import holdings.csv --broker canonical \
  --as-of 2026-08-06T20:00:00+09:00
uv run marketsieve portfolio show
```

楽天証券の空の`assetbalance(all)`は直接取り込めます。

```shell
uv run marketsieve portfolio import assetbalance.csv --broker rakuten \
  --as-of 2026-08-06T12:48:40+09:00
```

保存するのは正規化結果と入力digestだけで、元CSVは保存しません。楽天adapterが受け付ける
のは、検証済みの保有なし形式だけです。保有銘柄と監視銘柄は、匿名化した保有あり出力で
形式を確認できるまでcanonical CSVを使用します。

## アーキテクチャ

公開SDKは`packages/core`、実装済みextension contractは`packages/extension-api`、プロバイダーadapterは`packages/source-*`、CLIは`packages/cli`に配置します。SDKはアプリケーションやインフラストラクチャ用ライブラリをimportできません。[文書索引](docs/README.md)と正式な[Architecture](docs/design/architecture.md)に依存規則を記載しています。

## 開発

Makefileを人、コーディングエージェント、VS Code、CIに共通する操作の入口とします。利用できる操作は`make help`で確認できます。Pull Requestを作成する前に、テストと完全なローカルゲートを実行します。

```shell
make test
make check
make evidence
```

VS Codeはworkspaceの`.venv`を使用します。`make sync`の実行後、「実行とデバッグ」を日常分析の主入口として使えます。Tasksは同じ日常操作と品質ゲートを提供し、番号付き構成より後ろの詳細操作はCLIコードのデバッグに使用します。Test Explorerはテストとカバレッジを担当します。対話的なカバレッジはローカル確認用とし、`make check`を正式なカバレッジGateとします。ローカルcacheと生成物は`.marketsieve`に集約し、repository rootに置く生成環境は`.venv`だけとします。

`make check`はDevelop Gateを実行します。`make evidence`はこれに加えて、checksum付きreview bundleを`.marketsieve/artifacts/review/<commit>/`へ生成します。bundleはcode reviewの入力であり、review完了の証拠ではありません。アプリケーション結果はstdout、構造化JSON Lines logはstderrへ出力します。情報logを取得する場合は`--log-level INFO`、`.marketsieve/logs/`にも保存する場合は`--log-file`を指定します。

変更は短命ブランチから`develop`へ統合します。人間が確認する`develop -> main` Pull Requestをリリース境界とします。手順は[Contributing](CONTRIBUTING.md)を参照してください。

## プラグイン開発

provider packageはCLI内部ではなく、データ種別ごとに小さく分けたextension APIへ依存します。
[外部universe pluginの例](examples/instrument-universe-plugin/README.md)はworkspace catalogの外にあり、
`marketsieve-extension-api>=0.8,<0.9`、entry point、公開conformance checkを示します。完全Gateは
このwheelをbuildし、公開wheel一式と隔離環境へinstallします。

## Roadmap

今後の順序は[Roadmap](docs/roadmap.md)、制約は[正式設計](docs/design/README.md)を参照してください。

## ライセンス

MarketSieveは[MIT License](LICENSE)で提供します。
