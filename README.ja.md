# MarketSieve

[![CI](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml/badge.svg)](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MarketSieveは、日本株と米国株を再現可能な方法で分析するためのオープンソースPython基盤です。公開SDKとCLI applicationの依存境界を分け、市場ロジックをデータプロバイダー、レポートエージェント、配信チャネルから独立させます。

[English README](README.md)

## 目的

MarketSieveは、検証済みの市場情報から再現可能な分析、過去データ実験、根拠付きレポートを作成します。SDKをメール、LINE、LLMプロバイダー、データベースへ依存させず、交換可能なチャネルからレポートを配信します。

## 現在の状態

`develop`では0.3.0の基盤をPersonal Close Briefへ拡張しています。CSV、J-Quants、Alpha Vantage、FREDを独立した配布物として扱い、変更不能な検証済みスナップショット、価格・テクニカル・財務・valuation・risk・event・data qualityの総合確認、比較、レポート、説明専用Agentを提供します。FakeListLLMを既定とし、LM Studioと明示的に許可したOpenAI、Anthropic、Googleも同じgrounded pipelineを使用します。CLIは根拠と欠損理由を提示し、投資判断を推奨しません。

## インストール

Python 3.12から3.14をサポートします。開発にはPython 3.13と[uv](https://docs.astral.sh/uv/)を使用します。

```shell
make sync
```

SDK、extension API、CLI、Agent、CSV source、J-Quants source、Alpha Vantage source、FRED sourceは独立した配布物としてビルドできます。

```shell
make build
```

公開releaseはPyPIではなく、checksum付きGitHub Release wheelhouseを使用します。assetを
`release.json`で検証してwheelhouse ZIPを展開した後、offlineでinstallします。

```shell
python -m pip install --no-index --find-links ./marketsieve-wheelhouse \
  "marketsieve-cli[all-sources]"
```

同じwheelhouseから`marketsieve-cli[all]`を指定すると、全sourceに加えて任意機能のAgentもinstallできます。

## CLI

公開`marketsieve-cli` distributionはSDKへ依存しますが、SDK wheelには含まれません。参照系コマンドはオフラインで動作します。プロバイダーから取得する場合だけ、明示的な`source fetch`が環境変数の認証情報を読み、ネットワークへ接続します。

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
uv run marketsieve report XTKS:7203 --source-profile offline-jp --format rich
uv run marketsieve agent explain XTKS:7203 --source-profile offline-jp --output json
uv run marketsieve --config marketsieve.toml agent explain XTKS:7203 --source-profile offline-jp --provider openai --dry-run --output json
```

## アーキテクチャ

公開SDKは`packages/core`、実装済みextension contractは`packages/extension-api`、プロバイダーadapterは`packages/source-*`、CLIは`packages/cli`に配置します。SDKはアプリケーションやインフラストラクチャ用ライブラリをimportできません。[文書索引](docs/README.md)と正式な[Architecture](docs/design/architecture.md)に依存規則を記載しています。

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

0.2 workbenchと0.3 grounded explanation Agentはdevelop上で完成しています。順序は[Roadmap](docs/roadmap.md)、制約は[正式設計](docs/design/README.md)を参照してください。

## ライセンス

MarketSieveは[MIT License](LICENSE)で提供します。
