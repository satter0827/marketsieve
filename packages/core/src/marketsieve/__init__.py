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
    candidate_order_key,
)
from marketsieve.economic import EconomicObservation, EconomicSeries
from marketsieve.experiment import (
    ExperimentComparison,
    ExperimentMetric,
    ExperimentRun,
    ExperimentSpec,
    ReplayDecision,
    ReplayWindow,
    compare_experiments,
    run_experiment,
)
from marketsieve.financial import (
    FinancialMetric,
    FinancialObservation,
    FinancialPeriodView,
    FinancialTrendReport,
    analyze_financial_history,
)
from marketsieve.portfolio import (
    Holding,
    PersonalInvestmentContext,
    PortfolioSnapshot,
    WatchItem,
)
from marketsieve.screening import (
    BalancedCandidateScreen,
    InstrumentUniverse,
    ScreenCandidate,
    ScreeningReport,
    ScreenPolicy,
)

__version__ = version("marketsieve")

__all__ = [
    "AnalysisContext",
    "BalancedCandidateScreen",
    "BalancedMediumTermPolicy",
    "DecisionAction",
    "DecisionConfidence",
    "DecisionEvidence",
    "DecisionPolicy",
    "DecisionReport",
    "EconomicObservation",
    "EconomicSeries",
    "EvidenceDirection",
    "ExperimentComparison",
    "ExperimentMetric",
    "ExperimentRun",
    "ExperimentSpec",
    "FinancialMetric",
    "FinancialObservation",
    "FinancialPeriodView",
    "FinancialTrendReport",
    "Holding",
    "InstrumentDecision",
    "InstrumentUniverse",
    "MarketSession",
    "PersonalInvestmentContext",
    "PortfolioSnapshot",
    "ReplayDecision",
    "ReplayWindow",
    "ScreenCandidate",
    "ScreenPolicy",
    "ScreeningReport",
    "WatchItem",
    "__version__",
    "analyze_financial_history",
    "candidate_order_key",
    "compare_experiments",
    "run_experiment",
]
