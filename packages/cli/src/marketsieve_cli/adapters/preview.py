"""Loopback-only preview server for one immutable evidence object."""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class ObjectPreviewServer:
    """Expose only one verified object's registered artifacts on loopback."""

    def __init__(self, object_path: Path, *, port: int = 0) -> None:
        resolved = object_path.resolve()
        if object_path.is_symlink() or not resolved.is_dir():
            raise LookupError("preview evidence object does not exist")
        manifest_path = resolved / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("preview evidence object has no manifest")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("preview evidence object manifest is invalid") from error
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or "explorer.html" not in artifacts:
            raise ValueError("preview evidence object has incomplete artifact metadata")
        allowed_names = set(artifacts) | {"manifest.json"}
        allowed = {f"/{name}": resolved / name for name in allowed_names}
        allowed["/"] = resolved / "explorer.html"
        if any(path.is_symlink() or not path.is_file() for path in allowed.values()):
            raise ValueError("preview evidence object has incomplete registered artifacts")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = urlsplit(self.path).path
                path = allowed.get(route)
                if path is None:
                    self.send_error(404)
                    return
                body = path.read_bytes()
                content_type = {
                    ".html": "text/html; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                    ".jsonl": "application/x-ndjson; charset=utf-8",
                    ".md": "text/markdown; charset=utf-8",
                }.get(path.suffix, "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                del format, args

        if not 0 <= port <= 65535:
            raise ValueError("preview port must be from 0 through 65535")
        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/explorer.html"

    def start(self) -> str:
        if self._thread is not None:
            raise RuntimeError("preview server is already running")
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    def serve_forever(self, *, open_browser: bool = False) -> None:
        if open_browser:
            webbrowser.open(self.url)
        try:
            self._server.serve_forever()
        finally:
            self._server.server_close()

    def close(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=5)
        self._server.server_close()
