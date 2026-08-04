"""Shared parsing for the configured GitHub repository."""

from __future__ import annotations


def repository_name(remote: str) -> str:
    value = remote.removesuffix(".git")
    if value.startswith("https://github.com/"):
        return value.removeprefix("https://github.com/")
    if value.startswith("git@github.com:"):
        return value.removeprefix("git@github.com:")
    raise RuntimeError("origin must identify a GitHub repository")
