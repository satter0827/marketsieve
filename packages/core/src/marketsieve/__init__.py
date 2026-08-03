"""Public package metadata for the MarketSieve SDK."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("marketsieve")
except PackageNotFoundError:  # pragma: no cover - source tree without installation
    __version__ = "0.1.0.dev0"

__all__ = ["__version__"]
