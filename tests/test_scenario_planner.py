from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from hermes_screencast.demo.scenario_planner import (
    CommandScenarioProvider,
    ScenarioPlanner,
    ScenarioPlanningError,
    ScenarioPlanningRequest,
    ScenarioProviderError,
    build_scenario_prompt,
)
from hermes_screencast.demo.script import DemoActionType


@dataclass
class FakeProvider:
    output: str
    prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return self.output


def valid_output(url: str = "https://example.com") -> str:
    return json.dumps(
        {
            "title": "Generated demo",
            "target": {"kind": "web", "url": url},
            "preferences": {"pacing": "professional"},
            "metadata": {"schema": "hermes.demo.v1"},
            "steps": [
                {"action": "goto", "url": url},
                {"action": "highlight", "selector": "h1"},
            ],
        }
    )


def test_scenario_planner_returns_validated_demo_script() -> None:
    provider = FakeProvider(valid_output())
    request = ScenarioPlanningRequest(
        scenario="Open the page and highlight the heading.",
        target_url="https://example.com",
        preferences={"pacing": "professional"},
        constraints=("Do not click links",),
    )

    script = ScenarioPlanner(provider=provider).plan(request)

    assert script.title == "Generated demo"
    assert script.steps[0].action == DemoActionType.GOTO
    assert script.steps[1].selector == "h1"
    assert provider.prompt is not None
    assert "Do not click links" in provider.prompt


def test_request_title_and_preferences_override_provider_defaults() -> None:
    script = ScenarioPlanner(provider=FakeProvider(valid_output())).plan(
        ScenarioPlanningRequest(
            scenario="Show the page",
            title="Requested title",
            preferences={"pacing": "brisk", "browser_ui": "visible"},
        )
    )

    assert script.title == "Requested title"
    assert script.preferences == {
        "pacing": "brisk",
        "browser_ui": "visible",
    }


def test_scenario_prompt_lists_only_supported_actions() -> None:
    prompt = build_scenario_prompt(
        ScenarioPlanningRequest(scenario="Show the page")
    )

    assert '"goto"' in prompt
    assert '"highlight"' in prompt
    assert "Return JSON only" in prompt


def test_scenario_prompt_includes_valid_discovery_report() -> None:
    prompt = build_scenario_prompt(
        ScenarioPlanningRequest(
            scenario="Click Save",
            discovery={
                "schema": "hermes.discovery.v1",
                "elements": [
                    {"name": "Save", "selector": '[data-testid="save"]'}
                ],
            },
        )
    )

    assert "discovery_report" in prompt
    assert '[data-testid=\\"save\\"]' in prompt


def test_scenario_planner_rejects_unknown_discovery_schema() -> None:
    provider = FakeProvider(valid_output())

    with pytest.raises(ScenarioPlanningError, match="hermes.discovery.v1"):
        ScenarioPlanner(provider=provider).plan(
            ScenarioPlanningRequest(
                scenario="Show the page",
                discovery={"schema": "unknown"},
            )
        )

    assert provider.prompt is None


def test_scenario_planner_rejects_empty_scenario_before_provider_call() -> None:
    provider = FakeProvider(valid_output())

    with pytest.raises(ScenarioPlanningError, match="cannot be empty"):
        ScenarioPlanner(provider=provider).plan(
            ScenarioPlanningRequest(scenario="   ")
        )

    assert provider.prompt is None


def test_scenario_planner_rejects_malformed_json() -> None:
    with pytest.raises(ScenarioPlanningError, match="not valid JSON"):
        ScenarioPlanner(provider=FakeProvider("```json\n{}\n```" )).plan(
            ScenarioPlanningRequest(scenario="Show the page")
        )


def test_scenario_planner_rejects_invalid_demo_script() -> None:
    output = json.dumps(
        {
            "title": "Invalid demo",
            "steps": [{"action": "click"}],
        }
    )

    with pytest.raises(ScenarioPlanningError, match="click requires selector"):
        ScenarioPlanner(provider=FakeProvider(output)).plan(
            ScenarioPlanningRequest(scenario="Click the button")
        )


def test_scenario_planner_requires_goto_as_first_step() -> None:
    output = json.dumps(
        {
            "title": "Invalid demo",
            "steps": [{"action": "wait", "seconds": 1}],
        }
    )

    with pytest.raises(ScenarioPlanningError, match="first step must be goto"):
        ScenarioPlanner(provider=FakeProvider(output)).plan(
            ScenarioPlanningRequest(scenario="Wait")
        )


def test_scenario_planner_requires_exact_requested_target_url() -> None:
    with pytest.raises(ScenarioPlanningError, match="must match target URL"):
        ScenarioPlanner(provider=FakeProvider(valid_output("https://wrong.example"))).plan(
            ScenarioPlanningRequest(
                scenario="Show the page",
                target_url="https://example.com",
            )
        )


def test_command_provider_passes_prompt_through_stdin(monkeypatch) -> None:
    calls = []

    class Result:
        returncode = 0
        stdout = valid_output()

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr("hermes_screencast.demo.scenario_planner.subprocess.run", fake_run)

    output = CommandScenarioProvider(("provider", "--offline")).generate("prompt")

    assert output == valid_output()
    assert calls[0][0] == ["provider", "--offline"]
    assert calls[0][1]["input"] == "prompt"
    assert calls[0][1]["check"] is False


def test_command_provider_rejects_nonzero_exit(monkeypatch) -> None:
    class Result:
        returncode = 7
        stdout = ""

    monkeypatch.setattr(
        "hermes_screencast.demo.scenario_planner.subprocess.run",
        lambda *args, **kwargs: Result(),
    )

    with pytest.raises(ScenarioProviderError, match="exit code 7"):
        CommandScenarioProvider(("provider",)).generate("prompt")
