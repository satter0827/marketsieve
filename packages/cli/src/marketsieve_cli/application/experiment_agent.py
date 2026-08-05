"""Optional grounded explanation of immutable experiment runs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from marketsieve_agent import explain_experiment
from marketsieve_cli.application.agent import model_details, select_model


class ExperimentReader(Protocol):
    def show(self, run_id: str) -> dict[str, Any]: ...


class ExperimentExplanationWriter(Protocol):
    def put(self, value: dict[str, Any]) -> dict[str, Any]: ...


class AgentConfiguration(Protocol):
    def agent_provider(self, name: str) -> Any: ...


class ExperimentAgentService:
    """Explain one verified experiment without changing its facts or metrics."""

    def __init__(
        self,
        runs: ExperimentReader,
        explanations: ExperimentExplanationWriter,
        configuration: AgentConfiguration,
        environment: Mapping[str, str],
    ) -> None:
        self._runs = runs
        self._explanations = explanations
        self._configuration = configuration
        self._environment = environment

    def explain(
        self,
        run_id: str,
        provider: str,
        locale: str,
        *,
        allow_cloud: bool,
        allow_remote: bool,
    ) -> dict[str, Any]:
        run = self._runs.show(run_id)
        model_name, endpoint = model_details(
            self._configuration, provider, allow_remote=allow_remote
        )
        model = select_model(
            self._configuration,
            self._environment,
            provider,
            allow_cloud=allow_cloud,
            allow_remote=allow_remote,
        )
        result = explain_experiment(run, model=model, locale=locale)
        result["model_settings"] = {
            "provider": provider,
            "model": model_name,
            "endpoint": endpoint,
            "locale": locale,
        }
        return self._explanations.put(result)
