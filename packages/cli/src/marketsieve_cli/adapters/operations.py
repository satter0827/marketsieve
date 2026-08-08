"""Persistent structured operation history for user-triggered generation."""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import secrets
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _uuid7() -> str:
    timestamp = int(time.time_ns() // 1_000_000) & ((1 << 48) - 1)
    randomness = secrets.randbits(74)
    value = (timestamp << 80) | (0x7 << 76) | ((randomness >> 62) << 64)
    value |= (0b10 << 62) | (randomness & ((1 << 62) - 1))
    hexadecimal = f"{value:032x}"
    return "-".join(
        (
            hexadecimal[:8],
            hexadecimal[8:12],
            hexadecimal[12:16],
            hexadecimal[16:20],
            hexadecimal[20:],
        )
    )


class OperationRunStore:
    def __init__(self, state_root: Path) -> None:
        self.root = state_root / "operations" / "runs"

    @contextmanager
    def track(self, command: str, inputs: dict[str, Any]) -> Iterator[dict[str, Any]]:
        run_id = _uuid7()
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=False)
        started = datetime.now(UTC)
        fingerprint = hashlib.sha256(_json_bytes(inputs)).hexdigest()
        run: dict[str, Any] = {
            "schema": "operation-run/v1",
            "run_id": run_id,
            "command": command,
            "input_fingerprint": fingerprint,
            "started_at": started.isoformat(),
            "ended_at": None,
            "status": "running",
            "exit_code": None,
            "attempt": 1,
            "resumable": False,
            "published_object_ids": [],
            "acquired_count": None,
            "coverage": None,
            "duration_seconds": None,
        }
        self._write(path / "run.json", run)
        self._event(path, "INFO", "operation_started", {"command": command})
        context: dict[str, Any] = {
            "run_id": run_id,
            "published_object_ids": [],
            "metrics": {},
        }
        try:
            yield context
        except BaseException as error:
            ended = datetime.now(UTC)
            run.update(
                ended_at=ended.isoformat(),
                status="failed",
                exit_code=1,
                duration_seconds=str((ended - started).total_seconds()),
            )
            self._event(
                path,
                "ERROR",
                "operation_failed",
                {"error_type": type(error).__name__, "message": str(error)},
            )
            self._write_failure(path, command, error)
            self._write(path / "run.json", run)
            raise
        else:
            ended = datetime.now(UTC)
            metrics = context["metrics"]
            run.update(
                ended_at=ended.isoformat(),
                status="completed",
                exit_code=0,
                published_object_ids=list(context["published_object_ids"]),
                acquired_count=metrics.get("acquired_count"),
                coverage=metrics.get("coverage"),
                duration_seconds=str((ended - started).total_seconds()),
            )
            self._event(
                path,
                "INFO",
                "operation_completed",
                {"published_object_ids": run["published_object_ids"]},
            )
            self._write(path / "run.json", run)

    def list(self, *, status: str | None = None, command: str | None = None) -> dict[str, Any]:
        runs: builtins.list[dict[str, Any]] = []
        if self.root.is_dir() and not self.root.is_symlink():
            for path in self.root.iterdir():
                if path.name.startswith(".") or not path.is_dir() or path.is_symlink():
                    continue
                try:
                    item = self._read(path / "run.json")
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    continue
                if status is not None and item.get("status") != status:
                    continue
                if command is not None and item.get("command") != command:
                    continue
                runs.append(item)
        runs.sort(key=lambda item: (item["started_at"], item["run_id"]), reverse=True)
        return {"schema": "operation-run-list/v1", "runs": runs}

    def show(self, run_id: str) -> dict[str, Any]:
        return self._read(self._path(run_id) / "run.json")

    def events(self, run_id: str, *, level: str | None = None) -> dict[str, Any]:
        items = self._read_jsonl(self._path(run_id) / "events.jsonl")
        if level is not None:
            items = [item for item in items if item["level"] == level]
        return {"schema": "operation-events/v1", "run_id": run_id, "events": items}

    def prune(
        self,
        run_ids: tuple[str, ...] = (),
        *,
        before: date | None = None,
        status: str | None = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        selected = []
        for item in self.list(status=status)["runs"]:
            if run_ids and item["run_id"] not in run_ids:
                continue
            if before is not None and datetime.fromisoformat(item["started_at"]).date() >= before:
                continue
            selected.append(item["run_id"])
        if apply:
            for run_id in selected:
                shutil.rmtree(self._path(run_id))
        return {
            "schema": "operation-prune/v1",
            "dry_run": not apply,
            "run_ids": selected,
            "count": len(selected),
        }

    def _path(self, run_id: str) -> Path:
        if len(run_id) != 36 or any(character not in "0123456789abcdef-" for character in run_id):
            raise LookupError(f"operation run does not exist: {run_id}")
        path = self.root / run_id
        if path.is_symlink() or not path.is_dir():
            raise LookupError(f"operation run does not exist: {run_id}")
        return path

    @staticmethod
    def _write(path: Path, value: object) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_bytes(_json_bytes(value))
        temporary.replace(path)

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict) or raw != _json_bytes(value):
            raise ValueError("operation document is invalid")
        return value

    @staticmethod
    def _read_jsonl(path: Path) -> builtins.list[dict[str, Any]]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def _event(self, path: Path, level: str, code: str, details: dict[str, Any]) -> None:
        document = {
            "schema": "operation-event/v1",
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "code": code,
            "details": details,
        }
        with (path / "events.jsonl").open("ab") as stream:
            stream.write(_json_bytes(document))

    def _write_failure(self, path: Path, command: str, error: BaseException) -> None:
        document = {
            "schema": "operation-failure/v1",
            "command": command,
            "reason": type(error).__name__,
            "message": str(error),
        }
        with (path / "failures.jsonl").open("ab") as stream:
            stream.write(_json_bytes(document))
