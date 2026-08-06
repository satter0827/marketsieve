import io
import tarfile
import zipfile
from pathlib import Path

import pytest
from scripts.secret_gate import (
    _credential_path_finding,
    _scan_added_lines,
    _tracked_paths,
    scan_history,
    scan_patch_text,
    scan_paths,
)


def write(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def test_tracked_paths_skip_files_deleted_in_the_worktree() -> None:
    assert all(path.is_file() for path in _tracked_paths())


def test_secret_scan_accepts_empty_documented_environment(tmp_path: Path) -> None:
    path = write(tmp_path / ".env.example", "OPENAI_API_KEY=\n")

    assert scan_paths((path,)) == []


def test_secret_scan_reports_location_without_value(tmp_path: Path) -> None:
    value = "sk-" + "A" * 24
    path = write(tmp_path / "settings.txt", f"OPENAI_API_KEY={value}\n")

    findings = scan_paths((path,))

    assert {finding.kind for finding in findings} == {"credential_assignment", "openai_key"}
    assert all(value not in repr(finding) for finding in findings)


@pytest.mark.parametrize("prefix", ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"))
def test_secret_scan_recognizes_github_token_prefixes(tmp_path: Path, prefix: str) -> None:
    value = prefix + "A" * 36
    path = write(tmp_path / "artifact.txt", value + "\n")

    assert [finding.kind for finding in scan_paths((path,))] == ["github_token"]


@pytest.mark.parametrize("prefix", ("AKIA", "ASIA"))
def test_secret_scan_recognizes_aws_access_key_prefixes(tmp_path: Path, prefix: str) -> None:
    value = prefix + "A" * 16
    path = write(tmp_path / "artifact.txt", value + "\n")

    assert [finding.kind for finding in scan_paths((path,))] == ["aws_access_key"]


def test_secret_scan_reads_utf16_configuration(tmp_path: Path) -> None:
    key = "JQUANTS" + "_API_KEY"
    path = tmp_path / "settings.txt"
    path.write_text(f"{key}=opaque-production-credential\n", encoding="utf-16")

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]


def test_secret_scan_reads_cp932_csv(tmp_path: Path) -> None:
    key = "JQUANTS" + "_API_KEY"
    path = tmp_path / "portfolio.csv"
    path.write_text(f"銘柄,{key}=opaque-production-credential\n", encoding="cp932")

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]


def test_secret_scan_accepts_safe_cp932_csv(tmp_path: Path) -> None:
    path = tmp_path / "portfolio.csv"
    path.write_text("銘柄,評価額\n該当なし,0\n", encoding="cp932")

    assert scan_paths((path,)) == []


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
    "key",
    (
        "AWS_" + "SECRET_ACCESS_KEY",
        "JQUANTS_" + "REFRESH_TOKEN",
        "PRIVATE_" + "KEY",
        "SLACK_" + "TOKEN",
        "CLIENT_" + "SECRET_KEY",
    ),
)
def test_secret_scan_recognizes_standard_secret_names(tmp_path: Path, key: str) -> None:
    path = write(tmp_path / "settings.txt", f"{key}=opaque-production-credential\n")

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


def test_secret_scan_accepts_github_builtin_tokens_and_oidc_permission(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / ".github" / "workflows" / "publish.yml"
    workflow.parent.mkdir(parents=True)
    write(
        workflow,
        "permissions:\n"
        "  id-token: write\n"
        "env:\n"
        "  GH_TOKEN: ${{ github.token }}\n"
        "with:\n"
        "  github-token: ${{ github.token }}\n",
    )

    assert scan_paths((workflow,)) == []


def test_secret_scan_rejects_literal_token_in_github_workflow(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "publish.yml"
    workflow.parent.mkdir(parents=True)
    write(workflow, "env:\n  GH_TOKEN: opaque-production-credential\n")

    assert [finding.kind for finding in scan_paths((workflow,))] == ["credential_assignment"]


@pytest.mark.parametrize("parameter", ("apikey", "api_key", "access_token"))
def test_secret_scan_rejects_url_credentials(tmp_path: Path, parameter: str) -> None:
    value = "opaque-production-credential"
    url = f"https://provider.invalid/data?{parameter}={value}\n"
    path = write(tmp_path / "request.txt", url)

    assert [finding.kind for finding in scan_paths((path,))] == ["url_credential"]


def test_secret_scan_rejects_url_userinfo_credentials(tmp_path: Path) -> None:
    userinfo_value = "opaque-production-credential"
    url = "https://alice:" + userinfo_value + "@provider.invalid/data\n"
    path = write(tmp_path / "request.txt", url)

    assert [finding.kind for finding in scan_paths((path,))] == ["url_credential"]


@pytest.mark.parametrize(
    ("header_name", "scheme", "expected"),
    (
        ("Authorization", "Basic ", "basic_auth"),
        ("X-" + "API-Key", "", "api_key_header"),
        ("API-Key", "", "api_key_header"),
    ),
)
def test_secret_scan_rejects_credential_headers(
    tmp_path: Path, header_name: str, scheme: str, expected: str
) -> None:
    header_value = "b3BhcXVlLXByb2R1Y3Rpb24tY3JlZGVudGlhbA=="
    path = write(tmp_path / "request.txt", f"{header_name}: {scheme}{header_value}\n")

    assert expected in {finding.kind for finding in scan_paths((path,))}


@pytest.mark.parametrize(
    ("case", "expected"),
    (
        ("json_api", "api_key_header"),
        ("mapping_api", "api_key_header"),
        ("json_basic", "basic_auth"),
        ("json_bearer", "bearer_token"),
    ),
)
def test_secret_scan_rejects_serialized_credential_headers(
    tmp_path: Path, case: str, expected: str
) -> None:
    documents = {
        "json_api": '{"' + "X-API-Key" + '": "opaque-production-credential"}\n',
        "mapping_api": "headers={'" + "X-API-Key" + "': 'opaque-production-credential'}\n",
        "json_basic": '{"' + "Authorization" + '": "Basic b3BhcXVlLXByb2R1Y3Rpb24="}\n',
        "json_bearer": '{"' + "Authorization" + '": "Bearer opaque-production-credential"}\n',
    }
    document = documents[case]
    path = write(tmp_path / "request.txt", document)

    assert expected in {finding.kind for finding in scan_paths((path,))}


@pytest.mark.parametrize(
    ("header_name", "scheme", "reference"),
    (
        ("Authorization", "Bearer ", "${OPENAI_API_KEY}"),
        ("Authorization", "Basic ", "${BASIC_AUTH_VALUE}"),
        ("X-" + "API-Key", "", "config.api_key"),
    ),
)
def test_secret_scan_accepts_header_credential_references(
    tmp_path: Path, header_name: str, scheme: str, reference: str
) -> None:
    path = write(tmp_path / "request.txt", f'{header_name}: "{scheme}{reference}"\n')

    assert scan_paths((path,)) == []


@pytest.mark.parametrize(
    ("prefix", "separator"),
    (
        ('curl -H "', ": "),
        ('headers["', '"] = "'),
    ),
)
def test_secret_scan_rejects_embedded_authorization_headers(
    tmp_path: Path, prefix: str, separator: str
) -> None:
    document = prefix + "Authorization" + separator + 'Bearer opaque-production-credential"\n'
    path = write(tmp_path / "request.txt", document)

    assert [finding.kind for finding in scan_paths((path,))] == ["bearer_token"]


def test_secret_scan_rejects_basic_subscript_header_assignment(tmp_path: Path) -> None:
    header = "Authorization"
    path = write(
        tmp_path / "provider.py",
        f'headers["{header}"] = "Basic b3BhcXVlLXByb2R1Y3Rpb24="\n',
    )

    assert [finding.kind for finding in scan_paths((path,))] == ["basic_auth"]


@pytest.mark.parametrize(
    "value",
    (
        "api_key",
        'os.environ["PROVIDER_API_KEY"]',
        'os.environ.get("PROVIDER_API_KEY")',
        "settings.api_key",
    ),
)
def test_secret_scan_accepts_python_runtime_header_references(tmp_path: Path, value: str) -> None:
    header = "X-" + "API-Key"
    path = write(tmp_path / "provider.py", f'headers = {{"{header}": {value}}}\n')

    assert scan_paths((path,)) == []


@pytest.mark.parametrize(
    "value",
    (
        '"Bearer " + token',
        'f"Bearer {token}"',
        '"Basic " + encoded_credentials',
    ),
)
def test_secret_scan_accepts_python_runtime_authorization_headers(
    tmp_path: Path, value: str
) -> None:
    path = write(tmp_path / "provider.py", f'headers = {{"Authorization": {value}}}\n')

    assert scan_paths((path,)) == []


def test_secret_scan_rejects_python_literal_api_key_header(tmp_path: Path) -> None:
    header = "X-" + "API-Key"
    path = write(
        tmp_path / "provider.py",
        f'headers = {{"{header}": "opaque-production-credential"}}\n',
    )

    assert [finding.kind for finding in scan_paths((path,))] == ["api_key_header"]


@pytest.mark.parametrize("call", ("logger.info", "RuntimeError"))
def test_secret_scan_rejects_credentials_in_python_string_literals(
    tmp_path: Path, call: str
) -> None:
    key = "OPENAI_" + "API_KEY"
    source = f'{call}("{key}=opaque-production-credential")\n'
    path = write(tmp_path / "provider.py", source)

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]


@pytest.mark.parametrize(
    "source",
    (
        "logger.info(api_key)\n",
        "logger.warning(config.access_token)\n",
        "RuntimeError(provider_password)\n",
        'logger.info("credential=%s", client_secret)\n',
    ),
)
def test_secret_scan_rejects_credential_expressions_in_output_sinks(
    tmp_path: Path, source: str
) -> None:
    path = write(tmp_path / "provider.py", source)

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_output"]


@pytest.mark.parametrize("container", ("comment", "docstring"))
def test_secret_scan_rejects_credentials_in_python_noncode(tmp_path: Path, container: str) -> None:
    key = "JQUANTS_" + "API_KEY"
    assignment = f"{key}=opaque-production-credential"
    source = f"# {assignment}\n" if container == "comment" else f'"""{assignment}"""\n'
    path = write(tmp_path / "provider.py", source)

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]


@pytest.mark.parametrize(
    "source",
    (
        'logger.info(f"token={token}")\n',
        'RuntimeError(f"password={provider_password}")\n',
        'logger.error("%s", mask(api_key))\n',
    ),
)
def test_secret_scan_rejects_compound_credential_output_expressions(
    tmp_path: Path, source: str
) -> None:
    path = write(tmp_path / "provider.py", source)

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_output"]


@pytest.mark.parametrize("separator", ("_", "-"))
def test_secret_scan_rejects_dotted_configuration_keys(tmp_path: Path, separator: str) -> None:
    key = "providers.openai.api" + separator + "key"
    path = write(tmp_path / "marketsieve.toml", f'{key} = "opaque-production-credential"\n')

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]


@pytest.mark.parametrize(
    "case",
    ("mapping", "compact_json", "inline_yaml"),
)
def test_secret_scan_rejects_embedded_credential_fields(tmp_path: Path, case: str) -> None:
    documents = {
        "mapping": 'payload = {"' + "api_key" + '": "opaque-production-credential"}\n',
        "compact_json": '{"ok":true,"' + "JQUANTS_API_KEY" + '":"opaque-production-credential"}\n',
        "inline_yaml": "provider: {" + "api_key" + ": opaque-production-credential}\n",
    }
    document = documents[case]
    path = write(tmp_path / "request.txt", document)

    assert "credential_assignment" in {finding.kind for finding in scan_paths((path,))}


@pytest.mark.parametrize(
    "expression",
    (
        'response.json()["access_token"]',
        "getpass()",
        "credential_provider.load()",
        "None",
    ),
)
def test_secret_scan_accepts_dynamic_credential_expressions(
    tmp_path: Path, expression: str
) -> None:
    key = "provider_" + "token"
    path = write(tmp_path / "provider.py", f"{key} = {expression}\n")

    assert scan_paths((path,)) == []


def test_secret_scan_accepts_shell_environment_reference(tmp_path: Path) -> None:
    key = "provider_" + "token"
    path = write(tmp_path / "settings.txt", f"{key} = $OPENAI_API_KEY\n")

    assert scan_paths((path,)) == []


@pytest.mark.parametrize(
    "case",
    ("assignment", "url", "header"),
)
def test_secret_scan_rejects_punctuation_bearing_credentials(tmp_path: Path, case: str) -> None:
    documents = {
        "assignment": "OPENAI_API_KEY=prod(secret)\n",
        "url": "https://user:" + "prod(secret)" + "@provider.invalid\n",
        "header": "Authorization: Bearer " + "prod(secret)" + "\n",
    }
    document = documents[case]
    path = write(tmp_path / "settings.txt", document)

    assert scan_paths((path,))


def test_secret_scan_rejects_python_literal_credentials(tmp_path: Path) -> None:
    key = "provider_" + "token"
    path = write(tmp_path / "provider.py", f'{key} = "opaque-production-credential"\n')

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]


def test_secret_scan_rejects_python_dict_and_keyword_credentials(tmp_path: Path) -> None:
    key = "api_" + "key"
    source = (
        f'headers = {{"{key}": "opaque-production-credential"}}\ncall({key}="another-credential")\n'
    )
    path = write(
        tmp_path / "provider.py",
        source,
    )

    assert [finding.kind for finding in scan_paths((path,))] == [
        "api_key_header",
        "credential_assignment",
    ]


def test_secret_scan_rejects_python_subscript_and_bytes_credentials(tmp_path: Path) -> None:
    key = "JQUANTS_" + "API_KEY"
    source = (
        f'import os\nos.environ["{key}"] = "opaque-production-credential"\n'
        f'{key} = b"another-credential"\n'
    )
    path = write(tmp_path / "provider.py", source)

    assert [finding.kind for finding in scan_paths((path,))] == [
        "credential_assignment",
        "credential_assignment",
    ]


@pytest.mark.parametrize("method", ("setdefault", "putenv"))
def test_secret_scan_rejects_python_environment_call_credentials(
    tmp_path: Path, method: str
) -> None:
    key = "JQUANTS_" + "API_KEY"
    target = "os.environ.setdefault" if method == "setdefault" else "os.putenv"
    source = f'import os\n{target}("{key}", "opaque-production-credential")\n'
    path = write(tmp_path / "provider.py", source)

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]


def test_secret_scan_rejects_sensitive_tracked_path(tmp_path: Path) -> None:
    path = write(tmp_path / ".env", "SAFE=placeholder\n")

    assert [finding.kind for finding in scan_paths((path,))] == ["sensitive_path"]


def test_secret_scan_hashes_credential_bearing_path(tmp_path: Path) -> None:
    token = "sk-" + "A" * 24
    path = write(tmp_path / f"backup-{token}.txt", "safe\n")

    findings = scan_paths((path,))

    assert [finding.kind for finding in findings] == ["credential_path"]
    assert findings[0].path.startswith("path-sha256:")
    assert token not in findings[0].path


def test_secret_scan_rejects_assignment_in_nested_path(tmp_path: Path) -> None:
    key = "OPENAI_" + "API_KEY"
    directory = tmp_path / "backup"
    directory.mkdir()
    path = write(directory / f"{key}=opaque-production-credential", "safe\n")

    findings = scan_paths((path,))

    assert [finding.kind for finding in findings] == ["credential_path"]
    assert findings[0].path.startswith("path-sha256:")


def test_patch_scan_rejects_assignment_in_diff_path() -> None:
    key = "OPENAI_" + "API_KEY"
    patch = f"diff --git a/backup/{key}=opaque-production-credential b/safe\n"

    assert [finding.kind for finding in scan_patch_text("change", patch)] == [
        "credential_assignment"
    ]


def test_credential_path_detector_hashes_archive_member_assignments() -> None:
    key = "JQUANTS_" + "API_KEY"
    label = f"artifact.zip!package/{key}=opaque-production-credential"

    finding = _credential_path_finding(label)

    assert finding is not None
    assert finding.path.startswith("path-sha256:")
    assert "opaque-production-credential" not in finding.path


def test_patch_scan_strips_diff_prefix_for_assignments() -> None:
    key = "JQUANTS_" + "API_KEY"
    patch = f"+{key}=opaque-production-credential\n"

    assert [finding.kind for finding in scan_patch_text("patch", patch)] == [
        "credential_assignment"
    ]


def test_secret_scan_rejects_case_variant_sensitive_directory(tmp_path: Path) -> None:
    directory = tmp_path / "Credentials"
    directory.mkdir()
    path = write(directory / "token.bin", "opaque\n")

    assert [finding.kind for finding in scan_paths((path,))] == ["sensitive_path"]


@pytest.mark.parametrize("name", ("credentials.json", "secrets.toml", "Credential.yaml"))
def test_secret_scan_rejects_sensitive_filename_with_extension(tmp_path: Path, name: str) -> None:
    path = write(tmp_path / name, "opaque\n")

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
            b"first message\n",
            f"+OPENAI_API_KEY={value}\n".encode(),
            b"",
            b"second message\n",
            b"-OPENAI_API_KEY=removed\n",
            b"",
        )
    )
    monkeypatch.setattr("scripts.secret_gate._capture", lambda _command: next(responses))

    findings = scan_history("base")

    assert [(finding.path, finding.kind) for finding in findings] == [
        ("git-commit:first", "openai_key")
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
            b"first message\n",
            b"Binary files differ\n",
            f"{archive_path}\0".encode(),
            buffer.getvalue(),
            b"second message\n",
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


def test_history_scan_fails_closed_for_binary_before_later_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        (
            b"first\nsecond\n",
            b"first message\n",
            b"Binary files differ\n",
            b"nested/content.bin\0",
            b"\0opaque-binary-content",
            b"second message\n",
            b"Binary files differ\n",
            b"",
        )
    )
    monkeypatch.setattr("scripts.secret_gate._capture", lambda _command: next(responses))

    findings = scan_history("base")

    assert [finding.kind for finding in findings] == ["unscannable_content"]


def test_history_scan_checks_commit_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    value = "sk-" + "A" * 24
    responses = iter((b"first\n", f"remove {value}\n".encode(), b"", b""))
    monkeypatch.setattr("scripts.secret_gate._capture", lambda _command: next(responses))

    findings = scan_history("base")

    assert [(finding.path, finding.kind) for finding in findings] == [
        ("git-message:first", "openai_key")
    ]


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


def test_secret_scan_fails_closed_for_malformed_archive(tmp_path: Path) -> None:
    path = tmp_path / "artifact.whl"
    path.write_bytes(b"not-a-valid-wheel")

    assert [finding.kind for finding in scan_paths((path,))] == ["unscannable_content"]


def test_secret_scan_fails_closed_at_nested_archive_limit(tmp_path: Path) -> None:
    payload = b"plain"
    for depth in range(5):
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as archive:
            archive.writestr(f"level-{depth}.zip", payload)
        payload = nested.getvalue()
    path = tmp_path / "wheelhouse.zip"
    path.write_bytes(payload)

    assert "unscannable_content" in {finding.kind for finding in scan_paths((path,))}


def test_secret_scan_reads_sdist_members(tmp_path: Path) -> None:
    value = "opaque-production-credential"
    settings = write(tmp_path / "settings.txt", f"JQUANTS_API_KEY={value}\n")
    path = tmp_path / "artifact.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        archive.add(settings, arcname="package/settings.txt")

    assert [finding.kind for finding in scan_paths((path,))] == ["credential_assignment"]
