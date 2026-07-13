from __future__ import annotations

import argparse
import json
from pathlib import Path

import hermes_screencast.runner as runner


class FakeProduceResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)


def test_demo_produce_command_connects_cli_to_workflow(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    scenario = tmp_path / "scenario.txt"
    preferences = tmp_path / "preferences.json"
    output = tmp_path / "final.mp4"
    workspace = tmp_path / "final-work"

    scenario.write_text(
        "Open the page and explain the main action.",
        encoding="utf-8",
    )
    preferences.write_text(
        json.dumps({
            "browser_ui": "content_only",
        }),
        encoding="utf-8",
    )

    calls = []
    expected_payload = {
        "output": str(output.resolve()),
        "workspace": str(workspace.resolve()),
        "zoom_segments": 2,
        "cursor_segments": 3,
        "edit_segments": 4,
    }

    def fake_produce(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProduceResult(expected_payload)

    monkeypatch.setattr(
        runner,
        "produce_screencast",
        fake_produce,
    )

    args = argparse.Namespace(
        scenario=str(scenario),
        target_url="https://example.com",
        provider_command="provider-wrapper",
        provider_arg=["--model", "local"],
        output=str(output),
        work_directory=str(workspace),
        title="Product demo",
        preferences=str(preferences),
        constraint=["Do not submit forms"],
        profile="product-demo",
        visible_discovery=False,
        max_elements=500,
        preset="cinematic",
        encoder="software",
        quality="archive",
        fade_in=0.3,
        fade_out=0.4,
        no_normalize_audio=True,
    )

    result = runner.run_demo_produce_command(args)

    assert result.to_dict() == expected_payload
    assert len(calls) == 1

    positional, keyword = calls[0]

    assert positional == (
        str(scenario),
        "https://example.com",
        (
            "provider-wrapper",
            "--model",
            "local",
        ),
        str(output),
    )
    assert keyword == {
        "work_directory": str(workspace),
        "title": "Product demo",
        "preferences": {
            "browser_ui": "content_only",
        },
        "constraints": ("Do not submit forms",),
        "profile": "product-demo",
        "discovery_headless": True,
        "max_elements": 500,
        "preset": "cinematic",
        "encoder": "software",
        "quality": "archive",
        "fade_in_seconds": 0.3,
        "fade_out_seconds": 0.4,
        "normalize_audio": False,
    }

    printed = json.loads(capsys.readouterr().out)
    assert printed == expected_payload
