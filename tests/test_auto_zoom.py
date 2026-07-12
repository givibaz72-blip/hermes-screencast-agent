from __future__ import annotations

import json

import pytest

from hermes_screencast.auto_zoom import (
    AutoZoomSettings,
    apply_auto_zoom,
    build_auto_zoom_track,
)
from hermes_screencast.project import create_hermes_project, load_hermes_project


COMPOSITION = {"canvas": {"width": 1920, "height": 1080}}


def click_event(sequence, timestamp, x, y, width=100, height=40):
    return {
        "sequence": sequence,
        "time_seconds": timestamp,
        "type": "step_completed",
        "step_index": sequence,
        "action": "click",
        "data": {
            "target": {
                "selector": "#target",
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            },
            "state": {"viewport_width": 1920, "viewport_height": 1000},
        },
    }


def event_log(*events, duration=4.0):
    return {
        "schema": "hermes.recording.events.v1",
        "metadata": {
            "width": 1920,
            "height": 1080,
            "browser_ui": "visible",
        },
        "events": [
            {"sequence": 0, "time_seconds": 0, "type": "recording_started"},
            *events,
            {
                "sequence": 99,
                "time_seconds": duration,
                "type": "recording_finished",
                "data": {"success": True},
            },
        ],
    }


def test_build_auto_zoom_track_centers_and_clamps_click_target() -> None:
    track = build_auto_zoom_track(
        event_log(click_event(1, 1.0, 900, 400)),
        composition=COMPOSITION,
    )

    assert track["id"] == "auto-zoom"
    assert track["type"] == "camera.zoom"
    assert len(track["segments"]) == 1
    segment = track["segments"][0]
    assert segment == {
        "start_seconds": 0.75,
        "focus_seconds": 1.0,
        "hold_until_seconds": 1.65,
        "end_seconds": 2.0,
        "scale": 1.35,
        "focus": {"x": 950.0, "y": 500.0},
        "source_event_sequences": [1],
    }


def test_auto_zoom_merges_nearby_overlapping_clicks() -> None:
    track = build_auto_zoom_track(
        event_log(
            click_event(1, 1.0, 900, 400),
            click_event(2, 1.3, 940, 420),
        ),
        composition=COMPOSITION,
    )

    assert len(track["segments"]) == 1
    segment = track["segments"][0]
    assert segment["source_event_sequences"] == [1, 2]
    assert segment["focus"] == {"x": 970.0, "y": 510.0}
    assert segment["end_seconds"] == 2.3


def test_auto_zoom_splits_overlapping_distant_clicks_at_midpoint() -> None:
    track = build_auto_zoom_track(
        event_log(
            click_event(1, 1.0, 100, 400),
            click_event(2, 1.2, 1700, 400),
        ),
        composition=COMPOSITION,
    )

    first, second = track["segments"]
    assert first["end_seconds"] == pytest.approx(1.1)
    assert second["start_seconds"] == pytest.approx(1.1)
    assert first["source_event_sequences"] == [1]
    assert second["source_event_sequences"] == [2]


def test_auto_zoom_reduces_scale_to_keep_large_target_visible() -> None:
    track = build_auto_zoom_track(
        event_log(click_event(1, 1.0, 0, 0, width=1900, height=1000)),
        composition=COMPOSITION,
    )

    assert track["segments"][0]["scale"] == 1.0


def test_auto_zoom_skips_click_without_safe_geometry() -> None:
    incomplete = click_event(1, 1.0, 100, 100)
    del incomplete["data"]["target"]["width"]
    track = build_auto_zoom_track(event_log(incomplete), composition=COMPOSITION)
    assert track["segments"] == []


def test_auto_zoom_requires_synchronized_event_schema() -> None:
    payload = event_log(click_event(1, 1.0, 100, 100))
    payload["schema"] = "legacy.events"
    with pytest.raises(ValueError, match="recording event log"):
        build_auto_zoom_track(payload, composition=COMPOSITION)


def test_apply_auto_zoom_replaces_track_idempotently(tmp_path) -> None:
    root = tmp_path / "demo.hermes"
    video = tmp_path / "demo.mp4"
    events = tmp_path / "demo.events.json"
    script = tmp_path / "demo.json"
    video.write_bytes(b"fake mp4")
    events.write_text(
        json.dumps(event_log(click_event(1, 1.0, 900, 400))), encoding="utf-8"
    )
    script.write_text(
        json.dumps({
            "title": "Demo",
            "steps": [
                {"action": "goto", "url": "https://example.com"},
                {"action": "click", "selector": "#target"},
            ],
        }),
        encoding="utf-8",
    )
    create_hermes_project(
        root,
        title="Demo",
        video_file=video,
        events_file=events,
        script_file=script,
        video_verifier=lambda path: path,
    )

    apply_auto_zoom(root, settings=AutoZoomSettings(scale=1.25))
    apply_auto_zoom(root, settings=AutoZoomSettings(scale=1.4))
    project = load_hermes_project(root)

    assert len(project.timeline["tracks"]) == 1
    assert project.timeline["tracks"][0]["settings"]["scale"] == 1.4
    assert project.timeline["tracks"][0]["segments"][0]["scale"] == 1.4


@pytest.mark.parametrize("value", [0.9, -1, float("inf")])
def test_auto_zoom_rejects_invalid_scale(value) -> None:
    with pytest.raises(ValueError, match="scale"):
        build_auto_zoom_track(
            event_log(click_event(1, 1.0, 900, 400)),
            composition=COMPOSITION,
            settings=AutoZoomSettings(scale=value),
        )
