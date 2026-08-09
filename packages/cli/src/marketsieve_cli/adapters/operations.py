"""Persistent, typed operation history for user-triggered acquisition."""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import secrets
import shutil
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any

from marketsieve_extension_api import (
    AcquisitionProgress,
    AcquisitionProgressState,
)

HEARTBEAT_INTERVAL_SECONDS = 15.0
RETRY_EVENT_INTERVAL_SECONDS = 15.0
OperationObserver = Callable[[str, AcquisitionProgress, float], None]


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


def _progress_document(progress: AcquisitionProgress) -> dict[str, Any]:
    document: dict[str, Any] = {
        "phase": progress.phase,
        "state": progress.state.value,
        "completed": progress.completed,
        "total": progress.total,
        "failure_count": progress.failure_count,
    }
    if progress.state is AcquisitionProgressState.RETRYING:
        document.update(
            attempt=progress.attempt,
            max_attempts=progress.max_attempts,
            retry_after_seconds=progress.retry_after_seconds,
        )
    return document


class OperationContext:
    """Own one run's progress, publications, metrics, and heartbeat."""

    def __init__(
        self,
        store: OperationRunStore,
        path: Path,
        run: dict[str, Any],
        started_at: datetime,
        observer: OperationObserver | None,
    ) -> None:
        self._store = store
        self._path = path
        self._run = run
        self._started_at = started_at
        self._started_monotonic = time.monotonic()
        self._last_event_monotonic = self._started_monotonic
        self._observer = observer
        self._lock = RLock()
        self._stop = Event()
        self._heartbeat = Thread(
            target=self._heartbeat_loop,
            name=f"marketsieve-operation-{run['run_id']}",
            daemon=True,
        )
        self._progress_by_phase: dict[str, AcquisitionProgress] = {}
        self._last_retry_event_by_phase: dict[str, float] = {}
        self._current_progress: AcquisitionProgress | None = None
        self._published_object_ids: list[str] = []
        self._acquired_count: int | None = None
        self._coverage: dict[str, Any] | None = None

    @property
    def run_id(self) -> str:
        return str(self._run["run_id"])

    @property
    def published_object_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._published_object_ids)

    def start(self) -> None:
        self._heartbeat.start()

    def stop(self) -> None:
        self._stop.set()
        self._heartbeat.join(timeout=self._store.heartbeat_interval_seconds + 1.0)

    def __call__(self, progress: AcquisitionProgress, /) -> None:
        with self._lock:
            previous = self._progress_by_phase.get(progress.phase)
            if previous is not None and (
                progress.total != previous.total
                or progress.completed < previous.completed
                or progress.failure_count < previous.failure_count
            ):
                raise ValueError("operation progress must be monotonic within a phase")
            self._progress_by_phase[progress.phase] = progress
            self._current_progress = progress
            code = "retry" if progress.state is AcquisitionProgressState.RETRYING else "progress"
            self._run["current_progress"] = _progress_document(progress)
            if code == "retry":
                now = time.monotonic()
                last_retry = self._last_retry_event_by_phase.get(progress.phase)
                if (
                    last_retry is not None
                    and now - last_retry < self._store.retry_event_interval_seconds
                ):
                    return
                self._last_retry_event_by_phase[progress.phase] = now
            self._record(code, {"progress": self._run["current_progress"]})
            self._write_run()
            self._observe(code, progress)

    def publish(self, object_id: str) -> None:
        if not isinstance(object_id, str) or not object_id:
            raise ValueError("published object ID must not be empty")
        with self._lock:
            if object_id in self._published_object_ids:
                return
            self._published_object_ids.append(object_id)
            self._run["published_object_ids"] = list(self._published_object_ids)
            self._record("published", {"object_id": object_id})
            self._write_run()

    def set_metrics(self, *, acquired_count: int | None, coverage: dict[str, Any] | None) -> None:
        if acquired_count is not None and (
            not isinstance(acquired_count, int)
            or isinstance(acquired_count, bool)
            or acquired_count < 0
        ):
            raise ValueError("acquired count must be a non-negative integer")
        if coverage is not None and not isinstance(coverage, dict):
            raise TypeError("coverage must be an object")
        with self._lock:
            self._acquired_count = acquired_count
            self._coverage = coverage

    def finish(self, error: BaseException | None) -> None:
        self.stop()
        with self._lock:
            ended = datetime.now(UTC)
            if error is None:
                status = "completed"
                exit_code = 0
                code = "completed"
            elif isinstance(error, KeyboardInterrupt):
                status = "cancelled"
                exit_code = 130
                code = "cancelled"
            else:
                status = "failed"
                exit_code = int(getattr(error, "exit_code", 1))
                code = "failed"
            resume_run_id = None if error is None else getattr(error, "resume_run_id", None)
            resume_command = None if error is None else getattr(error, "resume_command", None)
            resumable = (
                isinstance(resume_run_id, str)
                and len(resume_run_id) == 16
                and all(character in "0123456789abcdef" for character in resume_run_id)
            )
            self._run.update(
                updated_at=ended.isoformat(),
                ended_at=ended.isoformat(),
                status=status,
                exit_code=exit_code,
                resumable=resumable,
                published_object_ids=list(self._published_object_ids),
                acquired_count=self._acquired_count,
                coverage=self._coverage,
                duration_seconds=str((ended - self._started_at).total_seconds()),
            )
            if resumable:
                self._run["resume_run_id"] = resume_run_id
                if isinstance(resume_command, str) and resume_command:
                    self._run["resume_command"] = resume_command
            details: dict[str, Any] = {
                "exit_code": exit_code,
                "published_object_ids": list(self._published_object_ids),
            }
            if error is not None:
                details.update(error_type=type(error).__name__, message=str(error))
                self._store._write_failure(self._path, str(self._run["command"]), error)
            self._record(code, details)
            self._write_run()

    def _heartbeat_loop(self) -> None:
        interval = self._store.heartbeat_interval_seconds
        while not self._stop.wait(interval):
            with self._lock:
                progress = self._current_progress
                if progress is None or time.monotonic() - self._last_event_monotonic < interval:
                    continue
                self._record("heartbeat", {"progress": _progress_document(progress)})
                self._write_run()
                self._observe("heartbeat", progress)

    def _record(self, code: str, details: dict[str, Any]) -> None:
        now = datetime.now(UTC)
        self._run["updated_at"] = now.isoformat()
        self._last_event_monotonic = time.monotonic()
        self._store._event(self._path, now, code, details)

    def _write_run(self) -> None:
        self._store._write(self._path / "run.json", self._run)

    def _observe(self, code: str, progress: AcquisitionProgress) -> None:
        if self._observer is None:
            return
        try:
            self._observer(code, progress, time.monotonic() - self._started_monotonic)
        except Exception:
            return


class OperationRunStore:
    def __init__(
        self,
        state_root: Path,
        *,
        heartbeat_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
        retry_event_interval_seconds: float = RETRY_EVENT_INTERVAL_SECONDS,
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        if retry_event_interval_seconds <= 0:
            raise ValueError("retry event interval must be positive")
        self.root = state_root / "operations" / "runs"
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.retry_event_interval_seconds = retry_event_interval_seconds

    @contextmanager
    def track(
        self,
        command: str,
        inputs: dict[str, Any],
        *,
        observer: OperationObserver | None = None,
    ) -> Iterator[OperationContext]:
        run_id = _uuid7()
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=False)
        started = datetime.now(UTC)
        run: dict[str, Any] = {
            "schema": "operation-run/v2",
            "run_id": run_id,
            "command": command,
            "input_fingerprint": hashlib.sha256(_json_bytes(inputs)).hexdigest(),
            "started_at": started.isoformat(),
            "updated_at": started.isoformat(),
            "ended_at": None,
            "status": "running",
            "exit_code": None,
            "attempt": 1,
            "resumable": False,
            "published_object_ids": [],
            "current_progress": None,
            "acquired_count": None,
            "coverage": None,
            "duration_seconds": None,
        }
        self._write(path / "run.json", run)
        self._event(path, started, "started", {"command": command})
        context = OperationContext(self, path, run, started, observer)
        context.start()
        error: BaseException | None = None
        try:
            yield context
        except BaseException as caught:
            error = caught
            raise
        finally:
            context.finish(error)

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
                if item.get("schema") != "operation-run/v2":
                    continue
                if status is not None and item.get("status") != status:
                    continue
                if command is not None and item.get("command") != command:
                    continue
                runs.append(item)
        runs.sort(key=lambda item: (item["started_at"], item["run_id"]), reverse=True)
        return {"schema": "operation-run-list/v2", "runs": runs}

    def show(self, run_id: str) -> dict[str, Any]:
        return self._read(self._path(run_id) / "run.json")

    def events(self, run_id: str, *, level: str | None = None) -> dict[str, Any]:
        items = self._read_jsonl(self._path(run_id) / "events.jsonl")
        if level is not None:
            items = [item for item in items if item["level"] == level]
        return {"schema": "operation-events/v2", "run_id": run_id, "events": items}

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

    @staticmethod
    def _event(path: Path, timestamp: datetime, code: str, details: dict[str, Any]) -> None:
        level = "ERROR" if code in {"failed", "cancelled"} else "INFO"
        document = {
            "schema": "operation-event/v2",
            "timestamp": timestamp.isoformat(),
            "level": level,
            "code": code,
            "details": details,
        }
        with (path / "events.jsonl").open("ab") as stream:
            stream.write(_json_bytes(document))

    @staticmethod
    def _write_failure(path: Path, command: str, error: BaseException) -> None:
        document = {
            "schema": "operation-failure/v1",
            "command": command,
            "reason": type(error).__name__,
            "message": str(error),
        }
        with (path / "failures.jsonl").open("ab") as stream:
            stream.write(_json_bytes(document))
