from __future__ import annotations

import json

import pytest

from hermes_screencast.annotations import (
    add_project_annotation,
    list_project_annotations,
    remove_project_annotation,
)
from hermes_screencast.auto_zoom import apply_auto_zoom
from hermes_screencast.framing import apply_framing_preset
from hermes_screencast.project import create_hermes_project, load_hermes_project


def create_project(tmp_path):
    root = tmp_path / "demo.hermes"
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
    create_hermes_project(
        root,
        title="Demo",
        video_file=video,
        events_file=events,
        script_file=script,
        video_verifier=lambda path: path,
    )
    return root


def test_add_text_annotation_with_defaults_and_list(tmp_path) -> None:
    root = create_project(tmp_path)
    annotation = add_project_annotation(
        root,
        kind="text",
        start_seconds=1,
        end_seconds=3,
        x=120,
        y=80,
        text="Important action",
    )

    assert annotation["id"] == "annotation-001"
    assert annotation["position"] == {"x": 120, "y": 80}
    assert annotation["style"]["font_size"] == 32
    assert annotation["style"]["background_color"] == "#111827E6"
    assert list_project_annotations(root) == (annotation,)


def test_add_all_geometry_annotation_types_sorted_by_time(tmp_path) -> None:
    root = create_project(tmp_path)
    box = add_project_annotation(
        root, kind="box", start_seconds=3, end_seconds=4,
        x=100, y=100, width=400, height=240,
    )
    highlight = add_project_annotation(
        root, kind="highlight", start_seconds=2, end_seconds=3,
        x=200, y=150, width=300, height=120,
    )
    arrow = add_project_annotation(
        root, kind="arrow", start_seconds=1, end_seconds=2,
        x=50, y=50, to_x=500, to_y=300,
    )

    annotations = list_project_annotations(root)
    assert [item["kind"] for item in annotations] == ["arrow", "highlight", "box"]
    assert box["style"]["stroke_width"] == 4
    assert highlight["style"]["opacity"] == 0.28
    assert arrow["style"]["head_size"] == 16


def test_annotation_custom_styles_are_preserved(tmp_path) -> None:
    root = create_project(tmp_path)
    annotation = add_project_annotation(
        root,
        kind="text",
        annotation_id="title-card",
        start_seconds=0.5,
        end_seconds=2.5,
        x=40,
        y=40,
        text="Welcome",
        color="#112233",
        background_color="#AABBCCDD",
        opacity=0.8,
        font_size=48,
        font_weight=700,
        padding=16,
        corner_radius=10,
    )
    assert annotation["id"] == "title-card"
    assert annotation["style"]["font_weight"] == 700
    assert annotation["style"]["opacity"] == 0.8


def test_annotation_ids_are_unique(tmp_path) -> None:
    root = create_project(tmp_path)
    kwargs = dict(
        kind="text", annotation_id="note", start_seconds=1, end_seconds=2,
        x=10, y=10, text="One",
    )
    add_project_annotation(root, **kwargs)
    with pytest.raises(ValueError, match="already exists"):
        add_project_annotation(root, **kwargs)


def test_remove_annotation_and_drop_empty_track(tmp_path) -> None:
    root = create_project(tmp_path)
    added = add_project_annotation(
        root, kind="box", start_seconds=1, end_seconds=2,
        x=10, y=10, width=100, height=100,
    )
    removed = remove_project_annotation(root, added["id"])

    assert removed == added
    assert list_project_annotations(root) == ()
    assert all(
        track["id"] != "annotations"
        for track in load_hermes_project(root).timeline["tracks"]
    )


def test_remove_missing_annotation_fails(tmp_path) -> None:
    root = create_project(tmp_path)
    with pytest.raises(KeyError, match="not found"):
        remove_project_annotation(root, "missing")


@pytest.mark.parametrize("kwargs, message", [
    (
        dict(kind="box", start_seconds=1, end_seconds=2, x=1800, y=10,
             width=200, height=100),
        "exceed canvas",
    ),
    (
        dict(kind="arrow", start_seconds=1, end_seconds=2, x=10, y=10,
             to_x=2000, to_y=20),
        "exceeds canvas",
    ),
    (
        dict(kind="text", start_seconds=2, end_seconds=1, x=10, y=10,
             text="Invalid"),
        "times",
    ),
    (
        dict(kind="highlight", start_seconds=1, end_seconds=2, x=10, y=10,
             width=100, height=100, opacity=2),
        "opacity",
    ),
])
def test_annotation_rejects_invalid_geometry_time_and_style(tmp_path, kwargs, message) -> None:
    root = create_project(tmp_path)
    with pytest.raises(ValueError, match=message):
        add_project_annotation(root, **kwargs)


def test_annotation_requires_kind_specific_fields(tmp_path) -> None:
    root = create_project(tmp_path)
    with pytest.raises(ValueError, match="to_x is required"):
        add_project_annotation(
            root, kind="arrow", start_seconds=1, end_seconds=2,
            x=10, y=10, to_y=100,
        )


def test_annotations_preserve_zoom_and_composition(tmp_path) -> None:
    root = create_project(tmp_path)
    apply_auto_zoom(root)
    apply_framing_preset(root, preset="social-square")
    add_project_annotation(
        root, kind="highlight", start_seconds=1, end_seconds=2,
        x=100, y=100, width=300, height=200,
    )
    project = load_hermes_project(root)

    assert project.composition["preset"] == "social-square"
    assert [track["id"] for track in project.timeline["tracks"]] == [
        "auto-zoom", "annotations"
    ]


def test_smaller_style_is_rejected_before_annotation_leaves_canvas(tmp_path) -> None:
    root = create_project(tmp_path)
    add_project_annotation(
        root, kind="box", start_seconds=1, end_seconds=2,
        x=1500, y=100, width=300, height=200,
    )
    manifest = root / "project.json"
    original = manifest.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="exceed canvas"):
        apply_framing_preset(root, preset="social-square")

    assert manifest.read_text(encoding="utf-8") == original
    assert load_hermes_project(root).composition["preset"] == "source"


def test_project_rejects_tampered_annotation_id(tmp_path) -> None:
    root = create_project(tmp_path)
    add_project_annotation(
        root, kind="text", start_seconds=1, end_seconds=2,
        x=10, y=10, text="Note",
    )
    manifest = root / "project.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["timeline"]["tracks"][0]["segments"][0]["id"] = "bad id"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="annotation id"):
        load_hermes_project(root)
