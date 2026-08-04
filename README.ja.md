# MarketSieve

[![CI](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml/badge.svg)](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MarketSieveは、日本株と米国株を再現可能な方法で分析するためのオープンソースPython基盤です。公開SDKとリポジトリ内の運用アプリケーションの依存境界を分け、市場ロジックをデータプロバイダー、レポートエージェント、配信チャネルから独立させます。

[English README](README.md)

## 目的

MarketSieveは、検証済みの市場情報から再現可能な分析、過去データ実験、根拠付きレポートを作成します。SDKをメール、LINE、LLMプロバイダー、データベースへ依存させず、交換可能なチャネルからレポートを配信します。

## 現在の状態

Offline Analysis Previewは完成しています。公開`marketsieve` packageは、取引所を明示した銘柄、日足contract、決定論的な日米Synthetic source、SMA20状態変化分析を提供します。リポジトリ内の運用アプリケーションから全経路をoffline demoとして実行できます。この結果は投資推奨ではありません。

## インストール

Python 3.12から3.14をサポートします。開発にはPython 3.13と[uv](https://docs.astral.sh/uv/)を使用します。

```shell
make sync
```

公開SDKは単独でビルドできます。

```shell
make build
```

## CLI

CLIはリポジトリ内の運用アプリケーションに属し、公開SDK wheelには含まれません。Foundation段階ではネットワークへ接続せず、秘密情報も要求しません。

```shell
uv run marketsieve --version
make doctor
make demo
make demo-json
```

`make demo`はJP、USの順に人間向け結果を表示します。`make demo-json`は入力期間、観測数、状態、遷移、provenance、evidence IDを含むversion付きmachine contractを出力します。

## アーキテクチャ

公開SDKは`packages/core`、運用アプリケーションは`apps/marketsieve`に配置します。運用アプリケーションはSDKへ依存しますが、SDKはアプリケーションやインフラストラクチャ用ライブラリをimportできません。[文書索引](docs/README.md)と正式な[Architecture](docs/design/architecture.md)に依存規則を記載しています。

## 開発

Makefileを人、コーディングエージェント、VS Code、CIに共通する操作の入口とします。利用できる操作は`make help`で確認できます。Pull Requestを作成する前に、テストと完全なローカルゲートを実行します。

```shell
make test
make check
make review
```

VS Codeはworkspaceの`.venv`を使用し、依存同期、format、現在のテストファイル、診断、完全Gateのtaskを提供します。ローカルcacheと生成物は`.marketsieve`に集約し、repository rootに置く生成環境は`.venv`だけとします。

`make check`はDevelop Gateを実行します。`make review`はこれに加えて、checksum付きreview bundleを`.marketsieve/artifacts/review/<commit>/`へ生成します。アプリケーション結果はstdout、構造化JSON Lines logはstderrへ出力します。情報logを取得する場合は`--log-level INFO`、`.marketsieve/logs/`にも保存する場合は`--log-file`を指定します。

変更は短命ブランチから`develop`へ統合します。人間が確認する`develop -> main` Pull Requestをリリース境界とします。手順は[Contributing](CONTRIBUTING.md)を参照してください。

## Roadmap

次のマイルストーンでは、完成したPreviewへhistorical replayとchannel-neutral reportを追加し、`0.1.0` candidateとします。順序は[Roadmap](docs/roadmap.md)、制約は[正式設計](docs/design/README.md)を参照してください。

## ライセンス

MarketSieveは[MIT License](LICENSE)で提供します。
