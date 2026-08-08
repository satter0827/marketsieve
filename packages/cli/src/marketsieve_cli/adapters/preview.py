"""Loopback-only preview server for one immutable evidence object."""

from __future__ import annotations

import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class ObjectPreviewServer:
    """Expose only one Explorer and its chart-neutral data on loopback."""

    def __init__(self, object_path: Path, *, port: int = 0) -> None:
        resolved = object_path.resolve()
        if object_path.is_symlink() or not resolved.is_dir():
            raise LookupError("preview evidence object does not exist")
        allowed = {
            "/": resolved / "explorer.html",
            "/explorer.html": resolved / "explorer.html",
            "/explorer-data.json": resolved / "explorer-data.json",
        }
        if any(path.is_symlink() or not path.is_file() for path in allowed.values()):
            raise ValueError("preview evidence object has incomplete Explorer artifacts")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = urlsplit(self.path).path
                path = allowed.get(route)
                if path is None:
                    self.send_error(404)
                    return
                body = path.read_bytes()
                content_type = (
                    "application/json; charset=utf-8"
                    if path.suffix == ".json"
                    else "text/html; charset=utf-8"
                )
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
