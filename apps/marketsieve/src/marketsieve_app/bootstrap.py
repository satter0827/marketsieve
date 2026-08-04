"""Composition root for repository-local application services."""

from marketsieve import __version__
from marketsieve.synthetic.daily import (
    JP_BARS,
    JP_INSTRUMENT,
    US_BARS,
    US_INSTRUMENT,
    jp_source,
    us_source,
)
from marketsieve_app.application.demo import DemoMarket, DemoService
from marketsieve_app.application.diagnostics import DiagnosticsService
from marketsieve_app.observability import configure_logger


def build_diagnostics_service(
    *, level: str = "WARNING", write_log_file: bool = False
) -> DiagnosticsService:
    """Build the diagnostics use case with its default dependencies."""

    return DiagnosticsService(logger=configure_logger(level=level, write_file=write_log_file))


def build_demo_service(*, level: str = "WARNING", write_log_file: bool = False) -> DemoService:
    """Build the deterministic offline-demo use case."""

    markets = (
        DemoMarket(
            "jp", JP_INSTRUMENT, jp_source(), JP_BARS[0].trading_date, JP_BARS[-1].trading_date
        ),
        DemoMarket(
            "us", US_INSTRUMENT, us_source(), US_BARS[0].trading_date, US_BARS[-1].trading_date
        ),
    )
    return DemoService(markets, configure_logger(level=level, write_file=write_log_file))


def sdk_version() -> str:
    """Return the installed public SDK version."""

    return __version__
