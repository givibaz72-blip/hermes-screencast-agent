from __future__ import annotations

import json

import pytest

from hermes_screencast.auto_edit import (
    AutoEditSettings,
    apply_auto_edit,
    build_auto_edit_track,
)
from hermes_screencast.auto_zoom import apply_auto_zoom
from hermes_screencast.project import create_hermes_project, load_hermes_project


def event(sequence, timestamp, event_type, *, action=None, step_index=None):
    payload = {"sequence": sequence, "time_seconds": timestamp, "type": event_type}
    if action is not None:
        payload["action"] = action
    if step_index is not None:
        payload["step_index"] = step_index
    return payload


def event_log(events):
    return {
        "schema": "hermes.recording.events.v1",
        "metadata": {"width": 1920, "height": 1080},
        "events": events,
    }


def mixed_pause_events():
    return [
        event(0, 0.0, "recording_started"),
        event(1, 0.5, "step_started", action="click", step_index=0),
        event(2, 0.7, "step_completed", action="click", step_index=0),
        event(3, 2.2, "step_started", action="wait", step_index=1),
        event(4, 5.2, "step_completed", action="wait", step_index=1),
        event(5, 10.2, "step_started", action="click", step_index=2),
        event(6, 10.4, "step_completed", action="click", step_index=2),
        event(7, 12.4, "recording_finished"),
    ]


def create_project(tmp_path):
    root = tmp_path / "demo.hermes"
    video = tmp_path / "demo.mp4"
    events = tmp_path / "demo.events.json"
    script = tmp_path / "demo.json"
    video.write_bytes(b"fake mp4")
    events.write_text(json.dumps(event_log(mixed_pause_events())), encoding="utf-8")
    script.write_text(
        json.dumps({
            "title": "Demo",
            "steps": [
                {"action": "goto", "url": "https://example.com"},
                {"action": "click", "selector": "#one"},
                {"action": "wait", "seconds": 3},
                {"action": "click", "selector": "#two"},
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
    return root


def test_auto_edit_generates_speed_and_cut_segments() -> None:
    track = build_auto_edit_track(event_log(mixed_pause_events()))

    assert track["id"] == "auto-edit"
    assert track["type"] == "time.edit"
    assert [(item["mode"], item["reason"]) for item in track["segments"]] == [
        ("speed", "idle_gap"),
        ("speed", "wait_step"),
        ("cut", "idle_gap"),
        ("speed", "idle_gap"),
    ]
    assert track["segments"][0] == {
        "id": "auto-edit-001",
        "mode": "speed",
        "start_seconds": 0.95,
        "end_seconds": 1.95,
        "reason": "idle_gap",
        "source_event_sequences": [2, 3],
        "speed_factor": 4.0,
    }
    assert track["segments"][2]["start_seconds"] == 5.45
    assert track["segments"][2]["end_seconds"] == 9.95
    assert track["summary"] == {
        "source_duration_seconds": 12.4,
        "estimated_duration_seconds": 4.15,
        "removed_seconds": 8.25,
    }


def test_auto_edit_preserves_short_pauses() -> None:
    events = [
        event(0, 0, "recording_started"),
        event(1, 0.2, "step_started", action="click", step_index=0),
        event(2, 0.4, "step_completed", action="click", step_index=0),
        event(3, 1.0, "recording_finished"),
    ]
    track = build_auto_edit_track(event_log(events))
    assert track["segments"] == []
    assert track["summary"]["estimated_duration_seconds"] == 1.0


def test_auto_edit_uses_context_and_minimum_edit_guard() -> None:
    events = [
        event(0, 0, "recording_started"),
        event(1, 1.3, "step_started", action="click", step_index=0),
        event(2, 1.4, "recording_finished"),
    ]
    settings = AutoEditSettings(context_seconds=0.6, minimum_edit_seconds=0.2)
    track = build_auto_edit_track(event_log(events), settings=settings)
    assert track["segments"] == []


def test_auto_edit_sorts_out_of_order_events() -> None:
    track = build_auto_edit_track(event_log(list(reversed(mixed_pause_events()))))
    assert [item["id"] for item in track["segments"]] == [
        "auto-edit-001", "auto-edit-002", "auto-edit-003", "auto-edit-004"
    ]


def test_auto_edit_requires_synchronized_schema() -> None:
    payload = event_log([])
    payload["schema"] = "legacy.events"
    with pytest.raises(ValueError, match="recording event log"):
        build_auto_edit_track(payload)


@pytest.mark.parametrize("settings", [
    AutoEditSettings(preserve_threshold_seconds=4, cut_threshold_seconds=4),
    AutoEditSettings(speed_factor=1),
    AutoEditSettings(context_seconds=-1),
])
def test_auto_edit_rejects_invalid_settings(settings) -> None:
    with pytest.raises(ValueError):
        build_auto_edit_track(event_log([]), settings=settings)


def test_apply_auto_edit_is_idempotent_and_preserves_other_tracks(tmp_path) -> None:
    root = create_project(tmp_path)
    apply_auto_zoom(root)
    apply_auto_edit(root, settings=AutoEditSettings(speed_factor=3))
    apply_auto_edit(root, settings=AutoEditSettings(speed_factor=5))
    project = load_hermes_project(root)

    assert [track["id"] for track in project.timeline["tracks"]] == [
        "auto-zoom", "auto-edit"
    ]
    assert project.timeline["tracks"][1]["settings"]["speed_factor"] == 5


def test_project_rejects_overlapping_time_edits(tmp_path) -> None:
    root = create_project(tmp_path)
    apply_auto_edit(root)
    manifest = root / "project.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    track = payload["timeline"]["tracks"][0]
    track["segments"][1]["start_seconds"] = track["segments"][0]["start_seconds"]
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="non-overlapping"):
        load_hermes_project(root)

