# MarketSieve

[![CI](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml/badge.svg)](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MarketSieveは、日本株と米国株を再現可能な方法で分析するためのオープンソースPython基盤です。公開SDKとCLI applicationの依存境界を分け、市場ロジックをデータプロバイダー、レポートエージェント、配信チャネルから独立させます。

[English README](README.md)

## 目的

MarketSieveは、検証済みの市場情報から再現可能な分析、過去データ実験、根拠付きレポートを作成します。SDKをメール、LINE、LLMプロバイダー、データベースへ依存させず、交換可能なチャネルからレポートを配信します。

## 現在の状態

`0.1.0`が現在の公開基準です。次のdevelop sliceでは、独立packageのCSV import、変更不能なlocal snapshot、検証、price inspectionを追加します。公開`marketsieve` packageは、取引所を明示した銘柄、日足contract、決定論的な日米Synthetic source、SMA20状態変化分析、未来情報を排除したhistorical replay、channel-neutral reportを提供します。CLIが提示する結果は投資推奨ではありません。

## インストール

Python 3.12から3.14をサポートします。開発にはPython 3.13と[uv](https://docs.astral.sh/uv/)を使用します。

```shell
make sync
```

SDK、extension API、CLI、CSV sourceは独立artifactとしてビルドできます。

```shell
make build
```

## CLI

公開`marketsieve-cli` distributionはSDKへ依存しますが、SDK wheelには含まれません。現在のcommandはネットワークへ接続せず、秘密情報も要求しません。

```shell
uv run marketsieve --version
make doctor
make report
make report-json
make capabilities-json
```

`make report`は利用可能なterminalではRich表示を使用し、redirect時はANSIを含まないtextへ切り替えます。`make report-json`はversion付きreport contractを出力します。`make capabilities-json`はAI client向けにcommand、option、schema、exit code、stream、副作用を説明します。

各output modeは直接指定できます。

```shell
uv run marketsieve doctor --output json
uv run marketsieve report --market all --output rich
uv run marketsieve capabilities --output json
uv run marketsieve source list --output json
uv run marketsieve source import ./example-bundle --output json
uv run marketsieve snapshot verify SNAPSHOT_ID --output json
uv run marketsieve inspect XTKS:7203 --source-profile offline-jp --output json
```

## アーキテクチャ

公開SDKは`packages/core`、実装済みextension contractは`packages/extension-api`、CSV adapterは`packages/source-csv`、CLIは`packages/cli`に配置します。SDKはアプリケーションやインフラストラクチャ用ライブラリをimportできません。[文書索引](docs/README.md)と正式な[Architecture](docs/design/architecture.md)に依存規則を記載しています。

## 開発

Makefileを人、コーディングエージェント、VS Code、CIに共通する操作の入口とします。利用できる操作は`make help`で確認できます。Pull Requestを作成する前に、テストと完全なローカルゲートを実行します。

```shell
make test
make check
make evidence
```

VS Codeはworkspaceの`.venv`を使用し、依存同期、format、現在のテストファイル、診断、完全Gateのtaskを提供します。ローカルcacheと生成物は`.marketsieve`に集約し、repository rootに置く生成環境は`.venv`だけとします。

`make check`はDevelop Gateを実行します。`make evidence`はこれに加えて、checksum付きreview bundleを`.marketsieve/artifacts/review/<commit>/`へ生成します。bundleはcode reviewの入力であり、review完了の証拠ではありません。アプリケーション結果はstdout、構造化JSON Lines logはstderrへ出力します。情報logを取得する場合は`--log-level INFO`、`.marketsieve/logs/`にも保存する場合は`--log-file`を指定します。

変更は短命ブランチから`develop`へ統合します。人間が確認する`develop -> main` Pull Requestをリリース境界とします。手順は[Contributing](CONTRIBUTING.md)を参照してください。

## Roadmap

historical reportの処理経路が`0.1.0`の基準です。外部data sourceと個人向け配信channelは後続milestoneです。順序は[Roadmap](docs/roadmap.md)、制約は[正式設計](docs/design/README.md)を参照してください。

## ライセンス

MarketSieveは[MIT License](LICENSE)で提供します。
