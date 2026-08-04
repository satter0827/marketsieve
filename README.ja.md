# MarketSieve

[![CI](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml/badge.svg)](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MarketSieveは、日本株と米国株を再現可能な方法で分析するためのオープンソースPython基盤です。公開SDKとリポジトリ内の運用アプリケーションの依存境界を分け、市場ロジックをデータプロバイダー、レポートエージェント、配信チャネルから独立させます。

[English README](README.md)

## 目的

MarketSieveは、検証済みの市場情報から再現可能な分析、過去データ実験、根拠付きレポートを作成します。SDKをメール、LINE、LLMプロバイダー、データベースへ依存させず、交換可能なチャネルからレポートを配信します。

## 現在の状態

リポジトリのFoundationは完成しています。公開`marketsieve` packageが現在公開するのはpackage metadataだけで、リポジトリ内の運用アプリケーションはオフラインのバージョン表示と診断コマンドを提供します。承認済みの次期マイルストーンは、日米の合成日足データを使用するOffline Analysis Previewです。市場モデルと分析はまだ現在の機能ではありません。

## インストール

Python 3.12から3.14をサポートします。開発にはPython 3.13と[uv](https://docs.astral.sh/uv/)を使用します。

```shell
uv sync --locked
```

公開SDKは単独でビルドできます。

```shell
uv build --package marketsieve
```

## CLI

CLIはリポジトリ内の運用アプリケーションに属し、公開SDK wheelには含まれません。Foundation段階ではネットワークへ接続せず、秘密情報も要求しません。

```shell
uv run marketsieve --version
uv run marketsieve doctor
```

## アーキテクチャ

公開SDKは`packages/core`、運用アプリケーションは`apps/marketsieve`に配置します。運用アプリケーションはSDKへ依存しますが、SDKはアプリケーションやインフラストラクチャ用ライブラリをimportできません。[文書索引](docs/README.md)と正式な[Architecture](docs/design/architecture.md)に依存規則を記載しています。

## 開発

Pull Requestを作成する前に、完全なローカルゲートを実行します。

```shell
uv run pytest
uv run python scripts/quality_gate.py check all
```

変更は短命ブランチから`develop`へ統合します。人間が確認する`develop -> main` Pull Requestをリリース境界とします。手順は[Contributing](CONTRIBUTING.md)を参照してください。

## Roadmap

次のマイルストーンでは、日米の合成日足データから根拠付きのSMA20状態変化とオフラインdemoを生成する決定論的な縦切りを完成させます。後続の順序は[Roadmap](docs/roadmap.md)、承認済みの制約は[正式設計](docs/design/README.md)を参照してください。

## ライセンス

MarketSieveは[MIT License](LICENSE)で提供します。
