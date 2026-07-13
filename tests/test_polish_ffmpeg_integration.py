from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from hermes_screencast.polish import polish_hermes_project
from hermes_screencast.project import create_hermes_project, load_hermes_project


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg integration tools are unavailable",
)


def test_real_ffmpeg_project_polish_pipeline(tmp_path) -> None:
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-nostdin", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(source),
    ], check=True)
    events = tmp_path / "events.json"
    events.write_text(json.dumps({
        "schema": "hermes.recording.events.v1",
        "metadata": {"width": 320, "height": 180},
        "events": [
            {"sequence": 0, "time_seconds": 0, "type": "recording_started"},
            {"sequence": 1, "time_seconds": 0.25, "type": "step_completed", "step_index": 0, "action": "click", "data": {"cursor": {"x": 80, "y": 70}, "target": {"x": 60, "y": 55, "width": 40, "height": 30}}},
            {"sequence": 2, "time_seconds": 0.7, "type": "step_completed", "step_index": 1, "action": "click", "data": {"cursor": {"x": 240, "y": 120}, "target": {"x": 220, "y": 105, "width": 40, "height": 30}}},
            {"sequence": 3, "time_seconds": 1, "type": "recording_finished"},
        ],
    }), encoding="utf-8")
    script = tmp_path / "script.json"
    script.write_text(json.dumps({
        "title": "Integration", "steps": [
            {"action": "goto", "url": "https://example.com"},
            {"action": "click", "selector": "#one"},
            {"action": "click", "selector": "#two"},
        ],
    }), encoding="utf-8")
    root = tmp_path / "integration.hermes"
    create_hermes_project(
        root, title="Integration", video_file=source,
        events_file=events, script_file=script,
    )
    manifest = root / "project.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["composition"]["canvas"] = {
        "width": 320, "height": 180, "aspect_ratio": "16:9",
    }
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    result = polish_hermes_project(
        root, tmp_path / "polished.mp4", preset="keep",
        encoder="software", quality="draft",
        fade_in_seconds=0.05, fade_out_seconds=0.05,
    )

    assert result.output.stat().st_size > 0
    assert result.preview.stat().st_size > 0
    assert result.zoom_segments >= 1
    assert result.cursor_segments >= 1
    project = load_hermes_project(root)
    assert [track["id"] for track in project.timeline["tracks"]] == [
        "auto-zoom", "cursor-motion", "auto-edit",
    ]
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
        "-of", "csv=p=0", str(result.output),
    ], capture_output=True, text=True, check=True)
    assert set(probe.stdout.split()) == {"video", "audio"}
