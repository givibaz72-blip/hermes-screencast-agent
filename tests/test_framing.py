from __future__ import annotations

import json

import pytest

from hermes_screencast.auto_zoom import apply_auto_zoom
from hermes_screencast.framing import (
    apply_framing_preset,
    available_framing_presets,
    build_framing_composition,
)
from hermes_screencast.project import create_hermes_project, load_hermes_project


def project_sources(tmp_path):
    video = tmp_path / "demo.mp4"
    events = tmp_path / "demo.events.json"
    script = tmp_path / "demo.json"
    video.write_bytes(b"fake mp4")
    events.write_text(
        json.dumps({
            "schema": "hermes.recording.events.v1",
            "metadata": {"width": 1920, "height": 1080},
            "events": [],
        }),
        encoding="utf-8",
    )
    script.write_text(
        json.dumps({
            "title": "Demo",
            "steps": [
                {"action": "goto", "url": "https://example.com"},
                {"action": "wait", "seconds": 1},
            ],
        }),
        encoding="utf-8",
    )
    return video, events, script


def create_project(tmp_path):
    root = tmp_path / "demo.hermes"
    video, events, script = project_sources(tmp_path)
    create_hermes_project(
        root,
        title="Demo",
        video_file=video,
        events_file=events,
        script_file=script,
        video_verifier=lambda path: path,
    )
    return root


def test_framing_presets_cover_source_studio_and_social_formats() -> None:
    assert available_framing_presets() == (
        "cinematic", "clean", "social-square", "social-vertical", "source", "studio"
    )
    studio = build_framing_composition("studio")
    assert studio["canvas"] == {
        "width": 1920, "height": 1080, "aspect_ratio": "16:9"
    }
    assert studio["background"]["type"] == "linear_gradient"
    assert studio["frame"]["padding"] == 96
    assert studio["frame"]["corner_radius"] == 24
    assert studio["frame"]["shadow"]["enabled"] is True


@pytest.mark.parametrize(("preset", "width", "height", "ratio"), [
    ("social-square", 1080, 1080, "1:1"),
    ("social-vertical", 1080, 1920, "9:16"),
    ("cinematic", 2560, 1080, "64:27"),
])
def test_framing_aspect_presets(preset, width, height, ratio) -> None:
    composition = build_framing_composition(preset)
    assert composition["canvas"] == {
        "width": width, "height": height, "aspect_ratio": ratio
    }


def test_framing_overrides_recompute_ratio_and_keep_contract() -> None:
    composition = build_framing_composition(
        "studio",
        background_color="#123456",
        padding=40,
        corner_radius=12,
        shadow_enabled=False,
        canvas_width=1200,
        canvas_height=1000,
    )
    assert composition["canvas"]["aspect_ratio"] == "6:5"
    assert composition["background"] == {"type": "color", "value": "#123456"}
    assert composition["frame"]["padding"] == 40
    assert composition["frame"]["corner_radius"] == 12
    assert composition["frame"]["shadow"]["enabled"] is False


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"background_color": "red"}, "color background"),
    ({"padding": 600}, "padding"),
    ({"corner_radius": 600}, "corner radius"),
    ({"canvas_width": 0}, "dimensions"),
])
def test_framing_rejects_invalid_overrides(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_framing_composition("social-square", **kwargs)


def test_framing_rejects_unknown_preset() -> None:
    with pytest.raises(ValueError, match="Unknown framing preset"):
        build_framing_composition("neon")


def test_apply_framing_preserves_timeline_and_is_idempotent(tmp_path) -> None:
    root = create_project(tmp_path)
    apply_auto_zoom(root)

    apply_framing_preset(root, preset="studio")
    apply_framing_preset(root, preset="social-square", padding=80)
    project = load_hermes_project(root)

    assert project.composition["preset"] == "social-square"
    assert project.composition["frame"]["padding"] == 80
    assert project.composition["canvas"]["aspect_ratio"] == "1:1"
    assert [track["id"] for track in project.timeline["tracks"]] == ["auto-zoom"]


def test_project_rejects_tampered_canvas_ratio(tmp_path) -> None:
    root = create_project(tmp_path)
    manifest = root / "project.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["composition"]["canvas"]["aspect_ratio"] = "4:3"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="aspect ratio"):
        load_hermes_project(root)


def test_project_loads_legacy_v1_composition(tmp_path) -> None:
    root = create_project(tmp_path)
    manifest = root / "project.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["composition"] = {
        "canvas": {"width": 1920, "height": 1080},
        "background": {"type": "color", "value": "#111827"},
        "frame": {"padding": 0, "corner_radius": 0, "shadow": False},
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    project = load_hermes_project(root)
    assert project.composition["preset"] == "legacy"
    assert project.composition["canvas"]["aspect_ratio"] == "16:9"
    assert project.composition["frame"]["shadow"]["enabled"] is False
