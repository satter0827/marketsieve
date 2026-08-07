"""Immutable market-matrix storage and deterministic projections."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import shutil
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from marketsieve.matrix import MatrixField, MatrixRow


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _request_fingerprint(value: object) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _row_document(row: MatrixRow) -> dict[str, Any]:
    instrument = row.security.instrument
    return {
        "schema": "market-matrix-security/v1",
        "instrument_id": f"{instrument.mic}:{instrument.symbol}",
        "instrument": {
            "mic": instrument.mic,
            "symbol": instrument.symbol,
            "currency": instrument.currency,
            "exchange_timezone": instrument.exchange_timezone.key,
            "instrument_type": instrument.instrument_type.value,
        },
        "provider_symbol": row.security.provider_symbol,
        "memberships": list(row.security.memberships),
        "retrieved_at": row.security.retrieved_at.isoformat(),
        "evidence_id": row.security.evidence_id,
        "values": dict(row.values),
        "missing": dict(row.missing),
    }


def _field_document(field: MatrixField) -> dict[str, Any]:
    return {
        "name": field.name,
        "group": field.group,
        "data_type": field.data_type,
        "unit": field.unit,
        "source": field.source,
        "definition": field.definition,
        "formula": field.formula,
        "period": field.period,
        "definition_version": field.definition_version,
    }


class MatrixStore:
    """Persist one complete content-addressed matrix object."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects = root / "objects"
        self.runs = root / "runs"
        self.latest_ref = root / "latest.json"

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if len(run_id) != 16 or any(character not in "0123456789abcdef" for character in run_id):
            raise ValueError("matrix run ID must be 16 lowercase hexadecimal characters")

    def run_request(self, run_id: str) -> dict[str, Any]:
        self._validate_run_id(run_id)
        self._require_directory(self.runs)
        run_path = self.runs / run_id
        path = run_path / "request.json"
        if run_path.is_symlink() or path.is_symlink() or not path.is_file():
            raise LookupError(f"matrix run does not exist: {run_id}")
        raw = path.read_bytes()
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("matrix run request is not valid JSON") from error
        if not isinstance(document, dict) or set(document) != {"fingerprint", "request", "status"}:
            raise ValueError("matrix run request has an invalid schema")
        if document["status"] != "started" or not isinstance(document["request"], dict):
            raise ValueError("matrix run request has an invalid schema")
        if raw != _json_bytes(document):
            raise ValueError("matrix run request is not canonical JSON")
        expected_fingerprint = _request_fingerprint(document["request"])
        if document["fingerprint"] != expected_fingerprint:
            raise ValueError("matrix run request fingerprint does not match its content")
        return document["request"]

    def begin_run(
        self,
        fingerprint: str,
        request_document: dict[str, Any],
        *,
        resume: str | None,
    ) -> str:
        if len(fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in fingerprint
        ):
            raise ValueError("matrix fingerprint must be a lowercase SHA-256 digest")
        expected_fingerprint = _request_fingerprint(request_document)
        if fingerprint != expected_fingerprint:
            raise ValueError("matrix fingerprint does not match the request content")
        run_id = resume or fingerprint[:16]
        self._validate_run_id(run_id)
        self._ensure_directory(self.runs)
        path = self.runs / run_id
        if resume is not None:
            stored_request = self.run_request(run_id)
            if stored_request != request_document:
                raise ValueError("matrix resume request does not match the stored run fingerprint")
            return run_id
        if path.exists() or path.is_symlink():
            raise ValueError(
                f"matrix run already exists: {run_id}; resume it with --resume {run_id}"
            )
        temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=self.runs))
        try:
            request_path = temporary / "request.json"
            with request_path.open("wb") as stream:
                stream.write(
                    _json_bytes(
                        {
                            "fingerprint": fingerprint,
                            "request": request_document,
                            "status": "started",
                        }
                    )
                )
                stream.flush()
                os.fsync(stream.fileno())
            try:
                temporary.rename(path)
            except FileExistsError:
                raise ValueError(
                    f"matrix run already exists: {run_id}; resume it with --resume {run_id}"
                ) from None
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return run_id

    def put(
        self,
        *,
        run_id: str,
        manifest_body: dict[str, Any],
        fields: tuple[MatrixField, ...],
        rows: tuple[MatrixRow, ...],
        summary: dict[str, Any],
        failures: tuple[dict[str, str], ...],
    ) -> dict[str, Any]:
        stored_request = self.run_request(run_id)
        expected_request_evidence = {
            "fingerprint": _request_fingerprint(stored_request),
            **stored_request,
        }
        if manifest_body.get("request") != expected_request_evidence:
            raise ValueError("matrix manifest request does not match the persisted run")
        row_documents = tuple(_row_document(row) for row in rows)
        field_documents = tuple(_field_document(field) for field in fields)
        semantic = {
            **manifest_body,
            "field_definitions": field_documents,
            "row_hashes": [hashlib.sha256(_json_bytes(row)).hexdigest() for row in row_documents],
            "summary": summary,
            "failures": failures,
        }
        matrix_id = hashlib.sha256(_json_bytes(semantic)).hexdigest()
        manifest = {
            "schema": "market-matrix-manifest/v1",
            "matrix_id": matrix_id,
            **manifest_body,
        }
        destination = self.objects / matrix_id
        self._ensure_directory(self.objects)
        if destination.is_dir():
            self._verify_object(destination, matrix_id)
        else:
            pending = self.objects / f".{matrix_id}.{os.getpid()}.pending"
            pending.mkdir(parents=False, exist_ok=False)
            try:
                (pending / "manifest.json").write_bytes(_json_bytes(manifest))
                (pending / "fields.json").write_bytes(_json_bytes(list(field_documents)))
                self._write_jsonl(pending / "securities.jsonl", row_documents)
                (pending / "index-summary.json").write_bytes(_json_bytes(summary))
                self._write_jsonl(pending / "failures.jsonl", failures)
                self._write_csv(pending / "matrix.csv", fields, row_documents)
                self._write_html(
                    pending / "overview.html", manifest, summary, fields, row_documents
                )
                (pending / "analysis.md").write_text(
                    self._analysis_markdown(manifest, summary), encoding="utf-8"
                )
                pending.rename(destination)
            except BaseException:
                shutil.rmtree(pending, ignore_errors=True)
                raise
        self._ensure_directory(self.root)
        temporary = self.root / f".latest.{os.getpid()}.tmp"
        if temporary.exists() or temporary.is_symlink():
            raise ValueError("matrix latest-reference temporary path already exists")
        run_path = self.runs / run_id
        if run_path.is_symlink() or not run_path.is_dir():
            raise ValueError("matrix run path must be a real directory")
        document = self.show(matrix_id)
        try:
            temporary.write_bytes(_json_bytes({"matrix_id": matrix_id}))
            temporary.replace(self.latest_ref)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        with suppress(OSError):
            shutil.rmtree(run_path, ignore_errors=True)
        return document

    @staticmethod
    def _write_jsonl(path: Path, documents: Iterable[object]) -> None:
        with path.open("wb") as stream:
            for document in documents:
                stream.write(_json_bytes(document))

    @staticmethod
    def _write_csv(
        path: Path, fields: tuple[MatrixField, ...], rows: tuple[dict[str, Any], ...]
    ) -> None:
        names = [field.name for field in fields]
        header = [
            "instrument_id",
            "provider_symbol",
            "memberships_json",
            "retrieved_at",
            *names,
            "missing_fields_json",
            "evidence_id",
        ]
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=header)
            writer.writeheader()
            for row in rows:
                values = row["values"]
                writer.writerow(
                    {
                        "instrument_id": row["instrument_id"],
                        "provider_symbol": row["provider_symbol"],
                        "memberships_json": json.dumps(
                            row["memberships"], ensure_ascii=False, separators=(",", ":")
                        ),
                        "retrieved_at": row["retrieved_at"],
                        **{name: values.get(name, "") for name in names},
                        "missing_fields_json": json.dumps(
                            row["missing"],
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        "evidence_id": row["evidence_id"],
                    }
                )

    @staticmethod
    def _write_html(
        path: Path,
        manifest: dict[str, Any],
        summary: dict[str, Any],
        fields: tuple[MatrixField, ...],
        rows: tuple[dict[str, Any], ...],
    ) -> None:
        columns = [
            "instrument_id",
            "memberships",
            "provider_symbol",
            "retrieved_at",
            *(field.name for field in fields),
        ]
        table_rows: list[str] = []
        for row in rows:
            values = row["values"]
            record = {
                "instrument_id": row["instrument_id"],
                "memberships": ", ".join(row["memberships"]),
                "provider_symbol": row["provider_symbol"],
                "retrieved_at": row["retrieved_at"],
                **values,
            }
            cells = "".join(
                f"<td>{html.escape(str(record.get(name, '')))}</td>" for name in columns
            )
            row_memberships = html.escape(",".join(row["memberships"]))
            table_rows.append(f'<tr data-memberships="{row_memberships}">{cells}</tr>')
        field_groups: dict[str, int] = {}
        for field in fields:
            field_groups[field.group] = field_groups.get(field.group, 0) + 1
        summary_json = html.escape(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
        )
        groups_json = html.escape(
            json.dumps(field_groups, ensure_ascii=False, indent=2, sort_keys=True)
        )
        headers = "".join(
            f'<th><button type="button" data-column="{index}">{html.escape(name)}</button></th>'
            for index, name in enumerate(columns)
        )
        body = "".join(table_rows)
        index_memberships = sorted(
            {membership for row in rows for membership in row["memberships"]}
        )
        index_options = "".join(
            f'<option value="{html.escape(value)}">{html.escape(value)}</option>'
            for value in index_memberships
        )
        style = (
            "body{font:14px system-ui;margin:2rem;color:CanvasText;background:Canvas}"
            "h1{margin-bottom:.25rem}.meta{color:GrayText}"
            "input{padding:.6rem;width:min(32rem,90%);margin:1rem 0}"
            "select{padding:.6rem;margin:1rem}button{font:inherit;border:0;"
            "background:transparent;color:inherit;font-weight:700;cursor:pointer}"
            ".wrap{overflow:auto;border:1px solid GrayText}"
            "table{border-collapse:collapse;min-width:1200px;width:100%}"
            "th,td{padding:.45rem .6rem;border-bottom:1px solid GrayText;"
            "text-align:right;white-space:nowrap}"
            "th:first-child,td:first-child,th:nth-child(2),td:nth-child(2),"
            "th:nth-child(3),td:nth-child(3){text-align:left}"
            "thead{position:sticky;top:0;background:Canvas}tr[hidden]{display:none}"
        )
        script = (
            "const q=document.querySelector('#filter'),idx=document.querySelector('#index');"
            "const rows=[...document.querySelectorAll('#matrix tbody tr')];"
            "const apply=()=>{const value=q.value.toLowerCase(),index=idx.value;"
            "for(const row of rows){row.hidden=!row.textContent.toLowerCase().includes(value)"
            "||(index&&!row.dataset.memberships.split(',').includes(index))}};"
            "q.addEventListener('input',apply);idx.addEventListener('change',apply);"
            "for(const button of document.querySelectorAll('th button')){"
            "button.addEventListener('click',()=>{const column=Number(button.dataset.column);"
            "const direction=button.dataset.direction==='asc'?'desc':'asc';"
            "button.dataset.direction=direction;rows.sort((left,right)=>{"
            "const a=left.cells[column].textContent.trim(),"
            "b=right.cells[column].textContent.trim();"
            "const an=Number(a),bn=Number(b);const value=a!==''&&b!==''&&!Number.isNaN(an)"
            "&&!Number.isNaN(bn)?an-bn:a.localeCompare(b);return direction==='asc'?value:-value});"
            "const body=document.querySelector('#matrix tbody');for(const row of rows)"
            "body.appendChild(row)})}"
        )
        document = (
            '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="color-scheme" content="light dark">'
            f"<title>MarketSieve 全銘柄マトリックス</title><style>{style}</style></head>"
            "<body><h1>MarketSieve 全銘柄マトリックス</h1>"
            f'<p class="meta">マトリックス {manifest["matrix_id"]} · '
            f"{manifest['row_count']}銘柄 · {len(fields)}指標</p>"
            "<p>指数横断の全銘柄表です。空欄の理由は正本JSONLと"
            "failures.jsonlに保持されています。</p>"
            f"<details><summary>指数要約</summary><pre>{summary_json}</pre></details>"
            f"<details><summary>指標グループ</summary><pre>{groups_json}</pre></details>"
            '<label>検索 <input id="filter" type="search" '
            'placeholder="銘柄、指数、名称"></label>'
            f'<label>指数 <select id="index"><option value="">すべて</option>{index_options}'
            "</select></label>"
            f'<div class="wrap"><table id="matrix"><thead><tr>{headers}</tr>'
            f"</thead><tbody>{body}</tbody></table></div>"
            f"<script>{script}</script></body></html>"
        )
        path.write_text(document, encoding="utf-8")

    @staticmethod
    def _analysis_markdown(manifest: dict[str, Any], summary: dict[str, Any]) -> str:
        lines = [
            "# MarketSieve 指数横断分析",
            "",
            f"- マトリックスID: `{manifest['matrix_id']}`",
            f"- 取得時刻: `{manifest['created_at']}`",
            f"- 銘柄数: {manifest['row_count']}",
            f"- 指標数: {manifest['field_count']}",
            f"- 全体価格取得率: {summary['coverage']['overall']}",
            f"- 品質状態: `{summary['quality_status']}`",
            "",
            "個別銘柄の順位付けや売買推奨は行わず、指数横断の分布と欠損を記述します。",
            "",
        ]
        distribution_sections = (
            ("リターン", ("return_20d", "return_60d", "return_252d")),
            (
                "リスク",
                ("volatility_60d", "volatility_252d", "maximum_drawdown_252d"),
            ),
            ("バリュエーション", ("trailing_pe", "price_to_book")),
            ("収益性", ("operating_margin", "return_on_equity")),
            ("成長性", ("revenue_growth",)),
        )
        for name, group in sorted(summary["groups"].items()):
            display_name = (
                "全体"
                if name == "all"
                else manifest["universe_assets"].get(name, {}).get("name", name)
            )
            lines.extend(
                (
                    f"## {display_name}",
                    "",
                    "### 市場幅とトレンド",
                    "",
                    f"- 銘柄数: {group['security_count']}",
                    f"- 価格取得率: {group['price_coverage']}",
                    f"- 上昇 / 下落 / 変わらず: {group['advancing_count']} / "
                    f"{group['declining_count']} / {group['unchanged_count']}",
                    f"- SMA20超: {group['above_sma_20_count']}",
                    f"- SMA200超: {group['above_sma_200_count']}",
                )
            )
            lines.extend(("", "### 規模", ""))
            market_cap_distributions = group["currency_distributions"]["market_cap"]
            if not market_cap_distributions:
                lines.append("- 時価総額: 取得値なし")
            for currency, distribution in sorted(market_cap_distributions.items()):
                lines.append(
                    f"- 時価総額 ({currency}): 件数={distribution['count']}, "
                    f"第1四分位={distribution['p25']}, "
                    f"中央値={distribution['median']}, "
                    f"第3四分位={distribution['p75']}"
                )
            lines.extend(("", "### 流動性", ""))
            traded_value_distributions = group["currency_distributions"]["median_traded_value_20d"]
            if not traded_value_distributions:
                lines.append("- median_traded_value_20d: 取得値なし")
            for currency, distribution in sorted(traded_value_distributions.items()):
                lines.append(
                    f"- median_traded_value_20d ({currency}): 件数={distribution['count']}, "
                    f"第1四分位={distribution['p25']}, "
                    f"中央値={distribution['median']}, "
                    f"第3四分位={distribution['p75']}"
                )
            for title, field_names in distribution_sections:
                lines.extend(("", f"### {title}", ""))
                for field in field_names:
                    distribution = group["distributions"].get(field)
                    if distribution is None:
                        lines.append(f"- {field}: 取得値なし")
                    else:
                        lines.append(
                            f"- {field}: 件数={distribution['count']}, "
                            f"第1四分位={distribution['p25']}, "
                            f"中央値={distribution['median']}, "
                            f"第3四分位={distribution['p75']}"
                        )
            concentration = group["concentration"]
            lines.extend(
                (
                    "",
                    "### 集中度・セクター構成",
                    "",
                )
            )
            if not concentration["by_currency"]:
                lines.append("- 時価総額上位10社構成比: 取得値なし")
            for currency, value in sorted(concentration["by_currency"].items()):
                lines.append(
                    f"- 時価総額上位10社構成比 ({currency}): {value['top_10_market_cap_share']}"
                )
            for sector, value in sorted(group["sectors"].items()):
                shares = ", ".join(
                    f"{currency}={share}"
                    for currency, share in sorted(value["market_cap_share_by_currency"].items())
                )
                lines.append(
                    f"- {sector}: {value['security_count']}銘柄, "
                    f"通貨別時価総額構成比={shares or '取得値なし'}"
                )
            lines.extend(("", "### 欠損傾向", ""))
            for reason, count in sorted(group["missing"]["reasons"].items()):
                lines.append(f"- 理由 `{reason}`: {count}セル")
            missing_fields = sorted(
                group["missing"]["fields"].items(), key=lambda value: (-value[1], value[0])
            )[:10]
            for field, count in missing_fields:
                lines.append(f"- 欠損フィールド `{field}`: {count}銘柄")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def resolve_id(self, matrix_id: str) -> str:
        if matrix_id != "latest":
            return matrix_id
        self._require_directory(self.root)
        if self.latest_ref.is_symlink() or not self.latest_ref.is_file():
            raise LookupError("no market matrix is available")
        raw = self.latest_ref.read_bytes()
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("market matrix latest reference is invalid") from error
        if (
            not isinstance(value, dict)
            or set(value) != {"matrix_id"}
            or raw != _json_bytes(value)
            or not isinstance(value["matrix_id"], str)
            or len(value["matrix_id"]) != 64
            or any(character not in "0123456789abcdef" for character in value["matrix_id"])
        ):
            raise ValueError("market matrix latest reference is invalid")
        return value["matrix_id"]

    def show(self, matrix_id: str) -> dict[str, Any]:
        resolved = self.resolve_id(matrix_id)
        self._require_directory(self.objects)
        path = self.objects / resolved
        self._verify_object(path, resolved)
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        summary = json.loads((path / "index-summary.json").read_text(encoding="utf-8"))
        return {
            **manifest,
            "schema": "market-matrix/v1",
            "summary": summary,
            "artifacts": {
                name: str(path / name)
                for name in (
                    "manifest.json",
                    "fields.json",
                    "securities.jsonl",
                    "index-summary.json",
                    "failures.jsonl",
                    "matrix.csv",
                    "overview.html",
                    "analysis.md",
                )
            },
        }

    def row(self, matrix_id: str, instrument_id: str) -> dict[str, Any]:
        resolved = self.resolve_id(matrix_id)
        self._require_directory(self.objects)
        self._verify_object(self.objects / resolved, resolved)
        for document in self._rows(resolved):
            if document["instrument_id"] == instrument_id:
                return {
                    **document,
                    "schema": "market-matrix-row/v1",
                    "matrix_id": resolved,
                }
        raise LookupError(f"instrument is not present in matrix: {instrument_id}")

    def compare(
        self, matrix_id: str, instrument_ids: tuple[str, ...], fields: tuple[str, ...]
    ) -> dict[str, Any]:
        resolved = self.resolve_id(matrix_id)
        self._require_directory(self.objects)
        self._verify_object(self.objects / resolved, resolved)
        available_fields = {
            value["name"]
            for value in json.loads(
                (self.objects / resolved / "fields.json").read_text(encoding="utf-8")
            )
        }
        if len(fields) != len(set(fields)):
            raise ValueError("matrix compare fields must be unique")
        selected = tuple(sorted(fields or tuple(available_fields)))
        if unknown := set(selected) - available_fields:
            raise ValueError(f"unknown matrix fields: {sorted(unknown)}")
        rows = {value["instrument_id"]: value for value in self._rows(resolved)}
        missing_ids = [value for value in instrument_ids if value not in rows]
        if missing_ids:
            raise LookupError(f"instruments are not present in matrix: {missing_ids}")
        return {
            "schema": "market-matrix-comparison/v1",
            "matrix_id": resolved,
            "fields": list(selected),
            "rows": [
                {
                    "instrument_id": instrument_id,
                    "values": {
                        name: rows[instrument_id]["values"][name]
                        for name in selected
                        if name in rows[instrument_id]["values"]
                    },
                    "missing": {
                        name: rows[instrument_id]["missing"].get(name)
                        for name in selected
                        if name in rows[instrument_id]["missing"]
                    },
                }
                for instrument_id in instrument_ids
            ],
        }

    def _rows(self, matrix_id: str) -> Iterable[dict[str, Any]]:
        path = self.objects / matrix_id / "securities.jsonl"
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                yield json.loads(line)

    @staticmethod
    def _verify_object(path: Path, matrix_id: str) -> None:
        if path.is_symlink() or not path.is_dir() or path.name != matrix_id:
            raise LookupError(f"market matrix does not exist: {matrix_id}")
        required = {
            "manifest.json",
            "fields.json",
            "securities.jsonl",
            "index-summary.json",
            "failures.jsonl",
            "matrix.csv",
            "overview.html",
            "analysis.md",
        }
        artifacts = {value.name: value for value in path.iterdir()}
        if not required.issubset(artifacts) or any(
            artifacts[name].is_symlink() or not artifacts[name].is_file() for name in required
        ):
            raise ValueError("market matrix object is incomplete")
        manifest = MatrixStore._read_json(path / "manifest.json")
        if (
            manifest.get("matrix_id") != matrix_id
            or manifest.get("schema") != "market-matrix-manifest/v1"
        ):
            raise ValueError("market matrix manifest identity is invalid")
        fields = MatrixStore._read_json(path / "fields.json")
        summary = MatrixStore._read_json(path / "index-summary.json")
        rows = tuple(MatrixStore._read_jsonl(path / "securities.jsonl"))
        failures = tuple(MatrixStore._read_jsonl(path / "failures.jsonl"))
        semantic = {
            **{key: value for key, value in manifest.items() if key not in {"schema", "matrix_id"}},
            "field_definitions": fields,
            "row_hashes": [hashlib.sha256(_json_bytes(row)).hexdigest() for row in rows],
            "summary": summary,
            "failures": failures,
        }
        if hashlib.sha256(_json_bytes(semantic)).hexdigest() != matrix_id:
            raise ValueError("market matrix content identity is invalid")
        if (path / "analysis.md").read_text(encoding="utf-8") != MatrixStore._analysis_markdown(
            manifest, summary
        ):
            raise ValueError("market matrix analysis projection is invalid")
        field_values = tuple(MatrixField(**value) for value in fields)
        with tempfile.TemporaryDirectory(prefix="marketsieve-matrix-verify-") as directory:
            temporary = Path(directory)
            expected_csv = temporary / "matrix.csv"
            expected_html = temporary / "overview.html"
            MatrixStore._write_csv(expected_csv, field_values, rows)
            MatrixStore._write_html(expected_html, manifest, summary, field_values, rows)
            if (path / "matrix.csv").read_bytes() != expected_csv.read_bytes():
                raise ValueError("market matrix CSV projection is invalid")
            if (path / "overview.html").read_bytes() != expected_html.read_bytes():
                raise ValueError("market matrix HTML projection is invalid")

    @staticmethod
    def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
        for line in path.read_bytes().splitlines(keepends=True):
            try:
                document = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"market matrix JSONL is invalid: {path.name}") from error
            if not isinstance(document, dict) or line != _json_bytes(document):
                raise ValueError(f"market matrix JSONL is not canonical: {path.name}")
            yield document

    @staticmethod
    def _read_json(path: Path) -> Any:
        raw = path.read_bytes()
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"market matrix JSON is invalid: {path.name}") from error
        if raw != _json_bytes(document):
            raise ValueError(f"market matrix JSON is not canonical: {path.name}")
        return document

    def _ensure_directory(self, path: Path) -> None:
        current = self.root
        directories = [self.root.parent, self.root]
        for part in path.relative_to(self.root).parts:
            current /= part
            directories.append(current)
        if any(candidate.is_symlink() for candidate in directories):
            raise ValueError("matrix storage path must be a real directory")
        path.mkdir(parents=True, exist_ok=True)
        if any(not candidate.is_dir() for candidate in directories):
            raise ValueError("matrix storage path must be a real directory")

    def _require_directory(self, path: Path) -> None:
        current = self.root
        directories = [self.root.parent, self.root]
        for part in path.relative_to(self.root).parts:
            current /= part
            directories.append(current)
        if any(candidate.is_symlink() or not candidate.is_dir() for candidate in directories):
            raise LookupError("matrix storage directory does not exist")
