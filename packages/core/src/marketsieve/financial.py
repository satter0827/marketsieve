"""Knowledge-time-correct financial history calculations."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

NUMERIC_CONTEXT = Context(prec=34, rounding=ROUND_HALF_EVEN)
BASE_CONCEPTS = frozenset(
    {
        "revenue",
        "operating_income",
        "net_income",
        "eps",
        "operating_cash_flow",
        "capital_expenditure",
        "assets",
        "equity",
        "interest_bearing_debt",
    }
)
DERIVED_CONCEPTS = frozenset(
    {
        "free_cash_flow",
        "revenue_growth",
        "eps_growth",
        "operating_margin",
        "net_margin",
        "roe",
        "roa",
        "equity_ratio",
        "debt_to_equity",
    }
)
RATIO_CONCEPTS = frozenset(
    {
        "revenue_growth",
        "eps_growth",
        "operating_margin",
        "net_margin",
        "roe",
        "roa",
        "equity_ratio",
        "debt_to_equity",
    }
)


def _canonical(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class FinancialObservation:
    """One normalized amount available to an analysis at a known instant."""

    concept: str
    value: Decimal
    scale: int
    period: str
    fiscal_period_start: date | None
    fiscal_period_end: date
    accounting_standard: str | None
    consolidation: str
    revision: str
    currency: str
    available_at: datetime
    evidence_id: str

    def __post_init__(self) -> None:
        if self.concept not in BASE_CONCEPTS:
            raise ValueError("financial observation concept is unsupported")
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise ValueError("financial observation value must be a finite Decimal")
        if not isinstance(self.scale, int) or isinstance(self.scale, bool) or self.scale <= 0:
            raise ValueError("financial observation scale must be a positive integer")
        if self.period not in {"annual", "quarterly", "interim_ytd", "ttm"}:
            raise ValueError("financial observation period is unsupported")
        if self.fiscal_period_start is not None and type(self.fiscal_period_start) is not date:
            raise TypeError("financial observation start must be a date or None")
        if type(self.fiscal_period_end) is not date:
            raise TypeError("financial observation end must be a date")
        if (
            self.fiscal_period_start is not None
            and self.fiscal_period_start > self.fiscal_period_end
        ):
            raise ValueError("financial observation period must be ascending")
        if self.accounting_standard == "":
            raise ValueError("financial observation accounting standard must not be empty")
        if self.consolidation not in {"consolidated", "non_consolidated", "unknown"}:
            raise ValueError("financial observation consolidation is unsupported")
        if self.revision not in {"reported", "restated", "unknown"}:
            raise ValueError("financial observation revision is unsupported")
        if not self.currency or not self.evidence_id:
            raise ValueError("financial observation identity must not be empty")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("financial observation available_at must include a UTC offset")

    @property
    def amount(self) -> Decimal:
        with localcontext(NUMERIC_CONTEXT):
            return +(self.value * Decimal(self.scale))


@dataclass(frozen=True, slots=True)
class FinancialPeriodView:
    """Compatible values selected for one annual reporting period."""

    fiscal_period_start: date
    fiscal_period_end: date
    accounting_standard: str
    consolidation: str
    currency: str
    values: tuple[tuple[str, Decimal], ...]
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        names = tuple(name for name, _ in self.values)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("financial period values must have unique sorted concepts")
        if any(not value.is_finite() for _, value in self.values):
            raise ValueError("financial period values must be finite")
        if not self.evidence_ids or any(not value for value in self.evidence_ids):
            raise ValueError("financial period evidence IDs must not be empty")


@dataclass(frozen=True, slots=True)
class FinancialMetric:
    """One deterministic amount or ratio derived from compatible periods."""

    name: str
    value: Decimal
    definition_version: str
    inputs: tuple[str, ...]
    fiscal_period_end: date
    accounting_standard: str
    consolidation: str
    revision: str
    currency: str | None
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.name not in DERIVED_CONCEPTS:
            raise ValueError("financial metric name is unsupported")
        if not self.value.is_finite():
            raise ValueError("financial metric value must be finite")
        if not self.definition_version or not self.inputs or not self.evidence_ids:
            raise ValueError("financial metric provenance must not be empty")

    @property
    def canonical_value(self) -> str:
        return _canonical(self.value)


@dataclass(frozen=True, slots=True)
class FinancialTrendReport:
    """A deterministic company-history view at one knowledge instant."""

    knowledge_at: datetime
    periods: tuple[FinancialPeriodView, ...]
    metrics: tuple[FinancialMetric, ...]
    missing_reasons: tuple[str, ...]
    evidence_id: str

    def __post_init__(self) -> None:
        if self.knowledge_at.tzinfo is None or self.knowledge_at.utcoffset() is None:
            raise ValueError("financial trend knowledge_at must include a UTC offset")
        ends = tuple(period.fiscal_period_end for period in self.periods)
        if ends != tuple(sorted(ends, reverse=True)) or len(ends) != len(set(ends)):
            raise ValueError("financial trend periods must have unique descending ends")
        names = tuple(metric.name for metric in self.metrics)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("financial trend metrics must have unique sorted names")
        if any(not reason for reason in self.missing_reasons):
            raise ValueError("financial trend missing reasons must not be empty")
        if len(self.evidence_id) != 64:
            raise ValueError("financial trend evidence ID must be a SHA-256 digest")

    def metric(self, name: str) -> FinancialMetric | None:
        return next((metric for metric in self.metrics if metric.name == name), None)


def analyze_financial_history(
    observations: Iterable[FinancialObservation], knowledge_at: datetime
) -> FinancialTrendReport:
    """Select compatible annual disclosures and calculate reproducible company trends."""

    if knowledge_at.tzinfo is None or knowledge_at.utcoffset() is None:
        raise ValueError("financial history knowledge_at must include a UTC offset")
    known = tuple(
        observation for observation in observations if observation.available_at <= knowledge_at
    )
    eligible = tuple(
        observation
        for observation in known
        if observation.period == "annual"
        and observation.fiscal_period_start is not None
        and observation.accounting_standard is not None
        and observation.consolidation != "unknown"
        and observation.revision != "unknown"
    )
    selected = _latest_period_values(eligible)
    if not selected:
        return _report(knowledge_at, (), (), ("compatible_annual_financial_period_not_available",))

    current = max(
        selected,
        key=lambda period: (
            period.fiscal_period_end,
            period.consolidation == "consolidated",
            period.accounting_standard,
            period.currency,
        ),
    )
    previous = max(
        (
            period
            for period in selected
            if period.accounting_standard == current.accounting_standard
            and period.consolidation == current.consolidation
            and period.currency == current.currency
            and period.fiscal_period_end < current.fiscal_period_start
        ),
        key=lambda period: period.fiscal_period_end,
        default=None,
    )
    periods = (current,) if previous is None else (current, previous)
    metrics = _metrics(current, previous, eligible)
    missing = tuple(
        f"{name}_inputs_not_compatible_or_missing"
        for name in sorted(DERIVED_CONCEPTS - {metric.name for metric in metrics})
    )
    return _report(knowledge_at, periods, metrics, missing)


def _latest_period_values(
    observations: tuple[FinancialObservation, ...],
) -> tuple[FinancialPeriodView, ...]:
    groups: dict[
        tuple[date | None, date, str | None, str, str], dict[str, FinancialObservation]
    ] = defaultdict(dict)
    for observation in observations:
        basis_key = (
            observation.fiscal_period_start,
            observation.fiscal_period_end,
            observation.accounting_standard,
            observation.consolidation,
            observation.currency,
        )
        previous = groups[basis_key].get(observation.concept)
        if previous is not None and previous.available_at == observation.available_at:
            if previous.amount != observation.amount:
                raise ValueError("financial history contains conflicting observations")
            if previous.evidence_id <= observation.evidence_id:
                continue
        if previous is None or (observation.available_at, observation.evidence_id) > (
            previous.available_at,
            previous.evidence_id,
        ):
            groups[basis_key][observation.concept] = observation

    periods = []
    for group_key, values in groups.items():
        start, end, standard, consolidation, currency = group_key
        assert isinstance(start, date)
        assert isinstance(end, date)
        assert isinstance(standard, str)
        assert isinstance(consolidation, str)
        assert isinstance(currency, str)
        periods.append(
            FinancialPeriodView(
                start,
                end,
                standard,
                consolidation,
                currency,
                tuple(sorted((name, value.amount) for name, value in values.items())),
                tuple(sorted({value.evidence_id for value in values.values()})),
            )
        )
    return tuple(periods)


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    with localcontext(NUMERIC_CONTEXT):
        return +(numerator / denominator)


def _growth(
    current: Decimal | None, previous: Decimal | None, *, absolute_base: bool
) -> Decimal | None:
    if current is None or previous is None:
        return None
    with localcontext(NUMERIC_CONTEXT):
        return _ratio(+(current - previous), abs(previous) if absolute_base else previous)


def _metrics(
    current: FinancialPeriodView,
    previous: FinancialPeriodView | None,
    observations: tuple[FinancialObservation, ...],
) -> tuple[FinancialMetric, ...]:
    values = dict(current.values)
    prior = dict(previous.values) if previous is not None else {}
    revisions = {
        observation.revision
        for observation in observations
        if observation.fiscal_period_start == current.fiscal_period_start
        and observation.fiscal_period_end == current.fiscal_period_end
        and observation.accounting_standard == current.accounting_standard
        and observation.consolidation == current.consolidation
        and observation.currency == current.currency
        and observation.evidence_id in current.evidence_ids
    }
    revision = next(iter(revisions)) if len(revisions) == 1 else "mixed"
    calculated: dict[str, tuple[Decimal | None, tuple[str, ...]]] = {
        "free_cash_flow": (
            (
                values["operating_cash_flow"] - abs(values["capital_expenditure"])
                if {"operating_cash_flow", "capital_expenditure"} <= values.keys()
                else None
            ),
            ("operating_cash_flow", "capital_expenditure"),
        ),
        "operating_margin": (
            _ratio(values.get("operating_income"), values.get("revenue")),
            ("operating_income", "revenue"),
        ),
        "net_margin": (
            _ratio(values.get("net_income"), values.get("revenue")),
            ("net_income", "revenue"),
        ),
        "roe": (_ratio(values.get("net_income"), values.get("equity")), ("net_income", "equity")),
        "roa": (_ratio(values.get("net_income"), values.get("assets")), ("net_income", "assets")),
        "equity_ratio": (_ratio(values.get("equity"), values.get("assets")), ("equity", "assets")),
        "debt_to_equity": (
            _ratio(values.get("interest_bearing_debt"), values.get("equity")),
            ("interest_bearing_debt", "equity"),
        ),
        "revenue_growth": (
            _growth(values.get("revenue"), prior.get("revenue"), absolute_base=False),
            ("revenue", "previous_revenue"),
        ),
        "eps_growth": (
            _growth(values.get("eps"), prior.get("eps"), absolute_base=True),
            ("eps", "previous_eps"),
        ),
    }
    evidence_ids = tuple(
        sorted({*current.evidence_ids, *(previous.evidence_ids if previous is not None else ())})
    )
    return tuple(
        FinancialMetric(
            name,
            value,
            f"{name}-v1",
            inputs,
            current.fiscal_period_end,
            current.accounting_standard,
            current.consolidation,
            revision,
            None if name in RATIO_CONCEPTS else current.currency,
            evidence_ids,
        )
        for name, (value, inputs) in sorted(calculated.items())
        if value is not None and value.is_finite()
    )


def _report(
    knowledge_at: datetime,
    periods: tuple[FinancialPeriodView, ...],
    metrics: tuple[FinancialMetric, ...],
    missing: tuple[str, ...],
) -> FinancialTrendReport:
    content = {
        "knowledge_at": knowledge_at.isoformat(),
        "periods": [
            {
                "start": period.fiscal_period_start.isoformat(),
                "end": period.fiscal_period_end.isoformat(),
                "standard": period.accounting_standard,
                "consolidation": period.consolidation,
                "currency": period.currency,
                "values": [(name, _canonical(value)) for name, value in period.values],
                "evidence_ids": period.evidence_ids,
            }
            for period in periods
        ],
        "metrics": [
            {
                "name": metric.name,
                "value": metric.canonical_value,
                "definition": metric.definition_version,
                "inputs": metric.inputs,
                "evidence_ids": metric.evidence_ids,
            }
            for metric in metrics
        ],
        "missing": missing,
    }
    return FinancialTrendReport(knowledge_at, periods, metrics, missing, _digest(content))
