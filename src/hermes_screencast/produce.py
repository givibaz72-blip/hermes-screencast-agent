from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from hermes_screencast.browser.runtime import (
    BrowserRuntime,
    BrowserRuntimeConfig,
)
from hermes_screencast.demo.discovery import PageDiscoveryService
from hermes_screencast.demo.json_loader import demo_script_to_dict
from hermes_screencast.demo.recording import record_demo_script
from hermes_screencast.demo.scenario_planner import (
    CommandScenarioProvider,
    ScenarioPlanner,
    ScenarioPlanningRequest,
)
from hermes_screencast.demo.script import DemoScript
from hermes_screencast.polish import PolishResult, polish_hermes_project
from hermes_screencast.project import create_hermes_project


@dataclass(frozen=True)
class ProduceResult:
    workspace: Path
    discovery: Path
    script: Path
    recording: Path
    events: Path
    project: Path
    output: Path
    preview: Path
    result_manifest: Path
    zoom_segments: int
    cursor_segments: int
    edit_segments: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "discovery": str(self.discovery),
            "script": str(self.script),
            "recording": str(self.recording),
            "events": str(self.events),
            "project": str(self.project),
            "output": str(self.output),
            "preview": str(self.preview),
            "result_manifest": str(self.result_manifest),
            "zoom_segments": self.zoom_segments,
            "cursor_segments": self.cursor_segments,
            "edit_segments": self.edit_segments,
        }


def produce_screencast(
    scenario_file: str | Path,
    target_url: str,
    provider_command: Sequence[str],
    output_file: str | Path,
    *,
    work_directory: str | Path | None = None,
    title: str | None = None,
    preferences: dict[str, Any] | None = None,
    constraints: Sequence[str] = (),
    profile: str = "demo-produce",
    discovery_headless: bool = True,
    max_elements: int = 250,
    preset: str = "studio",
    encoder: str = "auto",
    quality: str = "high",
    fade_in_seconds: float = 0.2,
    fade_out_seconds: float = 0.25,
    normalize_audio: bool = True,
    runtime_factory: Callable[..., Any] = BrowserRuntime,
    discovery_factory: Callable[..., Any] = PageDiscoveryService,
    provider_factory: Callable[[Sequence[str]], Any] = CommandScenarioProvider,
    recorder: Callable[..., Path] = record_demo_script,
    project_creator: Callable[..., Path] = create_hermes_project,
    polisher: Callable[..., PolishResult] = polish_hermes_project,
) -> ProduceResult:
    scenario = Path(scenario_file).expanduser().resolve()
    output = Path(output_file).expanduser().resolve()

    if not scenario.is_file():
        raise FileNotFoundError(scenario)
    if output.suffix.lower() != ".mp4":
        raise ValueError("Produced screencast output must use .mp4 extension")
    if not provider_command:
        raise ValueError("Provider command cannot be empty")
    if max_elements <= 0:
        raise ValueError("Discovery max elements must be positive")

    workspace = (
        Path(work_directory).expanduser().resolve()
        if work_directory is not None
        else output.with_name(f"{output.stem}.work")
    )
    preview = output.with_suffix(".preview.html")

    _reject_overlapping_artifact_paths(
        workspace,
        output,
        preview,
    )
    _reject_existing_outputs(workspace, output, preview)

    discovery_path = workspace / "discovery.json"
    script_path = workspace / "demo.json"
    recording_path = workspace / "recording.mp4"
    events_path = workspace / "recording.events.json"
    project_path = workspace / "project.hermes"
    result_path = workspace / "result.json"

    output.parent.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=False)

    discovery_config = BrowserRuntimeConfig(
        profile=f"{profile}-discovery",
        headless=discovery_headless,
    )
    with runtime_factory(config=discovery_config) as runtime:
        report = discovery_factory(runtime=runtime).discover(
            target_url,
            max_elements=max_elements,
        )

    discovery_payload = report.to_dict()
    discovery_path.write_text(
        json.dumps(
            discovery_payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    request = ScenarioPlanningRequest(
        scenario=scenario.read_text(encoding="utf-8"),
        target_url=target_url,
        title=title,
        preferences=dict(preferences or {}),
        constraints=tuple(constraints),
        discovery=discovery_payload,
    )
    provider = provider_factory(tuple(provider_command))
    script = ScenarioPlanner(provider=provider).plan(request)
    _write_demo_script(script_path, script)

    recorder(
        script,
        recording_path,
        profile=profile,
        events_output_file=events_path,
    )

    project_creator(
        project_path,
        title=script.title,
        video_file=recording_path,
        events_file=events_path,
        script_file=script_path,
    )

    polished = polisher(
        project_path,
        output,
        preview_file=preview,
        preset=preset,
        encoder=encoder,
        quality=quality,
        fade_in_seconds=fade_in_seconds,
        fade_out_seconds=fade_out_seconds,
        normalize_audio=normalize_audio,
    )

    result = ProduceResult(
        workspace=workspace,
        discovery=discovery_path,
        script=script_path,
        recording=recording_path,
        events=events_path,
        project=project_path,
        output=polished.output,
        preview=polished.preview,
        result_manifest=result_path,
        zoom_segments=polished.zoom_segments,
        cursor_segments=polished.cursor_segments,
        edit_segments=polished.edit_segments,
    )
    result_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _reject_overlapping_artifact_paths(
    workspace: Path,
    output: Path,
    preview: Path,
) -> None:
    artifacts = (
        ("workspace", workspace),
        ("output", output),
        ("preview", preview),
    )

    for index, (left_name, left_path) in enumerate(artifacts):
        for right_name, right_path in artifacts[index + 1:]:
            overlaps = (
                left_path == right_path
                or left_path in right_path.parents
                or right_path in left_path.parents
            )
            if overlaps:
                raise ValueError(
                    "Demo production artifact paths must not overlap: "
                    f"{left_name}={left_path}, "
                    f"{right_name}={right_path}"
                )


def _reject_existing_outputs(
    workspace: Path,
    output: Path,
    preview: Path,
) -> None:
    existing = [
        path
        for path in (workspace, output, preview)
        if path.exists()
    ]
    if existing:
        joined = ", ".join(str(path) for path in existing)
        raise FileExistsError(
            f"Demo production will not overwrite existing paths: {joined}"
        )


def _write_demo_script(path: Path, script: DemoScript) -> None:
    path.write_text(
        json.dumps(
            demo_script_to_dict(script),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
