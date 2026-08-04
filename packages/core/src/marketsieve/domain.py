"""Exchange-qualified instrument identity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SYMBOL = re.compile(r"^[A-Z0-9]+$")
MIC = re.compile(r"^[A-Z0-9]{4}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")


class InstrumentType(StrEnum):
    """Supported instrument classifications."""

    EQUITY = "equity"


@dataclass(frozen=True, slots=True)
class Instrument:
    """An unambiguous exchange-qualified instrument."""

    symbol: str
    mic: str
    currency: str
    exchange_timezone: ZoneInfo
    instrument_type: InstrumentType

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) for value in (self.symbol, self.mic, self.currency)):
            raise TypeError("symbol, mic, and currency must be strings")
        if SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError("symbol must be uppercase alphanumeric without a market suffix")
        if MIC.fullmatch(self.mic) is None:
            raise ValueError("mic must be a four-character ISO 10383 code")
        if CURRENCY.fullmatch(self.currency) is None:
            raise ValueError("currency must be a three-letter uppercase code")
        if not isinstance(self.exchange_timezone, ZoneInfo):
            raise TypeError("exchange_timezone must be zoneinfo.ZoneInfo")
        if not isinstance(self.instrument_type, InstrumentType):
            raise TypeError("instrument_type must be InstrumentType")

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        mic: str,
        currency: str,
        exchange_timezone: str,
        instrument_type: InstrumentType = InstrumentType.EQUITY,
    ) -> Instrument:
        """Create an instrument while validating the IANA timezone name."""

        try:
            timezone = ZoneInfo(exchange_timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown exchange timezone: {exchange_timezone}") from error
        return cls(symbol, mic, currency, timezone, instrument_type)
