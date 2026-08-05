# MarketSieve

[![CI](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml/badge.svg)](https://github.com/satter0827/marketsieve/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MarketSieveは、日本株と米国株を再現可能な方法で分析するためのオープンソースPython基盤です。公開SDKとCLI applicationの依存境界を分け、市場ロジックをデータプロバイダー、レポートエージェント、配信チャネルから独立させます。

[English README](README.md)

## 目的

MarketSieveは、検証済みの市場情報から再現可能な分析、過去データ実験、根拠付きレポートを作成します。SDKをメール、LINE、LLMプロバイダー、データベースへ依存させず、交換可能なチャネルからレポートを配信します。

## 現在の状態

`develop`では0.3.0の基盤をPersonal Close Briefへ拡張しています。CSV、J-Quants、Alpha Vantage、FRED、SEC、EDINETを独立した配布物として扱い、変更不能な検証済みスナップショット、価格・テクニカル・財務・valuation・risk・event・data qualityの総合確認、比較、レポート、説明専用Agentを提供します。設定済みの`daily jp`と`daily us`は、ポートフォリオ銘柄を明示的に取得し、変更不能なClose Briefを保存します。`weekly`は有効な日米レポートをオフラインで週末作戦会議へまとめます。日米の銘柄集合は上限を指定して明示的に更新し、検証済みのローカル価格からオフラインで候補を抽出できます。候補の順序は根拠を確認でき、不透明な総合点を使いません。Agentは変更不能な判断レポートだけを読み、LM Studio、OpenAI、Anthropic、Googleのいずれかを明示した場合だけ動作します。説明は別成果物として保存され、レポートを変更しません。

## インストール

Python 3.12から3.14をサポートします。開発にはPython 3.13と[uv](https://docs.astral.sh/uv/)を使用します。

```shell
make sync
```

SDK、extension API、CLI、Agent、CSV source、J-Quants source、Alpha Vantage source、FRED source、SEC source、EDINET sourceは独立した配布物としてビルドできます。

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
uv run marketsieve equity-report XTKS:7203 --source-profile offline-jp --format rich
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

保存するのは正規化結果と入力digestだけで、元CSVは保存しません。楽天CSVは列を推測せず、
匿名化した実fixtureを根拠に追加します。

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
