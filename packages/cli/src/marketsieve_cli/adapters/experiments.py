"""Content-addressed experiment run storage."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from marketsieve import ExperimentRun
from marketsieve.analysis.indicators import canonical_decimal

EXPERIMENT_SCHEMA = "experiment-run/v1"
METRIC_UNITS = {
    "average_holding_period": "observations",
    "data_coverage": "ratio",
    "decision_change_count": "count",
    "decision_count": "count",
    "forward_return": "ratio",
    "maximum_drawdown": "ratio",
}


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def experiment_document(run: ExperimentRun) -> dict[str, Any]:
    return {
        "schema": EXPERIMENT_SCHEMA,
        "run_id": run.run_id,
        "spec_id": run.spec.spec_id,
        "profit_simulation": run.spec.is_profit_simulation,
        "spec": {
            "policy": {
                "name": run.spec.policy_name,
                "version": run.spec.policy_version,
                "settings": dict(run.spec.policy_settings),
            },
            "window": {
                "start": run.spec.window.start.isoformat(),
                "end": run.spec.window.end.isoformat(),
            },
            "datasets": dict(run.spec.datasets),
            "execution_costs": dict(run.spec.execution_costs),
        },
        "decisions": [
            {
                "instrument": f"{item.instrument.mic}:{item.instrument.symbol}",
                "as_of": item.as_of.isoformat(),
                "action": item.action.value,
                "confidence": item.confidence.value,
            }
            for item in run.decisions
        ],
        "metrics": {
            item.name: {"value": canonical_decimal(item.value), "unit": item.unit}
            for item in run.metrics
        },
    }


class ExperimentStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._objects = root / "objects"

    def put(self, run: ExperimentRun) -> dict[str, Any]:
        document = experiment_document(run)
        self._ensure_directory()
        destination = self._objects / f"{run.run_id}.json"
        payload = _json_bytes(document)
        if destination.exists():
            if (
                destination.is_symlink()
                or not destination.is_file()
                or destination.read_bytes() != payload
            ):
                raise ValueError("stored experiment conflicts with its run ID")
            return document
        descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=self._objects)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return document

    def show(self, run_id: str) -> dict[str, Any]:
        if len(run_id) != 64 or any(value not in "0123456789abcdef" for value in run_id):
            raise ValueError("run ID must be a lowercase SHA-256 digest")
        if self._root.is_symlink() or self._objects.is_symlink() or not self._objects.is_dir():
            raise LookupError("experiment storage directory does not exist")
        path = self._objects / f"{run_id}.json"
        if not path.is_file() or path.is_symlink():
            raise LookupError("experiment run not found")
        payload = path.read_bytes()
        try:
            document = cast(dict[str, Any], json.loads(payload))
            self._verify(document, run_id)
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("stored experiment is not canonical") from error
        if _json_bytes(document) != payload:
            raise ValueError("stored experiment is not canonical")
        return document

    def compare(self, left: str, right: str) -> dict[str, Any]:
        left_document, right_document = self.show(left), self.show(right)
        if left_document["metrics"].keys() != right_document["metrics"].keys():
            raise ValueError("experiment runs have incompatible metrics")
        deltas = {
            name: {
                "value": canonical_decimal(
                    Decimal(right_document["metrics"][name]["value"])
                    - Decimal(left_document["metrics"][name]["value"])
                ),
                "unit": left_document["metrics"][name]["unit"],
            }
            for name in sorted(left_document["metrics"])
        }
        return {
            "schema": "experiment-comparison/v1",
            "left_run_id": left,
            "right_run_id": right,
            "metric_deltas": deltas,
        }

    def _ensure_directory(self) -> None:
        if self._root.exists() and (self._root.is_symlink() or not self._root.is_dir()):
            raise ValueError("experiment root must be a real directory")
        self._root.mkdir(parents=True, exist_ok=True)
        if self._objects.exists() and (self._objects.is_symlink() or not self._objects.is_dir()):
            raise ValueError("experiment object path must be a real directory")
        self._objects.mkdir(exist_ok=True)

    @staticmethod
    def _verify(document: dict[str, Any], run_id: str) -> None:
        if (
            set(document)
            != {
                "schema",
                "run_id",
                "spec_id",
                "profit_simulation",
                "spec",
                "decisions",
                "metrics",
            }
            or document["schema"] != EXPERIMENT_SCHEMA
        ):
            raise ValueError("stored experiment shape is invalid")
        spec = document["spec"]
        if document["spec_id"] != _digest(spec):
            raise ValueError("stored experiment specification identity is invalid")
        metrics = document["metrics"]
        if set(metrics) != set(METRIC_UNITS) or any(
            set(value) != {"value", "unit"} or value["unit"] != METRIC_UNITS[name]
            for name, value in metrics.items()
        ):
            raise ValueError("stored experiment metrics are invalid")
        semantic = {
            "spec": spec,
            "decisions": document["decisions"],
            "metrics": {name: value["value"] for name, value in metrics.items()},
        }
        if document["run_id"] != run_id or _digest(semantic) != run_id:
            raise ValueError("stored experiment run identity is invalid")
        if document["profit_simulation"] is not bool(spec["execution_costs"]):
            raise ValueError("stored experiment profit classification is invalid")
