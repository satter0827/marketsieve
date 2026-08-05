"""Public package metadata for the MarketSieve SDK."""

from importlib.metadata import version

from marketsieve.decision import (
    AnalysisContext,
    BalancedMediumTermPolicy,
    DecisionAction,
    DecisionConfidence,
    DecisionEvidence,
    DecisionPolicy,
    DecisionReport,
    EvidenceDirection,
    InstrumentDecision,
    MarketSession,
)
from marketsieve.economic import EconomicObservation, EconomicSeries
from marketsieve.portfolio import (
    Holding,
    PersonalInvestmentContext,
    PortfolioSnapshot,
    WatchItem,
)

__version__ = version("marketsieve")

__all__ = [
    "AnalysisContext",
    "BalancedMediumTermPolicy",
    "DecisionAction",
    "DecisionConfidence",
    "DecisionEvidence",
    "DecisionPolicy",
    "DecisionReport",
    "EconomicObservation",
    "EconomicSeries",
    "EvidenceDirection",
    "Holding",
    "InstrumentDecision",
    "MarketSession",
    "PersonalInvestmentContext",
    "PortfolioSnapshot",
    "WatchItem",
    "__version__",
]
