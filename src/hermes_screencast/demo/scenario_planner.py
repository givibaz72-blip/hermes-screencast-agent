from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, Sequence

from hermes_screencast.demo.json_loader import demo_script_from_dict
from hermes_screencast.demo.script import DemoActionType, DemoScript


class ScenarioPlanningError(ValueError):
    """Raised when a scenario cannot be converted into a valid DemoScript."""


class ScenarioProviderError(ScenarioPlanningError):
    """Raised when a scenario provider cannot return usable output."""


class ScenarioProvider(Protocol):
    def generate(self, prompt: str) -> str:
        """Return one JSON object as text for the supplied planning prompt."""


@dataclass(frozen=True)
class ScenarioPlanningRequest:
    scenario: str
    target_url: str | None = None
    title: str | None = None
    preferences: dict[str, Any] = field(default_factory=dict)
    constraints: tuple[str, ...] = ()
    discovery: dict[str, Any] | None = None

    def validate(self) -> None:
        if not self.scenario.strip():
            raise ScenarioPlanningError("Scenario text cannot be empty")
        if self.target_url is not None and not self.target_url.strip():
            raise ScenarioPlanningError("Target URL cannot be empty")
        if self.title is not None and not self.title.strip():
            raise ScenarioPlanningError("Scenario title cannot be empty")
        if not isinstance(self.preferences, dict):
            raise ScenarioPlanningError("Scenario preferences must be an object")
        if any(not constraint.strip() for constraint in self.constraints):
            raise ScenarioPlanningError("Scenario constraints cannot be empty")
        if self.discovery is not None:
            if not isinstance(self.discovery, dict):
                raise ScenarioPlanningError("Scenario discovery must be an object")
            if self.discovery.get("schema") != "hermes.discovery.v1":
                raise ScenarioPlanningError(
                    "Scenario discovery must use schema hermes.discovery.v1"
                )


@dataclass(frozen=True)
class CommandScenarioProvider:
    command: Sequence[str]

    def generate(self, prompt: str) -> str:
        if not self.command:
            raise ScenarioProviderError("Provider command cannot be empty")

        try:
            result = subprocess.run(
                list(self.command),
                input=prompt,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise ScenarioProviderError(
                f"Could not start provider command: {self.command[0]}"
            ) from exc

        if result.returncode != 0:
            raise ScenarioProviderError(
                f"Provider command failed with exit code {result.returncode}"
            )
        if not result.stdout.strip():
            raise ScenarioProviderError("Provider command returned empty output")

        return result.stdout


@dataclass(frozen=True)
class ScenarioPlanner:
    provider: ScenarioProvider

    def plan(self, request: ScenarioPlanningRequest) -> DemoScript:
        request.validate()
        raw_output = self.provider.generate(build_scenario_prompt(request))

        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise ScenarioPlanningError(
                f"Provider output is not valid JSON: {exc.msg}"
            ) from exc

        try:
            script = demo_script_from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise ScenarioPlanningError(f"Provider returned invalid DemoScript: {exc}") from exc

        if script.steps[0].action != DemoActionType.GOTO:
            raise ScenarioPlanningError(
                "Provider returned invalid DemoScript: first step must be goto"
            )

        if request.target_url is not None and script.steps[0].url != request.target_url:
            raise ScenarioPlanningError(
                "Provider returned invalid DemoScript: first goto URL must match target URL"
            )

        script = replace(
            script,
            title=request.title or script.title,
            preferences={**script.preferences, **request.preferences},
        )
        script.validate()
        return script


def build_scenario_prompt(request: ScenarioPlanningRequest) -> str:
    request.validate()
    actions = [action.value for action in DemoActionType]
    input_payload = {
        "scenario": request.scenario,
        "target_url": request.target_url,
        "title": request.title,
        "preferences": request.preferences,
        "constraints": list(request.constraints),
        "discovery_report": request.discovery,
    }

    return (
        "Convert the user scenario below into one Hermes DemoScript JSON object.\n"
        "Return JSON only: no Markdown, comments, prose, or code fences.\n"
        "Use only these top-level fields: title, target, preferences, metadata, steps.\n"
        "Each step may use only: action, selector, url, text, seconds, value, note, metadata.\n"
        f"Supported actions: {json.dumps(actions)}.\n"
        "The first step must be goto. Use the exact target_url for that step when supplied.\n"
        "Use stable browser selectors and add waits or assertions after important state changes.\n"
        "When a discovery_report is supplied, use its selectors instead of inventing selectors.\n"
        "Do not include credentials or invent actions that are not supported.\n"
        "Input:\n"
        f"{json.dumps(input_payload, ensure_ascii=False, indent=2)}\n"
    )
