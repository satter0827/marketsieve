from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from marketsieve_cli.adapters.preview import ObjectPreviewServer


def _object(tmp_path: Path) -> Path:
    path = tmp_path / "object"
    path.mkdir()
    (path / "explorer.html").write_text("<!doctype html><title>Explorer</title>", encoding="utf-8")
    (path / "explorer-data.json").write_text(
        json.dumps({"schema": "explorer-data/v1"}), encoding="utf-8"
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
            assert json.loads(response.read())["schema"] == "explorer-data/v1"
        with pytest.raises(HTTPError) as missing:
            urlopen(url.replace("/explorer.html", "/../manifest.json"), timeout=2)
        assert missing.value.code == 404
    finally:
        server.close()


def test_preview_rejects_incomplete_objects_and_invalid_ports(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    with pytest.raises(ValueError, match="incomplete"):
        ObjectPreviewServer(incomplete)
    with pytest.raises(ValueError, match="port"):
        ObjectPreviewServer(_object(tmp_path), port=70000)
