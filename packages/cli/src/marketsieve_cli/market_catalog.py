"""CLI-owned runtime definitions for the built-in equity indices."""

from __future__ import annotations

from dataclasses import dataclass

from marketsieve.model import Instrument


@dataclass(frozen=True, slots=True)
class IndexRuntimeDefinition:
    """Provider and instrument identity for one built-in index benchmark."""

    market: str
    symbol: str
    mic: str
    provider_symbol: str
    currency: str
    exchange_timezone: str

    def instrument(self) -> Instrument:
        return Instrument.create(
            symbol=self.symbol,
            mic=self.mic,
            currency=self.currency,
            exchange_timezone=self.exchange_timezone,
        )


INDEX_RUNTIME_CATALOG = {
    "dow30": IndexRuntimeDefinition("us", "DJI", "XNYS", "^DJI", "USD", "America/New_York"),
    "nasdaq100": IndexRuntimeDefinition("us", "NDX", "XNAS", "^NDX", "USD", "America/New_York"),
    "nikkei225": IndexRuntimeDefinition("jp", "N225", "XTKS", "^N225", "JPY", "Asia/Tokyo"),
    "sp500": IndexRuntimeDefinition("us", "GSPC", "XNYS", "^GSPC", "USD", "America/New_York"),
    "topix500": IndexRuntimeDefinition("jp", "1308", "XTKS", "1308.T", "JPY", "Asia/Tokyo"),
}

MARKET_INDEX_GROUPS = {
    market: tuple(
        sorted(name for name, value in INDEX_RUNTIME_CATALOG.items() if value.market == market)
    )
    for market in ("jp", "us")
}
