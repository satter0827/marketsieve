import io
import tarfile
import zipfile
from pathlib import Path

import pytest
from scripts.secret_gate import _scan_added_lines, scan_history, scan_paths


def write(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def test_secret_scan_accepts_empty_documented_environment(tmp_path: Path) -> None:
    path = write(tmp_path / ".env.example", "OPENAI_API_KEY=\n")

    assert scan_paths((path,)) == []


def test_secret_scan_reports_location_without_value(tmp_path: Path) -> None:
    value = "sk-" + "A" * 24
    path = write(tmp_path / "settings.txt", f"OPENAI_API_KEY={value}\n")

    findings = scan_paths((path,))

    assert {finding.kind for finding in findings} == {"credential_assignment", "openai_key"}
    assert all(value not in repr(finding) for finding in findings)


def test_secret_scan_reads_utf16_configuration(tmp_path: Path) -> None:
    key = "JQUANTS" + "_API_KEY"
    path = tmp_path / "settings.txt"
    path.write_text(f"{key}=opaque-production-credential\n", encoding="utf-16")

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]


def test_secret_scan_fails_closed_for_oversized_content(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    path.write_bytes(b"x" * (5 * 1024 * 1024 + 1))

    assert [finding.kind for finding in scan_paths((path,))] == ["unscannable_content"]


@pytest.mark.parametrize(
    "document",
    (
        "export {key}={value}\n",
        "{key}: {value}\n",
        '{{"{key}": "{value}"}}\n',
    ),
)
def test_secret_scan_recognizes_common_assignments(tmp_path: Path, document: str) -> None:
    value = "opaque-production-credential"
    key = "JQUANTS" + "_API_KEY"
    path = write(tmp_path / "settings.txt", document.format(key=key, value=value))

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]


@pytest.mark.parametrize(
    "reference",
    (
        'os.environ["OPENAI_API_KEY"]',
        "config.api_key",
        "${OPENAI_API_KEY}",
    ),
)
def test_secret_scan_accepts_credential_references(tmp_path: Path, reference: str) -> None:
    key = "OPENAI" + "_API_KEY"
    path = write(tmp_path / "settings.txt", f"{key}={reference}\n")

    assert scan_paths((path,)) == []


def test_secret_scan_rejects_sensitive_tracked_path(tmp_path: Path) -> None:
    path = write(tmp_path / ".env", "SAFE=placeholder\n")

    assert [finding.kind for finding in scan_paths((path,))] == ["sensitive_path"]


def test_secret_scan_rejects_case_variant_sensitive_directory(tmp_path: Path) -> None:
    directory = tmp_path / "Credentials"
    directory.mkdir()
    path = write(directory / "token.bin", "opaque\n")

    assert [finding.kind for finding in scan_paths((path,))] == ["sensitive_path"]


@pytest.mark.parametrize("name", ("client.p12", "client.pfx", "client.pem", "client.key"))
def test_secret_scan_rejects_binary_credential_paths(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"\0opaque-binary-content")

    assert [finding.kind for finding in scan_paths((path,))] == ["sensitive_path"]


@pytest.mark.parametrize("kind", ("DSA ", "ENCRYPTED "))
def test_secret_scan_recognizes_private_key_header(tmp_path: Path, kind: str) -> None:
    header = "-----BEGIN " + kind + "PRIVATE KEY-----\n"
    path = write(tmp_path / "settings.txt", header)

    assert [finding.kind for finding in scan_paths((path,))] == ["private_key"]


def test_patch_scan_ignores_removed_credentials() -> None:
    value = "sk-" + "A" * 24
    patch = f"--- a/settings\n+++ b/settings\n-{value}\n+safe\n".encode()

    assert _scan_added_lines("change", patch) == []


def test_history_scan_checks_each_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    value = "sk-" + "A" * 24
    responses = iter(
        (
            b"first\nsecond\n",
            f"+OPENAI_API_KEY={value}\n".encode(),
            b"",
            b"-OPENAI_API_KEY=removed\n",
            b"",
        )
    )
    monkeypatch.setattr("scripts.secret_gate._capture", lambda _command: next(responses))

    findings = scan_history("base")

    assert [(finding.path, finding.kind) for finding in findings] == [
        ("git-commit:first", "credential_assignment"),
        ("git-commit:first", "openai_key"),
    ]


def test_history_scan_reads_archive_before_later_removal(monkeypatch: pytest.MonkeyPatch) -> None:
    value = "opaque-production-credential"
    archive_path = Path("nested/artifact.whl")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("package/settings.txt", f"JQUANTS_API_KEY={value}\n")
    responses = iter(
        (
            b"first\nsecond\n",
            b"Binary files differ\n",
            f"{archive_path}\0".encode(),
            buffer.getvalue(),
            b"Binary files differ\n",
            b"",
        )
    )
    commands: list[tuple[str, ...]] = []

    def capture(command: tuple[str, ...]) -> bytes:
        commands.append(command)
        return next(responses)

    monkeypatch.setattr("scripts.secret_gate._capture", capture)

    findings = scan_history("base")

    assert [finding.kind for finding in findings] == ["credential_assignment"]
    assert any("-r" in command for command in commands if "--name-only" in command)


def test_secret_scan_reads_wheel_members(tmp_path: Path) -> None:
    value = "opaque-production-credential"
    path = tmp_path / "artifact.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("package/settings.txt", f"JQUANTS_API_KEY={value}\n")

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]


def test_secret_scan_rejects_sensitive_wheel_member(tmp_path: Path) -> None:
    path = tmp_path / "artifact.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("package/client.p12", b"\0opaque-binary-content")

    assert [finding.kind for finding in scan_paths((path,))] == ["sensitive_path"]


def test_secret_scan_reads_nested_archive(tmp_path: Path) -> None:
    value = "opaque-production-credential"
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("package/settings.txt", f"JQUANTS_API_KEY={value}\n")
    path = tmp_path / "wheelhouse.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("artifact.whl", nested.getvalue())

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]


def test_secret_scan_reads_sdist_members(tmp_path: Path) -> None:
    value = "opaque-production-credential"
    settings = write(tmp_path / "settings.txt", f"JQUANTS_API_KEY={value}\n")
    path = tmp_path / "artifact.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        archive.add(settings, arcname="package/settings.txt")

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]
