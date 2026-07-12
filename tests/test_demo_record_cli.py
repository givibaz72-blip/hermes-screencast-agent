from __future__ import annotations

import argparse
from pathlib import Path

import hermes_screencast.runner as runner


def test_run_demo_record_command_connects_loader_and_recorder(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    demo_json = tmp_path / "scenario.json"
    output = tmp_path / "result.mp4"
    script = object()

    loaded_paths: list[Path] = []
    recorded_calls: list[tuple[object, Path, str, str | None]] = []

    def fake_load_demo_script(path: Path):
        loaded_paths.append(path)
        return script

    def fake_record_demo_script(
        loaded_script,
        output_file: Path,
        *,
        profile: str,
        events_output_file: str | None,
    ) -> Path:
        recorded_calls.append(
            (loaded_script, output_file, profile, events_output_file)
        )
        return output_file.resolve()

    monkeypatch.setattr(
        runner,
        "load_demo_script",
        fake_load_demo_script,
    )
    monkeypatch.setattr(
        runner,
        "record_demo_script",
        fake_record_demo_script,
    )

    args = argparse.Namespace(
        demo_json=str(demo_json),
        output=str(output),
        profile="saas-demo",
        events_output=None,
    )

    result = runner.run_demo_record_command(args)

    assert loaded_paths == [demo_json]
    assert recorded_calls == [
        (script, output, "saas-demo", None),
    ]
    assert result == output.resolve()

    captured = capsys.readouterr()
    assert (
        f"Recording events written: {output.with_suffix('.events.json').resolve()}"
        in captured.out
    )
    assert f"✅ DemoScript recorded: {output.resolve()}" in captured.out
