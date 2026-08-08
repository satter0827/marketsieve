# marketsieve

Provider-independent instruments, daily observations, Decimal-based indicators, field definitions,
and cross-sectional Market Snapshot calculations. This package performs no network, storage,
configuration, logging, CLI, or model-provider work.

```python
from marketsieve.fields import field_definitions
from marketsieve.indicators import IndicatorSpec, calculate
from marketsieve.model import DailyBar, Instrument


def analyze(bars: tuple[DailyBar, ...]):
    instrument = Instrument.create(
        symbol="MSFT", mic="XNAS", currency="USD", exchange_timezone="America/New_York"
    )
    result = calculate(IndicatorSpec.create("sma", period=20), bars)
    return instrument, result, field_definitions()
```

Insufficient observations produce an explicit indicator status rather than an imputed value.
