"""Reject credentials from tracked files, diffs, and generated evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import re
import subprocess
import tarfile
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parents[1]
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_DEPTH = 3
SENSITIVE_NAMES = re.compile(
    r"(?:^|/)(?:\.env(?:\..+)?|(?:credentials?|secrets?)(?:\.[^/]+)?)(?:$|/)",
    re.IGNORECASE,
)
SENSITIVE_SUFFIXES = (".key", ".p12", ".pem", ".pfx", ".private-key")
ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".whl", ".zip")
PERMITTED_NAMES = {".env.example"}
PLACEHOLDERS = {"", "example", "placeholder", "replace-me", "set-me"}
TEMPLATE_PLACEHOLDER = re.compile(r"^(?:\{[^{}]+}|<[^<>]+>)$")
REFERENCE_VALUE = re.compile(
    r"^(?:"
    r"\$\{?[A-Z0-9_]+}?|%[A-Z0-9_]+%|"
    r"(?:os\.)?(?:environ(?:\[[^]]+]|\.get\([^)]*\))|getenv\([^)]*\))|"
    r"(?:config|settings|secret|secrets)\.[A-Z_][A-Z0-9_.]*|"
    r"[A-Z_][A-Z0-9_]*\[[^]]+])$",
    re.IGNORECASE,
)
URL_CREDENTIAL = re.compile(
    r"(?i)[?&](?:api_?key|access_token|auth_token|client_secret|password)="
    r"([^&#\s\"']+)"
)
URL_USERINFO_CREDENTIAL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^/@\s:\"']+:([^/@\s\"']+)@")


def _joined(*parts: str) -> str:
    return "".join(parts)


PATTERNS = (
    (
        "private_key",
        re.compile(
            _joined("-----BEGIN ", "(?:DSA |ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----")
        ),
    ),
    ("openai_key", re.compile(_joined(r"\bsk-", r"[A-Za-z0-9_-]{20,}\b"))),
    ("google_key", re.compile(_joined(r"\bAIza", r"[A-Za-z0-9_-]{30,}\b"))),
    ("github_token", re.compile(_joined(r"\b(?:ghp_|github_pat_)", r"[A-Za-z0-9_]{20,}\b"))),
    ("aws_access_key", re.compile(_joined(r"\bAKIA", r"[A-Z0-9]{16}\b"))),
    ("slack_token", re.compile(_joined(r"\bxox[baprs]-", r"[A-Za-z0-9-]{20,}\b"))),
)
HEADER_CREDENTIALS = (
    (
        "bearer_token",
        re.compile(
            r"(?i)(?:\[\s*)?[\"']?authorization[\"']?(?:\s*\])?\s*[:=]\s*"
            r"[\"']?bearer\s+"
            r"([^\s\"']+)"
        ),
    ),
    (
        "basic_auth",
        re.compile(
            r"(?i)(?:\[\s*)?[\"']?authorization[\"']?(?:\s*\])?\s*[:=]\s*"
            r"[\"']?basic\s+"
            r"([^\s\"']+)"
        ),
    ),
    (
        "api_key_header",
        re.compile(
            r"(?i)(?:\[\s*)?[\"']?(?:x-)?api-key[\"']?(?:\s*\])?\s*:\s*[\"']?"
            r"([^\s\"']+)"
        ),
    ),
)
ASSIGNMENT = re.compile(
    r"(?i)(?:^|[{,]\s*)\s*(?:export\s+)?[\"']?"
    r"([A-Z0-9_.-]*(?:API[-_]?KEY|ACCESS[-_]?KEY|SECRET[-_]?KEY|PRIVATE[-_]?KEY|"
    r"ACCESS[-_]?TOKEN|AUTH[-_]?TOKEN|REFRESH[-_]?TOKEN|TOKEN|CLIENT[-_]?SECRET|"
    r"SECRET|PASSWORD))[\"']?"
    r"\s*(?:=|:)\s*(\"[^\"\n]*\"|'[^'\n]*'|[^,}\s]+)"
)
CREDENTIAL_NAME = re.compile(
    r"(?i)(?:^|[_.-])(?:API[-_]?KEY|ACCESS[-_]?KEY|SECRET[-_]?KEY|PRIVATE[-_]?KEY|"
    r"ACCESS[-_]?TOKEN|AUTH[-_]?TOKEN|REFRESH[-_]?TOKEN|TOKEN|CLIENT[-_]?SECRET|"
    r"SECRET|PASSWORD)$"
)


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    kind: str


def _hashed_label(label: str) -> str:
    digest = hashlib.sha256(label.encode("utf-8", errors="replace")).hexdigest()
    return f"path-sha256:{digest}"


def _credential_path_finding(label: str) -> Finding | None:
    if _scan_text("path-name", label, scan_assignments=True):
        return Finding(_hashed_label(label), 0, "credential_path")
    return None


def _capture(command: Sequence[str]) -> bytes:
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True).stdout


def _tracked_paths() -> tuple[Path, ...]:
    values = _capture(("git", "ls-files", "-z")).split(b"\0")
    return tuple(ROOT / value.decode() for value in values if value)


def _artifact_paths(roots: Iterable[Path]) -> tuple[Path, ...]:
    return tuple(
        path
        for root in roots
        if root.exists()
        for path in (root.rglob("*") if root.is_dir() else (root,))
        if path.is_file()
    )


def _decode_text(payload: bytes) -> str | None:
    if len(payload) > MAX_TEXT_BYTES:
        return None
    if b"\0" in payload:
        if not payload.startswith((b"\xff\xfe", b"\xfe\xff")):
            return None
        try:
            return payload.decode("utf-16")
        except UnicodeDecodeError:
            return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _read_text(path: Path) -> str | None:
    try:
        return _decode_text(path.read_bytes())
    except OSError:
        return None


def _is_literal_credential(value: str) -> bool:
    raw = value.strip()
    quoted = len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]
    normalized = raw[1:-1] if quoted else raw
    dynamic = not quoted and (
        normalized in {"None", "True", "False"}
        or ("(" in normalized and ")" in normalized)
        or ("[" in normalized and "]" in normalized)
        or re.match(r"(?i)^[fbru]+[\"']", normalized) is not None
    )
    return (
        not dynamic
        and normalized.lower() not in PLACEHOLDERS
        and TEMPLATE_PLACEHOLDER.fullmatch(normalized) is None
        and REFERENCE_VALUE.fullmatch(normalized) is None
    )


def _python_label(label: str) -> bool:
    return label.rsplit("!", maxsplit=1)[-1].rsplit(":", maxsplit=1)[-1].endswith(".py")


def _python_target_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _python_literal(node.slice)
    return None


def _python_literal(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bytes):
            return node.value.decode("utf-8", errors="replace")
    return None


def _scan_python_assignments(label: str, text: str) -> list[Finding]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [Finding(label, 0, "unscannable_content")]
    findings: list[Finding] = []
    for node in ast.walk(tree):
        targets: tuple[ast.expr, ...] = ()
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
            value = node.value
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            targets = (node.target,)
            value = node.value
        literal = _python_literal(value)
        if (
            literal is not None
            and any(
                (name := _python_target_name(target)) is not None
                and CREDENTIAL_NAME.search(name) is not None
                for target in targets
            )
            and _is_literal_credential(f'"{literal}"')
        ):
            findings.append(Finding(label, getattr(node, "lineno", 0), "credential_assignment"))
        if isinstance(node, ast.Dict):
            for key, item in zip(node.keys, node.values, strict=True):
                key_literal = _python_literal(key)
                item_literal = _python_literal(item)
                if (
                    key_literal is not None
                    and CREDENTIAL_NAME.search(key_literal) is not None
                    and item_literal is not None
                    and _is_literal_credential(f'"{item_literal}"')
                ):
                    findings.append(Finding(label, node.lineno, "credential_assignment"))
        if isinstance(node, ast.keyword) and node.arg is not None:
            keyword_literal = _python_literal(node.value)
            if (
                CREDENTIAL_NAME.search(node.arg) is not None
                and keyword_literal is not None
                and _is_literal_credential(f'"{keyword_literal}"')
            ):
                findings.append(Finding(label, node.value.lineno, "credential_assignment"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            environment_call = (
                node.func.attr == "setdefault"
                and isinstance(owner, ast.Attribute)
                and owner.attr == "environ"
            ) or (node.func.attr == "putenv" and isinstance(owner, ast.Name) and owner.id == "os")
            if environment_call and len(node.args) >= 2:
                key_literal = _python_literal(node.args[0])
                value_literal = _python_literal(node.args[1])
                if (
                    key_literal is not None
                    and CREDENTIAL_NAME.search(key_literal) is not None
                    and value_literal is not None
                    and _is_literal_credential(f'"{value_literal}"')
                ):
                    findings.append(Finding(label, node.lineno, "credential_assignment"))
    return findings


def _scan_text(label: str, text: str, *, scan_assignments: bool = True) -> list[Finding]:
    findings: list[Finding] = []
    python_source = scan_assignments and _python_label(label)
    if python_source:
        findings.extend(_scan_python_assignments(label, text))
    for line_number, line in enumerate(text.splitlines(), start=1):
        if scan_assignments and not python_source:
            for assignment in ASSIGNMENT.finditer(line):
                if _is_literal_credential(assignment.group(2)):
                    findings.append(Finding(label, line_number, "credential_assignment"))
        for match in (*URL_CREDENTIAL.finditer(line), *URL_USERINFO_CREDENTIAL.finditer(line)):
            if _is_literal_credential(match.group(1)):
                findings.append(Finding(label, line_number, "url_credential"))
        for kind, pattern in HEADER_CREDENTIALS:
            for match in pattern.finditer(line):
                if _is_literal_credential(match.group(1)):
                    findings.append(Finding(label, line_number, kind))
        for kind, pattern in PATTERNS:
            if pattern.search(line):
                findings.append(Finding(label, line_number, kind))
    return findings


def _is_archive(label: str) -> bool:
    return label.lower().endswith(ARCHIVE_SUFFIXES)


def _is_sensitive_path(label: str, name: str) -> bool:
    return name not in PERMITTED_NAMES and (
        SENSITIVE_NAMES.search(label) is not None or name.lower().endswith(SENSITIVE_SUFFIXES)
    )


def _scan_archive_payload(payload: bytes, label: str, *, depth: int = 0) -> list[Finding]:
    findings: list[Finding] = []
    stream = io.BytesIO(payload)
    try:
        if zipfile.is_zipfile(stream):
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                for zip_member in archive.infolist():
                    if zip_member.is_dir():
                        continue
                    member_label = f"{label}!{zip_member.filename}"
                    member_name = zip_member.filename.rsplit("/", maxsplit=1)[-1]
                    if (path_finding := _credential_path_finding(member_label)) is not None:
                        findings.append(path_finding)
                    if _is_sensitive_path(zip_member.filename, member_name):
                        findings.append(Finding(_hashed_label(member_label), 0, "sensitive_path"))
                    if zip_member.file_size > MAX_TEXT_BYTES:
                        findings.append(Finding(member_label, 0, "unscannable_content"))
                        continue
                    member_payload = archive.read(zip_member)
                    text = _decode_text(member_payload)
                    if text is not None:
                        findings.extend(_scan_text(member_label, text))
                    nested_archive = _is_archive(zip_member.filename)
                    if (
                        text is None
                        and not nested_archive
                        and not _is_sensitive_path(zip_member.filename, member_name)
                    ):
                        findings.append(Finding(member_label, 0, "unscannable_content"))
                    if depth < MAX_ARCHIVE_DEPTH and nested_archive:
                        findings.extend(
                            _scan_archive_payload(member_payload, member_label, depth=depth + 1)
                        )
                    elif nested_archive:
                        findings.append(Finding(member_label, 0, "unscannable_content"))
        else:
            stream.seek(0)
            with tarfile.open(fileobj=stream, mode="r:*") as archive:
                for tar_member in archive.getmembers():
                    if not tar_member.isfile():
                        continue
                    member_label = f"{label}!{tar_member.name}"
                    member_name = tar_member.name.rsplit("/", maxsplit=1)[-1]
                    if (path_finding := _credential_path_finding(member_label)) is not None:
                        findings.append(path_finding)
                    if _is_sensitive_path(tar_member.name, member_name):
                        findings.append(Finding(_hashed_label(member_label), 0, "sensitive_path"))
                    if tar_member.size > MAX_TEXT_BYTES:
                        findings.append(Finding(member_label, 0, "unscannable_content"))
                        continue
                    handle = archive.extractfile(tar_member)
                    member_payload = handle.read() if handle is not None else b""
                    text = _decode_text(member_payload)
                    if text is not None:
                        findings.extend(_scan_text(member_label, text))
                    nested_archive = _is_archive(tar_member.name)
                    if (
                        text is None
                        and not nested_archive
                        and not _is_sensitive_path(tar_member.name, member_name)
                    ):
                        findings.append(Finding(member_label, 0, "unscannable_content"))
                    if depth < MAX_ARCHIVE_DEPTH and nested_archive:
                        findings.extend(
                            _scan_archive_payload(member_payload, member_label, depth=depth + 1)
                        )
                    elif nested_archive:
                        findings.append(Finding(member_label, 0, "unscannable_content"))
    except (OSError, tarfile.TarError, zipfile.BadZipFile):
        findings.append(Finding(label, 0, "unscannable_content"))
    return findings


def _scan_archive(path: Path, label: str) -> list[Finding]:
    if not _is_archive(label):
        return []
    try:
        return _scan_archive_payload(path.read_bytes(), label)
    except OSError:
        return [Finding(label, 0, "unscannable_content")]


def _scan_added_lines(label: str, patch: bytes) -> list[Finding]:
    additions = "\n".join(
        line[1:]
        for line in patch.decode("utf-8", errors="replace").splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    return _scan_text(label, additions, scan_assignments=False)


def scan_patch_text(label: str, text: str) -> list[Finding]:
    logical = "\n".join(
        line[1:] if line.startswith(("+", "-", " ")) else line for line in text.splitlines()
    )
    return _scan_text(label, logical)


def scan_paths(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in dict.fromkeys(paths):
        try:
            label = str(path.relative_to(ROOT))
        except ValueError:
            label = str(path)
        sensitive_path = _is_sensitive_path(label, path.name)
        archive_path = _is_archive(label)
        if (path_finding := _credential_path_finding(label)) is not None:
            findings.append(path_finding)
        if sensitive_path:
            findings.append(Finding(_hashed_label(label), 0, "sensitive_path"))
        findings.extend(_scan_archive(path, label))
        text = _read_text(path)
        if text is not None:
            findings.extend(_scan_text(label, text))
        elif not sensitive_path and not archive_path:
            findings.append(Finding(label, 0, "unscannable_content"))
    return findings


def scan_diff(base: str) -> list[Finding]:
    patch = _capture(("git", "diff", "--no-ext-diff", "--unified=0", base, "--"))
    return _scan_added_lines(f"git-diff:{base}", patch)


def scan_history(base: str) -> list[Finding]:
    commits = _capture(("git", "rev-list", "--reverse", f"{base}..HEAD")).splitlines()
    findings: list[Finding] = []
    for commit in commits:
        sha = commit.decode("ascii")
        message = _capture(("git", "log", "-1", "--format=%B", sha))
        message_text = _decode_text(message)
        if message_text is None:
            findings.append(Finding(f"git-message:{sha}", 0, "unscannable_content"))
        else:
            findings.extend(_scan_text(f"git-message:{sha}", message_text))
        patch = _capture(
            (
                "git",
                "diff-tree",
                "--root",
                "-m",
                "-p",
                "--no-commit-id",
                "--unified=0",
                sha,
                "--",
            )
        )
        findings.extend(_scan_added_lines(f"git-commit:{sha}", patch))
        paths = _capture(
            (
                "git",
                "diff-tree",
                "--root",
                "-m",
                "-r",
                "--no-commit-id",
                "--name-only",
                "--diff-filter=AM",
                "-z",
                sha,
                "--",
            )
        ).split(b"\0")
        for encoded_path in paths:
            if not encoded_path:
                continue
            changed_path = encoded_path.decode("utf-8", errors="replace")
            name = changed_path.rsplit("/", maxsplit=1)[-1]
            history_label = f"git-commit:{sha}:{changed_path}"
            if (path_finding := _credential_path_finding(history_label)) is not None:
                findings.append(path_finding)
            if _is_sensitive_path(changed_path, name):
                findings.append(Finding(_hashed_label(history_label), 0, "sensitive_path"))
            label = history_label
            payload = _capture(("git", "show", f"{sha}:{changed_path}"))
            if _is_archive(changed_path):
                findings.extend(_scan_archive_payload(payload, label))
            else:
                text = _decode_text(payload)
                if text is None:
                    if not _is_sensitive_path(changed_path, name):
                        findings.append(Finding(label, 0, "unscannable_content"))
                else:
                    findings.extend(_scan_text(label, text))
    return findings


def check(paths: tuple[Path, ...], base: str | None) -> None:
    findings = scan_paths((*_tracked_paths(), *_artifact_paths(paths)))
    if base is not None:
        findings.extend(scan_diff(base))
        findings.extend(scan_history(base))
    unique = sorted(set(findings), key=lambda item: (item.path, item.line, item.kind))
    if unique:
        for finding in unique:
            safe_path = (
                _hashed_label(finding.path)
                if _scan_text("path-name", finding.path)
                else finding.path
            )
            location = f"{safe_path}:{finding.line}" if finding.line else safe_path
            print(f"secret finding: {location} [{finding.kind}]")
        raise SystemExit(1)
    print("Secret scan passed without exposing file contents.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", action="append", default=[], type=Path)
    parser.add_argument("--base")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    check(tuple(args.path), args.base)


if __name__ == "__main__":
    main()
