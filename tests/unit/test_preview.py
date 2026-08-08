from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from marketsieve_cli.adapters.preview import ObjectPreviewServer


def _object(tmp_path: Path) -> Path:
    path = tmp_path / "object"
    path.mkdir()
    (path / "explorer.html").write_text("<!doctype html><title>Explorer</title>", encoding="utf-8")
    (path / "explorer-data.json").write_text(
        json.dumps({"schema": "explorer-data/v4"}), encoding="utf-8"
    )
    (path / "securities.jsonl").write_text('{"instrument_id":"XNAS:MSFT"}\n', encoding="utf-8")
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "artifacts": {
                    "explorer.html": "explorer.html",
                    "explorer-data.json": "explorer-data.json",
                    "securities.jsonl": "securities.jsonl",
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_preview_serves_only_one_explorer_object(tmp_path: Path) -> None:
    try:
        server = ObjectPreviewServer(_object(tmp_path))
    except PermissionError:
        pytest.skip("sandbox does not permit loopback sockets")
    url = server.start()
    try:
        with urlopen(url, timeout=2) as response:
            assert response.status == 200
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        with urlopen(url.replace("/explorer.html", "/explorer-data.json"), timeout=2) as response:
            assert json.loads(response.read())["schema"] == "explorer-data/v4"
        with urlopen(url.replace("/explorer.html", "/securities.jsonl"), timeout=2) as response:
            assert response.headers["Content-Type"].startswith("application/x-ndjson")
        with pytest.raises(HTTPError) as missing:
            urlopen(url.replace("/explorer.html", "/../manifest.json"), timeout=2)
        assert missing.value.code == 404
    finally:
        server.close()


def test_preview_rejects_incomplete_objects_and_invalid_ports(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    with pytest.raises(ValueError, match="manifest"):
        ObjectPreviewServer(incomplete)
    with pytest.raises(ValueError, match="port"):
        ObjectPreviewServer(_object(tmp_path), port=70000)


def test_preview_rejects_invalid_manifests_and_registered_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(LookupError, match="does not exist"):
        ObjectPreviewServer(missing)

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "manifest.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest is invalid"):
        ObjectPreviewServer(invalid)

    artifact_cases: tuple[object, ...] = (
        [],
        {"explorer-data.json": "explorer-data.json"},
    )
    for artifacts in artifact_cases:
        incomplete = tmp_path / f"incomplete-{len(list(tmp_path.iterdir()))}"
        incomplete.mkdir()
        (incomplete / "manifest.json").write_text(
            json.dumps({"artifacts": artifacts}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="artifact metadata"):
            ObjectPreviewServer(incomplete)

    registered_missing = _object(tmp_path)
    (registered_missing / "securities.jsonl").unlink()
    with pytest.raises(ValueError, match="registered artifacts"):
        ObjectPreviewServer(registered_missing)


def test_preview_rejects_symlinks(tmp_path: Path) -> None:
    target = _object(tmp_path)
    link = tmp_path / "object-link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(LookupError, match="does not exist"):
        ObjectPreviewServer(link)

    nested = tmp_path / "nested"
    nested.mkdir()
    artifact_link = _object(nested)
    actual = artifact_link / "actual.jsonl"
    actual.write_text("{}\n", encoding="utf-8")
    (artifact_link / "securities.jsonl").unlink()
    (artifact_link / "securities.jsonl").symlink_to(actual)
    with pytest.raises(ValueError, match="registered artifacts"):
        ObjectPreviewServer(artifact_link)


def test_preview_lifecycle_and_content_types(tmp_path: Path) -> None:
    path = _object(tmp_path)
    (path / "README.md").write_text("# Snapshot\n", encoding="utf-8")
    (path / "definitions.bin").write_bytes(b"evidence")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifacts"].update({"README.md": "README.md", "definitions.bin": "definitions.bin"})
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    try:
        server = ObjectPreviewServer(path)
    except PermissionError:
        pytest.skip("sandbox does not permit loopback sockets")
    url = server.start()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            server.start()
        with urlopen(url.replace("/explorer.html", "/README.md"), timeout=2) as response:
            assert response.headers["Content-Type"].startswith("text/markdown")
        with urlopen(url.replace("/explorer.html", "/definitions.bin"), timeout=2) as response:
            assert response.headers["Content-Type"] == "application/octet-stream"
        with urlopen(url.replace("/explorer.html", "/"), timeout=2) as response:
            assert response.status == 200
    finally:
        server.close()


def test_preview_serve_forever_opens_browser_and_closes_server(tmp_path: Path) -> None:
    server = ObjectPreviewServer.__new__(ObjectPreviewServer)
    fake_server = Mock()
    server._server = fake_server
    server._thread = None
    with patch("marketsieve_cli.adapters.preview.webbrowser.open") as open_browser:
        server.serve_forever(open_browser=True)
    open_browser.assert_called_once_with(server.url)
    fake_server.serve_forever.assert_called_once_with()
    fake_server.server_close.assert_called_once_with()
