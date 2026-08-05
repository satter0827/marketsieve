"""Explicit, explanation-only decision-report use cases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from marketsieve import DecisionReport
from marketsieve_agent import (
    AnthropicModel,
    FactCatalog,
    GoogleModel,
    LmStudioModel,
    OpenAIModel,
    explain,
)
from marketsieve_agent.pipeline import PROMPT_VERSION, build_prompt


class AgentConfiguration(Protocol):
    def agent_provider(self, name: str) -> Any: ...


class DecisionReportReader(Protocol):
    def resolve(self, report_id: str) -> DecisionReport: ...


class ExplanationWriter(Protocol):
    def put(self, value: dict[str, Any]) -> dict[str, Any]: ...


class AgentService:
    """Explain exactly one verified report through one explicit provider."""

    def __init__(
        self,
        reports: DecisionReportReader,
        explanations: ExplanationWriter,
        configuration: AgentConfiguration,
        environment: Mapping[str, str],
    ) -> None:
        self._reports = reports
        self._explanations = explanations
        self._configuration = configuration
        self._environment = environment

    def doctor(self, provider: str, *, allow_remote: bool = False) -> dict[str, Any]:
        try:
            model, endpoint = self._doctor_details(provider, allow_remote=allow_remote)
        except (LookupError, TypeError, ValueError) as error:
            return {
                "schema_version": "1.0.0",
                "operation": "doctor",
                "status": "not_ready",
                "provider": provider,
                "model": None,
                "endpoint": None,
                "message": str(error),
            }
        return {
            "schema_version": "1.0.0",
            "operation": "doctor",
            "status": "ready",
            "provider": provider,
            "model": model,
            "endpoint": endpoint,
            "message": "provider configuration is ready; no model request was made",
        }

    def explain(
        self,
        report_id: str,
        provider: str,
        locale: str,
        *,
        allow_cloud: bool,
        allow_remote: bool,
        dry_run: bool,
    ) -> dict[str, Any]:
        report = self._reports.resolve(report_id)
        catalog = FactCatalog.from_report(report)
        prompt = build_prompt(catalog, locale)
        if dry_run:
            model, endpoint = self._preview_details(provider, allow_remote=allow_remote)
            return {
                "schema_version": "1.0.0",
                "operation": "dry_run",
                "status": "ready",
                "provider": provider,
                "model": model,
                "endpoint": endpoint,
                "report_id": report.report_id,
                "prompt_version": PROMPT_VERSION,
                "catalog_hash": catalog.catalog_hash,
                "fact_count": len(catalog.facts),
                "payload": prompt,
            }
        selected = self._model(provider, allow_cloud=allow_cloud, allow_remote=allow_remote)
        result = explain(report, model=selected, locale=locale).as_document()
        artifact = self._explanations.put({**result, "operation": "explain"})
        return artifact

    def _doctor_details(self, provider: str, *, allow_remote: bool) -> tuple[str, str | None]:
        model, endpoint = self._preview_details(provider, allow_remote=allow_remote)
        if provider == "lmstudio":
            LmStudioModel(model=model, endpoint=endpoint or "", allow_remote=allow_remote)
        return model, endpoint

    def _preview_details(self, provider: str, *, allow_remote: bool) -> tuple[str, str | None]:
        settings = self._configuration.agent_provider(provider)
        if provider == "lmstudio":
            endpoint = settings.endpoint or "http://127.0.0.1:1234/v1"
            LmStudioModel(model=settings.model, endpoint=endpoint, allow_remote=allow_remote)
            return settings.model, endpoint
        if provider not in {"openai", "anthropic", "google"}:
            raise ValueError("agent provider is not supported")
        if settings.endpoint is not None:
            raise ValueError("cloud agent endpoints are fixed and cannot be configured")
        endpoints = {
            "openai": OpenAIModel.endpoint,
            "anthropic": AnthropicModel.endpoint,
            "google": GoogleModel.endpoint,
        }
        return settings.model, endpoints[provider]

    def _model(self, provider: str, *, allow_cloud: bool, allow_remote: bool) -> Any:
        settings = self._configuration.agent_provider(provider)
        self._preview_details(provider, allow_remote=allow_remote)
        if provider == "lmstudio":
            return LmStudioModel(
                model=settings.model,
                endpoint=settings.endpoint or "http://127.0.0.1:1234/v1",
                api_token=self._environment.get("LMSTUDIO_API_TOKEN"),
                allow_remote=allow_remote,
            )
        credentials = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
        }
        if provider not in credentials:
            raise ValueError("agent provider is not supported")
        key = self._environment.get(credentials[provider], "")
        constructors = {"openai": OpenAIModel, "anthropic": AnthropicModel, "google": GoogleModel}
        return constructors[provider](model=settings.model, api_key=key, allow_cloud=allow_cloud)
