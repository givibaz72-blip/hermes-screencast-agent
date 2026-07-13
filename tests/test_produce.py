from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_screencast.polish import PolishResult
from hermes_screencast.produce import produce_screencast


class FakeRuntime:
    instances: list["FakeRuntime"] = []

    def __init__(self, *, config):
        self.config = config
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeReport:
    def to_dict(self):
        return {
            "schema": "hermes.discovery.v1",
            "url": "https://example.com",
            "title": "Example",
            "summary": {
                "total": 1,
                "included": 1,
                "truncated": False,
            },
            "elements": [],
            "ambiguities": [],
        }


class FakeDiscovery:
    calls: list[tuple[str, int]] = []

    def __init__(self, *, runtime):
        self.runtime = runtime

    def discover(self, url, *, max_elements):
        self.__class__.calls.append((url, max_elements))
        return FakeReport()


class FakeProvider:
    commands: list[tuple[str, ...]] = []

    def __init__(self, command):
        self.__class__.commands.append(tuple(command))

    def generate(self, prompt):
        assert '"schema": "hermes.discovery.v1"' in prompt
        return json.dumps({
            "title": "Generated demo",
            "steps": [
                {
                    "action": "goto",
                    "url": "https://example.com",
                },
                {
                    "action": "click",
                    "selector": "#primary-action",
                },
            ],
        })


def test_produce_screencast_runs_complete_existing_pipeline(
    tmp_path: Path,
) -> None:
    FakeRuntime.instances.clear()
    FakeDiscovery.calls.clear()
    FakeProvider.commands.clear()

    scenario = tmp_path / "scenario.txt"
    output = tmp_path / "delivery" / "final.mp4"
    scenario.write_text(
        "Open the page and click the primary action.",
        encoding="utf-8",
    )

    recorded_calls = []
    project_calls = []
    polish_calls = []

    def fake_recorder(
        script,
        output_file,
        *,
        profile,
        events_output_file,
    ):
        recorded_calls.append((
            script.title,
            Path(output_file),
            profile,
            Path(events_output_file),
        ))
        Path(output_file).write_bytes(b"recording")
        Path(events_output_file).write_text(
            json.dumps({
                "schema": "hermes.recording.events.v1",
                "metadata": {
                    "width": 1920,
                    "height": 1080,
                },
                "events": [],
            }),
            encoding="utf-8",
        )
        return Path(output_file).resolve()

    def fake_project_creator(
        project_directory,
        *,
        title,
        video_file,
        events_file,
        script_file,
    ):
        project_calls.append((
            Path(project_directory),
            title,
            Path(video_file),
            Path(events_file),
            Path(script_file),
        ))
        root = Path(project_directory)
        root.mkdir()
        (root / "project.json").write_text(
            "{}",
            encoding="utf-8",
        )
        return root.resolve()

    def fake_polisher(
        project_directory,
        output_file,
        *,
        preview_file,
        preset,
        encoder,
        quality,
        fade_in_seconds,
        fade_out_seconds,
        normalize_audio,
    ):
        polish_calls.append((
            Path(project_directory),
            Path(output_file),
            Path(preview_file),
            preset,
            encoder,
            quality,
            fade_in_seconds,
            fade_out_seconds,
            normalize_audio,
        ))
        output_path = Path(output_file).resolve()
        preview_path = Path(preview_file).resolve()
        output_path.write_bytes(b"final")
        preview_path.write_text(
            "<html></html>",
            encoding="utf-8",
        )
        return PolishResult(
            project=Path(project_directory).resolve(),
            output=output_path,
            preview=preview_path,
            zoom_segments=2,
            cursor_segments=3,
            edit_segments=4,
        )

    result = produce_screencast(
        scenario,
        "https://example.com",
        ("provider-wrapper", "--model", "local"),
        output,
        title="Requested title",
        constraints=("Do not submit forms",),
        runtime_factory=FakeRuntime,
        discovery_factory=FakeDiscovery,
        provider_factory=FakeProvider,
        recorder=fake_recorder,
        project_creator=fake_project_creator,
        polisher=fake_polisher,
    )

    workspace = output.parent / "final.work"

    assert result.workspace == workspace.resolve()
    assert result.discovery == workspace.resolve() / "discovery.json"
    assert result.script == workspace.resolve() / "demo.json"
    assert result.recording == workspace.resolve() / "recording.mp4"
    assert result.events == workspace.resolve() / "recording.events.json"
    assert result.project == workspace.resolve() / "project.hermes"
    assert result.output == output.resolve()
    assert result.preview == output.with_suffix(".preview.html").resolve()
    assert result.zoom_segments == 2
    assert result.cursor_segments == 3
    assert result.edit_segments == 4

    assert FakeRuntime.instances[0].config.profile == (
        "demo-produce-discovery"
    )
    assert FakeRuntime.instances[0].config.headless is True
    assert FakeDiscovery.calls == [
        ("https://example.com", 250),
    ]
    assert FakeProvider.commands == [
        ("provider-wrapper", "--model", "local"),
    ]

    assert recorded_calls[0][0] == "Requested title"
    assert recorded_calls[0][2] == "demo-produce"
    assert project_calls[0][1] == "Requested title"
    assert polish_calls[0][3:6] == (
        "studio",
        "auto",
        "high",
    )

    manifest = json.loads(
        result.result_manifest.read_text(encoding="utf-8")
    )
    assert manifest == result.to_dict()

    generated_script = json.loads(
        result.script.read_text(encoding="utf-8")
    )
    assert generated_script["title"] == "Requested title"
    assert generated_script["steps"][1] == {
        "action": "click",
        "selector": "#primary-action",
    }


@pytest.mark.parametrize(
    "existing_name",
    (
        "workspace",
        "output",
        "preview",
    ),
)
def test_produce_screencast_refuses_to_overwrite_existing_work(
    tmp_path: Path,
    existing_name: str,
) -> None:
    scenario = tmp_path / "scenario.txt"
    output = tmp_path / "final.mp4"
    workspace = tmp_path / "custom-work"
    preview = output.with_suffix(".preview.html")
    scenario.write_text("Record a demo.", encoding="utf-8")

    if existing_name == "workspace":
        workspace.mkdir()
    elif existing_name == "output":
        output.write_bytes(b"existing")
    else:
        preview.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError, match="will not overwrite"):
        produce_screencast(
            scenario,
            "https://example.com",
            ("provider",),
            output,
            work_directory=workspace,
            runtime_factory=FakeRuntime,
            discovery_factory=FakeDiscovery,
            provider_factory=FakeProvider,
        )


@pytest.mark.parametrize(
    (
        "workspace_relative",
        "output_relative",
    ),
    (
        (
            "work",
            "work/final.mp4",
        ),
        (
            "final.mp4/work",
            "final.mp4",
        ),
        (
            "final.mp4",
            "final.mp4",
        ),
        (
            "final.preview.html",
            "final.mp4",
        ),
    ),
)
def test_produce_screencast_rejects_overlapping_artifact_paths(
    tmp_path: Path,
    workspace_relative: str,
    output_relative: str,
) -> None:
    scenario = tmp_path / "scenario.txt"
    workspace = tmp_path / workspace_relative
    output = tmp_path / output_relative
    preview = output.with_suffix(".preview.html")
    scenario.write_text(
        "Record a demo.",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="artifact paths must not overlap",
    ):
        produce_screencast(
            scenario,
            "https://example.com",
            ("provider",),
            output,
            work_directory=workspace,
        )

    assert not workspace.exists()
    assert not output.exists()
    assert not preview.exists()


def test_produce_screencast_requires_mp4_output(
    tmp_path: Path,
) -> None:
    scenario = tmp_path / "scenario.txt"
    scenario.write_text("Record a demo.", encoding="utf-8")

    with pytest.raises(ValueError, match=".mp4"):
        produce_screencast(
            scenario,
            "https://example.com",
            ("provider",),
            tmp_path / "final.mov",
        )
