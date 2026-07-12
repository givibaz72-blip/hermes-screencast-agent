from __future__ import annotations

import json

import pytest

from hermes_screencast.project import (
    create_hermes_project,
    load_hermes_project,
    validate_hermes_project,
)


def source_files(tmp_path):
    video = tmp_path / "recording.mp4"
    events = tmp_path / "recording.events.json"
    script = tmp_path / "demo.json"
    video.write_bytes(b"fake mp4")
    events.write_text(
        json.dumps({"schema": "hermes.recording.events.v1", "metadata": {}, "events": []}),
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


def test_create_project_copies_and_validates_portable_assets(tmp_path) -> None:
    video, events, script = source_files(tmp_path)
    root = tmp_path / "product.hermes"

    manifest = create_hermes_project(
        root,
        title="Product demo",
        video_file=video,
        events_file=events,
        script_file=script,
        video_verifier=lambda path: path,
    )

    assert manifest == root / "project.json"
    project = validate_hermes_project(root)
    assert project.title == "Product demo"
    assert set(project.assets) == {"video", "events", "script"}
    assert (root / "assets" / "source.mp4").read_bytes() == b"fake mp4"
    assert all(not asset.path.startswith("/") for asset in project.assets.values())


def test_project_validation_detects_tampered_asset(tmp_path) -> None:
    video, events, script = source_files(tmp_path)
    root = tmp_path / "tampered.hermes"
    create_hermes_project(
        root, title="Demo", video_file=video, events_file=events, script_file=script,
        video_verifier=lambda path: path,
    )
    (root / "assets" / "source.mp4").write_bytes(b"changed")

    with pytest.raises(ValueError, match="size mismatch|checksum mismatch"):
        validate_hermes_project(root)


def test_project_rejects_path_traversal(tmp_path) -> None:
    video, events, script = source_files(tmp_path)
    root = tmp_path / "unsafe.hermes"
    manifest = create_hermes_project(
        root, title="Demo", video_file=video, events_file=events, script_file=script,
        video_verifier=lambda path: path,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["assets"]["video"]["path"] = "../outside.mp4"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="safe and relative"):
        load_hermes_project(root)


def test_project_rejects_wrong_event_schema(tmp_path) -> None:
    video, events, script = source_files(tmp_path)
    events.write_text(json.dumps({"schema": "wrong", "events": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="hermes.recording.events.v1"):
        create_hermes_project(
            tmp_path / "wrong.hermes", title="Demo", video_file=video,
            events_file=events, script_file=script, video_verifier=lambda path: path,
        )


def test_project_refuses_to_overwrite_existing_manifest(tmp_path) -> None:
    video, events, script = source_files(tmp_path)
    root = tmp_path / "existing.hermes"
    root.mkdir()
    (root / "project.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        create_hermes_project(
            root, title="Demo", video_file=video, events_file=events,
            script_file=script, video_verifier=lambda path: path,
        )
