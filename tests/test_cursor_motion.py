from __future__ import annotations

import json

import pytest

from hermes_screencast.auto_zoom import apply_auto_zoom
from hermes_screencast.cursor_motion import (
    CursorMotionSettings,
    apply_cursor_motion,
    build_cursor_motion_track,
)
from hermes_screencast.project import (
    create_hermes_project,
    load_hermes_project,
    validate_project_timeline,
)


COMPOSITION = {"canvas": {"width": 1920, "height": 1080}}


def cursor_event(sequence, timestamp, x, y, action="click"):
    return {
        "sequence": sequence,
        "time_seconds": timestamp,
        "type": "step_completed",
        "step_index": sequence,
        "action": action,
        "data": {
            "cursor": {"x": x, "y": y},
            "target": {
                "selector": "#target", "x": x - 20, "y": y - 10,
                "width": 40, "height": 20,
            },
            "state": {"viewport_width": 1920, "viewport_height": 1000},
        },
    }


def event_log(*events):
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
                "time_seconds": 4,
                "type": "recording_finished",
                "data": {"success": True},
            },
        ],
    }


def test_cursor_motion_builds_timed_bezier_segment() -> None:
    track = build_cursor_motion_track(
        event_log(
            cursor_event(1, 1.0, 100, 200),
            cursor_event(2, 2.0, 500, 400, action="hover"),
        ),
        composition=COMPOSITION,
    )

    assert track["id"] == "cursor-motion"
    assert track["type"] == "cursor.motion"
    assert track["anchors"] == [
        {
            "time_seconds": 1.0,
            "position": {"x": 100.0, "y": 280.0},
            "action": "click",
            "source_event_sequence": 1,
        },
        {
            "time_seconds": 2.0,
            "position": {"x": 500.0, "y": 480.0},
            "action": "hover",
            "source_event_sequence": 2,
        },
    ]
    segment = track["segments"][0]
    assert segment["start_seconds"] == pytest.approx(1.620562, abs=1e-6)
    assert segment["end_seconds"] == 1.94
    assert segment["arrival_seconds"] == 2.0
    assert segment["from"] == {"x": 100.0, "y": 280.0}
    assert segment["to"] == {"x": 500.0, "y": 480.0}
    assert segment["control_1"] == {"x": 140.0, "y": 300.0}
    assert segment["control_2"] == {"x": 460.0, "y": 460.0}
    assert segment["source_event_sequences"] == [1, 2]


def test_cursor_motion_uses_neighboring_anchors_for_smooth_tangents() -> None:
    track = build_cursor_motion_track(
        event_log(
            cursor_event(1, 1.0, 100, 200),
            cursor_event(2, 2.0, 500, 400),
            cursor_event(3, 3.0, 900, 100),
        ),
        composition=COMPOSITION,
    )

    first, second = track["segments"]
    assert first["control_2"] == {"x": 420.0, "y": 490.0}
    assert second["control_1"] == {"x": 580.0, "y": 470.0}


def test_cursor_motion_fits_short_interaction_interval() -> None:
    track = build_cursor_motion_track(
        event_log(
            cursor_event(1, 1.0, 100, 200),
            cursor_event(2, 1.05, 900, 600),
        ),
        composition=COMPOSITION,
    )

    segment = track["segments"][0]
    assert segment["start_seconds"] == 1.0
    assert segment["end_seconds"] == pytest.approx(1.033333, abs=1e-6)
    assert segment["arrival_seconds"] == 1.05


def test_cursor_motion_clamps_positions_to_video_frame() -> None:
    track = build_cursor_motion_track(
        event_log(cursor_event(1, 1.0, -10, 1050)),
        composition=COMPOSITION,
    )
    assert track["anchors"][0]["position"] == {"x": 0.0, "y": 1080.0}


def test_cursor_motion_skips_events_without_cursor_geometry() -> None:
    event = cursor_event(1, 1.0, 100, 100)
    del event["data"]["cursor"]
    track = build_cursor_motion_track(event_log(event), composition=COMPOSITION)
    assert track["anchors"] == []
    assert track["segments"] == []


def test_cursor_motion_requires_synchronized_event_schema() -> None:
    payload = event_log(cursor_event(1, 1.0, 100, 100))
    payload["schema"] = "legacy.events"
    with pytest.raises(ValueError, match="recording event log"):
        build_cursor_motion_track(payload, composition=COMPOSITION)


def test_project_timeline_rejects_cursor_point_outside_frame_contract() -> None:
    track = build_cursor_motion_track(
        event_log(
            cursor_event(1, 1.0, 100, 200),
            cursor_event(2, 2.0, 500, 400),
        ),
        composition=COMPOSITION,
    )
    track["segments"][0]["control_1"]["x"] = -1
    with pytest.raises(ValueError, match="cursor point"):
        validate_project_timeline({"tracks": [track]})


def test_cursor_motion_coexists_with_zoom_and_replaces_itself(tmp_path) -> None:
    root = tmp_path / "demo.hermes"
    video = tmp_path / "demo.mp4"
    events = tmp_path / "demo.events.json"
    script = tmp_path / "demo.json"
    video.write_bytes(b"fake mp4")
    events.write_text(
        json.dumps(event_log(
            cursor_event(1, 1.0, 100, 200),
            cursor_event(2, 2.0, 500, 400),
        )),
        encoding="utf-8",
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

    apply_auto_zoom(root)
    apply_cursor_motion(root, settings=CursorMotionSettings(tension=0.4))
    apply_cursor_motion(root, settings=CursorMotionSettings(tension=0.8))
    project = load_hermes_project(root)

    assert [track["id"] for track in project.timeline["tracks"]] == [
        "auto-zoom", "cursor-motion"
    ]
    assert project.timeline["tracks"][1]["settings"]["tension"] == 0.8


@pytest.mark.parametrize("settings", [
    CursorMotionSettings(speed_pixels_per_second=0),
    CursorMotionSettings(minimum_move_seconds=1, maximum_move_seconds=0.5),
    CursorMotionSettings(tension=1.1),
])
def test_cursor_motion_rejects_invalid_settings(settings) -> None:
    with pytest.raises(ValueError):
        build_cursor_motion_track(
            event_log(cursor_event(1, 1.0, 100, 100)),
            composition=COMPOSITION,
            settings=settings,
        )
