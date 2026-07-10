from __future__ import annotations

import json

import pytest

from hermes_screencast.demo.json_loader import demo_script_from_dict, load_demo_script
from hermes_screencast.demo.script import DemoActionType


def test_load_demo_script_from_json_file(tmp_path) -> None:
    path = tmp_path / "demo.json"
    path.write_text(
        json.dumps(
            {
                "title": "JSON demo",
                "steps": [
                    {"action": "goto", "url": "https://example.com"},
                    {"action": "wait", "seconds": 1},
                    {"action": "narration", "text": "Hello from JSON"},
                    {"action": "highlight", "selector": "h1"},
                    {"action": "scroll", "value": 250},
                ],
            }
        ),
        encoding="utf-8",
    )

    script = load_demo_script(path)

    assert script.title == "JSON demo"
    assert len(script.steps) == 5
    assert script.steps[0].action == DemoActionType.GOTO
    assert script.steps[0].url == "https://example.com"
    assert script.steps[2].text == "Hello from JSON"
    assert script.steps[3].selector == "h1"
    assert script.steps[4].value == 250


def test_demo_script_from_dict_rejects_missing_title() -> None:
    with pytest.raises(ValueError, match="requires string field: title"):
        demo_script_from_dict(
            {
                "steps": [
                    {"action": "goto", "url": "https://example.com"},
                ],
            }
        )


def test_demo_script_from_dict_rejects_missing_steps() -> None:
    with pytest.raises(ValueError, match="requires list field: steps"):
        demo_script_from_dict(
            {
                "title": "Missing steps",
            }
        )


def test_demo_script_from_dict_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="unsupported action"):
        demo_script_from_dict(
            {
                "title": "Bad action",
                "steps": [
                    {"action": "unknown"},
                ],
            }
        )


def test_demo_script_from_dict_rejects_unknown_step_field() -> None:
    with pytest.raises(ValueError, match="unknown field"):
        demo_script_from_dict(
            {
                "title": "Unknown field",
                "steps": [
                    {
                        "action": "goto",
                        "url": "https://example.com",
                        "unexpected": True,
                    },
                ],
            }
        )


def test_demo_script_from_dict_runs_model_validation() -> None:
    with pytest.raises(ValueError, match="click requires selector"):
        demo_script_from_dict(
            {
                "title": "Invalid model",
                "steps": [
                    {"action": "click"},
                ],
            }
        )
