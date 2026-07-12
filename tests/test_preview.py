from __future__ import annotations

import json

from hermes_screencast.annotations import add_project_annotation
from hermes_screencast.auto_edit import apply_auto_edit
from hermes_screencast.auto_zoom import apply_auto_zoom
from hermes_screencast.cursor_motion import apply_cursor_motion
from hermes_screencast.framing import apply_framing_preset
from hermes_screencast.preview import build_project_preview_model, write_project_preview
from hermes_screencast.project import create_hermes_project


def create_rich_project(tmp_path, title="Product demo"):
    root = tmp_path / "demo.hermes"
    video = tmp_path / "demo.mp4"
    events = tmp_path / "demo.events.json"
    script = tmp_path / "demo.json"
    video.write_bytes(b"fake mp4")
    event_payload = {
        "schema": "hermes.recording.events.v1",
        "metadata": {
            "width": 1920, "height": 1080, "browser_ui": "content_only"
        },
        "events": [
            {"sequence": 0, "time_seconds": 0, "type": "recording_started"},
            {
                "sequence": 1, "time_seconds": 0.5, "type": "step_started",
                "step_index": 0, "action": "click",
            },
            {
                "sequence": 2, "time_seconds": 0.8, "type": "step_completed",
                "step_index": 0, "action": "click",
                "data": {
                    "target": {"x": 300, "y": 200, "width": 120, "height": 40},
                    "cursor": {"x": 360, "y": 220},
                    "state": {"viewport_width": 1920, "viewport_height": 1080},
                },
            },
            {
                "sequence": 3, "time_seconds": 6.0, "type": "step_started",
                "step_index": 1, "action": "click",
            },
            {
                "sequence": 4, "time_seconds": 6.3, "type": "step_completed",
                "step_index": 1, "action": "click",
                "data": {
                    "target": {"x": 1200, "y": 600, "width": 160, "height": 60},
                    "cursor": {"x": 1280, "y": 630},
                    "state": {"viewport_width": 1920, "viewport_height": 1080},
                },
            },
            {"sequence": 5, "time_seconds": 8.0, "type": "recording_finished"},
        ],
    }
    events.write_text(json.dumps(event_payload), encoding="utf-8")
    script.write_text(
        json.dumps({
            "title": "Demo",
            "steps": [
                {"action": "goto", "url": "https://example.com"},
                {"action": "click", "selector": "#one"},
                {"action": "click", "selector": "#two"},
            ],
        }),
        encoding="utf-8",
    )
    create_hermes_project(
        root,
        title=title,
        video_file=video,
        events_file=events,
        script_file=script,
        video_verifier=lambda path: path,
    )
    apply_auto_zoom(root)
    apply_cursor_motion(root)
    apply_framing_preset(root, preset="studio")
    add_project_annotation(
        root, kind="text", start_seconds=1, end_seconds=3,
        x=100, y=80, text="Key action",
    )
    apply_auto_edit(root)
    return root


def test_preview_model_combines_all_project_tracks(tmp_path) -> None:
    root = create_rich_project(tmp_path)
    model = build_project_preview_model(root)

    assert model["schema"] == "hermes.preview.v1"
    assert model["title"] == "Product demo"
    assert model["source_duration_seconds"] == 8.0
    assert model["estimated_duration_seconds"] < 8.0
    assert model["composition"]["preset"] == "studio"
    assert [track["type"] for track in model["tracks"]] == [
        "camera.zoom", "cursor.motion", "annotation.overlay", "time.edit"
    ]
    assert model["tracks"][0]["segments"][0]["label"] == "1.35x zoom"
    assert model["tracks"][2]["segments"][0]["label"] == "text: annotation-001"


def test_write_preview_is_self_contained_and_readable(tmp_path) -> None:
    root = create_rich_project(tmp_path)
    output = write_project_preview(root, tmp_path / "preview.html")
    markup = output.read_text(encoding="utf-8")

    assert output == tmp_path / "preview.html"
    assert "<!doctype html>" in markup
    assert "Product demo · Hermes preview" in markup
    assert "HermesProject preview" in markup
    assert "camera.zoom" in markup
    assert "cursor-motion" in markup
    assert "cut: idle_gap" in markup
    assert 'type="application/json"' in markup
    assert "https://" not in markup
    assert "<input id=\"scrubber\"" in markup


def test_preview_defaults_inside_project_directory(tmp_path) -> None:
    root = create_rich_project(tmp_path)
    assert write_project_preview(root) == root / "preview.html"
    assert (root / "preview.html").is_file()


def test_preview_escapes_untrusted_project_text(tmp_path) -> None:
    title = "</script><script>alert('x')</script>"
    root = create_rich_project(tmp_path, title=title)
    markup = write_project_preview(root).read_text(encoding="utf-8")

    assert title not in markup
    assert "&lt;/script&gt;&lt;script&gt;" in markup
    assert "\\u003c/script>" in markup

