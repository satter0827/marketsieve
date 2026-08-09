# MarketSieve

MarketSieveは、日本株・米国株の分析材料をローカルで生成・保存・確認するためのワークベンチです。
APIキー不要のyfinanceから、市場全体のMarket Snapshotと、選択した銘柄のSecurity Research Packを
生成します。解釈は人間または外部AIが行います。

ポートフォリオやウォッチリストは管理せず、スコア、順位、推奨、モデル出力は生成しません。

## ソースチェックアウトから実行する

macOSとUbuntu、Python 3.12から3.14をサポートします。

```shell
make sync
make doctor
make market-capture MARKET=jp
make market-capture MARKET=us
make market-show
make market-preview
```

個別調査では、検証済みSnapshotから正確な銘柄IDを選んでから証拠を生成します。

```shell
make market-query QUERY_ARGS='--market jp --profile swing --domain return --domain risk --order return_20d:desc --limit 30'
make research-build INSTRUMENTS='XTKS:7203'
make research-preview INSTRUMENT='XTKS:7203'
```

分析対象と証拠領域は実行ごとに指定します。任意の`marketsieve.settings.toml`には、取得並列数、
再試行、品質閾値などの運用設定だけを置き、`make setup-settings`で作成できます。

## 検証済みリリースをインストールする

1件のGitHub Releaseから全ファイルをダウンロードし、`SHA256SUMS`で検証してから、同じ
ディレクトリでCLIをインストールします。

```shell
python -m pip install --find-links . "marketsieve-cli==VERSION"
marketsieve doctor
```

4つのMarketSieve配布物はGitHub Releaseから取得します。外部ランタイム依存関係は、pipが設定済み
パッケージインデックスから解決します。MarketSieveの配布物はPyPIへ公開しません。

## 保存済み証拠を確認する

Snapshotは`.marketsieve/market-snapshots/objects/SNAPSHOT_ID/`、Research Packは
`.marketsieve/research/objects/RESEARCH_ID/`に保存します。JSON・JSONLが正本であり、
`summary.md`と`explorer.html`は同じ正本から作る決定的な表示です。Explorerはブラウザーの
fetch APIを使うため、`file://`で直接開かず、`market preview`または`research preview`を使います。

保存済みデータの確認では、ネットワーク取得や再計算を行いません。現行、非互換、破損、孤立した
成果物は次のコマンドで診断します。

```shell
marketsieve operations artifacts doctor --output json
```

1.0以前の成果物は自動移行も自動削除もしません。非互換と判定された場合は、現行コマンドで
再生成します。

公開前に取得が中断した場合、エラーと失敗した操作履歴に同じ16文字の再開run IDが表示されます。
保存済みの同一リクエストだけを`marketsieve market build --resume TOKEN`で再開します。

公開CLIは`market`、`research`、`operations`、`doctor`、`capabilities`です。公開SDKは
`marketsieve.model`、`marketsieve.indicators`、`marketsieve.fields`です。

詳細は[ドキュメント索引](docs/README.md)、[1.0ロードマップ](docs/roadmap.md)、
[開発手順](CONTRIBUTING.md)を参照してください。
