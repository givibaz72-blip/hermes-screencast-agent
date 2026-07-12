from __future__ import annotations

import json

import pytest

from hermes_screencast.editor import (
    ProjectEditConflictError,
    read_editor_project,
    save_editor_project,
)
from hermes_screencast.project import create_hermes_project


def create_project(tmp_path):
    video = tmp_path / "source.mp4"
    events = tmp_path / "events.json"
    script = tmp_path / "script.json"
    video.write_bytes(b"fake mp4")
    events.write_text(json.dumps({
        "schema": "hermes.recording.events.v1",
        "metadata": {"width": 1920, "height": 1080},
        "events": [{"sequence": 0, "time_seconds": 2, "type": "recording_finished"}],
    }), encoding="utf-8")
    script.write_text(json.dumps({
        "title": "Editor", "steps": [
            {"action": "goto", "url": "https://example.com"},
            {"action": "wait", "seconds": 1},
        ],
    }), encoding="utf-8")
    root = tmp_path / "editor.hermes"
    create_hermes_project(
        root, title="Editor", video_file=video, events_file=events,
        script_file=script, video_verifier=lambda path: path,
    )
    return root


def test_editor_read_and_atomic_save(tmp_path) -> None:
    root = create_project(tmp_path)
    before = read_editor_project(root)
    composition = before.project["composition"]
    composition["background"] = {"type": "color", "value": "#123456"}
    timeline = {"tracks": []}

    after = save_editor_project(
        root, composition=composition, timeline=timeline,
        expected_etag=before.etag,
    )

    assert after.etag != before.etag
    assert after.project["composition"]["background"]["value"] == "#123456"
    assert after.project["assets"] == before.project["assets"]
    assert not (root / "project.json.editor.tmp").exists()


def test_editor_rejects_stale_snapshot_without_overwrite(tmp_path) -> None:
    root = create_project(tmp_path)
    snapshot = read_editor_project(root)
    manifest = root / "project.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["title"] = "Concurrent change"
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ProjectEditConflictError, match="changed since"):
        save_editor_project(
            root, composition=snapshot.project["composition"],
            timeline=snapshot.project["timeline"],
            expected_etag=snapshot.etag,
        )
    assert json.loads(manifest.read_text(encoding="utf-8"))["title"] == "Concurrent change"


def test_editor_rejects_invalid_edits_without_mutation(tmp_path) -> None:
    root = create_project(tmp_path)
    snapshot = read_editor_project(root)
    before = (root / "project.json").read_bytes()
    with pytest.raises(ValueError, match="timeline"):
        save_editor_project(
            root, composition=snapshot.project["composition"],
            timeline={"tracks": "invalid"}, expected_etag=snapshot.etag,
        )
    assert (root / "project.json").read_bytes() == before
