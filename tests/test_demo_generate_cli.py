from __future__ import annotations

import argparse
import json

from hermes_screencast import runner


class FakeProvider:
    def __init__(self, command) -> None:
        self.command = command

    def generate(self, prompt: str) -> str:
        assert "Open the product page" in prompt
        return json.dumps(
            {
                "title": "Product demo",
                "target": {"kind": "web", "url": "https://example.com"},
                "preferences": {"pacing": "professional"},
                "metadata": {"schema": "hermes.demo.v1"},
                "steps": [
                    {"action": "goto", "url": "https://example.com"},
                    {"action": "highlight", "selector": "h1"},
                ],
            }
        )


def test_demo_generate_writes_deterministic_validated_json(tmp_path, monkeypatch) -> None:
    scenario_path = tmp_path / "scenario.txt"
    preferences_path = tmp_path / "preferences.json"
    output_path = tmp_path / "generated.json"
    scenario_path.write_text("Open the product page", encoding="utf-8")
    preferences_path.write_text(
        json.dumps({"pacing": "professional"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "CommandScenarioProvider", FakeProvider)
    args = argparse.Namespace(
        scenario=str(scenario_path),
        output=str(output_path),
        provider_command="fake-provider",
        provider_arg=["--offline"],
        target_url="https://example.com",
        title="Product demo",
        preferences=str(preferences_path),
        constraint=["Do not submit forms"],
    )

    result = runner.run_demo_generate_command(args)

    assert result == output_path.resolve()
    assert output_path.read_text(encoding="utf-8").endswith("\n")
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["title"] == "Product demo"
    assert payload["steps"] == [
        {"action": "goto", "url": "https://example.com"},
        {"action": "highlight", "selector": "h1"},
    ]


def test_demo_generate_rejects_non_object_preferences(tmp_path) -> None:
    scenario_path = tmp_path / "scenario.txt"
    preferences_path = tmp_path / "preferences.json"
    scenario_path.write_text("Show the page", encoding="utf-8")
    preferences_path.write_text("[]", encoding="utf-8")
    args = argparse.Namespace(
        scenario=str(scenario_path),
        output=str(tmp_path / "generated.json"),
        provider_command="fake-provider",
        provider_arg=[],
        target_url=None,
        title=None,
        preferences=str(preferences_path),
        constraint=[],
    )

    try:
        runner.run_demo_generate_command(args)
    except ValueError as exc:
        assert str(exc) == "Preferences JSON root must be an object"
    else:
        raise AssertionError("Expected invalid preferences to fail")
