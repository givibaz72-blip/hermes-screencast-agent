from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from hermes_screencast.project import (
    validate_hermes_project,
    validate_project_timeline,
)


ANNOTATION_TRACK_ID = "annotations"
ANNOTATION_KINDS = ("arrow", "box", "highlight", "text")


def add_project_annotation(
    project_directory: str | Path,
    *,
    kind: str,
    start_seconds: float,
    end_seconds: float,
    annotation_id: str | None = None,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
    to_x: float | None = None,
    to_y: float | None = None,
    text: str | None = None,
    color: str | None = None,
    background_color: str | None = None,
    opacity: float | None = None,
    stroke_width: float | None = None,
    corner_radius: float | None = None,
    font_size: float | None = None,
    font_weight: int | None = None,
    padding: float | None = None,
    head_size: float | None = None,
) -> dict[str, Any]:
    root = Path(project_directory).expanduser().resolve()
    project = validate_hermes_project(root)
    tracks = copy.deepcopy(project.timeline["tracks"])
    track = next((item for item in tracks if item.get("id") == ANNOTATION_TRACK_ID), None)
    if track is None:
        track = {
            "id": ANNOTATION_TRACK_ID,
            "type": "annotation.overlay",
            "source": "manual",
            "settings": {"coordinate_space": "canvas"},
            "segments": [],
        }
        tracks.append(track)
    identifier = annotation_id or _next_annotation_id(track["segments"])
    if any(item.get("id") == identifier for item in track["segments"]):
        raise ValueError(f"Annotation id already exists: {identifier}")
    annotation = _build_annotation(
        kind=kind,
        identifier=identifier,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        x=x,
        y=y,
        width=width,
        height=height,
        to_x=to_x,
        to_y=to_y,
        text=text,
        color=color,
        background_color=background_color,
        opacity=opacity,
        stroke_width=stroke_width,
        corner_radius=corner_radius,
        font_size=font_size,
        font_weight=font_weight,
        padding=padding,
        head_size=head_size,
    )
    track["segments"].append(annotation)
    track["segments"].sort(key=lambda item: (item["start_seconds"], item["id"]))
    timeline = {"tracks": tracks}
    validate_project_timeline(timeline, composition=project.composition)
    _write_timeline(root, project, timeline)
    return annotation


def remove_project_annotation(
    project_directory: str | Path, annotation_id: str
) -> dict[str, Any]:
    root = Path(project_directory).expanduser().resolve()
    project = validate_hermes_project(root)
    tracks = copy.deepcopy(project.timeline["tracks"])
    track = next((item for item in tracks if item.get("id") == ANNOTATION_TRACK_ID), None)
    if track is None:
        raise KeyError(f"Annotation not found: {annotation_id}")
    removed = next(
        (item for item in track["segments"] if item.get("id") == annotation_id), None
    )
    if removed is None:
        raise KeyError(f"Annotation not found: {annotation_id}")
    track["segments"] = [
        item for item in track["segments"] if item.get("id") != annotation_id
    ]
    if not track["segments"]:
        tracks = [item for item in tracks if item.get("id") != ANNOTATION_TRACK_ID]
    timeline = {"tracks": tracks}
    validate_project_timeline(timeline, composition=project.composition)
    _write_timeline(root, project, timeline)
    return removed


def list_project_annotations(project_directory: str | Path) -> tuple[dict[str, Any], ...]:
    project = validate_hermes_project(project_directory)
    track = next(
        (
            item for item in project.timeline["tracks"]
            if item.get("id") == ANNOTATION_TRACK_ID
        ),
        None,
    )
    return tuple(copy.deepcopy(track["segments"])) if track is not None else ()


def _build_annotation(
    *,
    kind: str,
    identifier: str,
    start_seconds: float,
    end_seconds: float,
    x: float | None,
    y: float | None,
    width: float | None,
    height: float | None,
    to_x: float | None,
    to_y: float | None,
    text: str | None,
    color: str | None,
    background_color: str | None,
    opacity: float | None,
    stroke_width: float | None,
    corner_radius: float | None,
    font_size: float | None,
    font_weight: int | None,
    padding: float | None,
    head_size: float | None,
) -> dict[str, Any]:
    common = {
        "id": identifier,
        "kind": kind,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
    }
    if kind == "text":
        return {
            **common,
            "position": {"x": _required(x, "x"), "y": _required(y, "y")},
            "text": text,
            "style": {
                "color": color or "#FFFFFF",
                "background_color": background_color or "#111827E6",
                "font_size": 32 if font_size is None else font_size,
                "font_weight": 600 if font_weight is None else font_weight,
                "padding": 12 if padding is None else padding,
                "corner_radius": 8 if corner_radius is None else corner_radius,
                "opacity": 1.0 if opacity is None else opacity,
            },
        }
    if kind in {"box", "highlight"}:
        style = {
            "color": color or "#FACC15",
            "corner_radius": 12 if corner_radius is None else corner_radius,
            "opacity": (1.0 if kind == "box" else 0.28) if opacity is None else opacity,
        }
        if kind == "box":
            style["stroke_width"] = 4 if stroke_width is None else stroke_width
        return {
            **common,
            "bounds": {
                "x": _required(x, "x"),
                "y": _required(y, "y"),
                "width": _required(width, "width"),
                "height": _required(height, "height"),
            },
            "style": style,
        }
    if kind == "arrow":
        return {
            **common,
            "from": {"x": _required(x, "x"), "y": _required(y, "y")},
            "to": {"x": _required(to_x, "to_x"), "y": _required(to_y, "to_y")},
            "style": {
                "color": color or "#FACC15",
                "stroke_width": 5 if stroke_width is None else stroke_width,
                "head_size": 16 if head_size is None else head_size,
                "opacity": 1.0 if opacity is None else opacity,
            },
        }
    raise ValueError(f"Unknown annotation kind: {kind}")


def _required(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(f"Annotation {name} is required")
    return value


def _next_annotation_id(segments: list[dict[str, Any]]) -> str:
    used = {item.get("id") for item in segments}
    index = 1
    while f"annotation-{index:03d}" in used:
        index += 1
    return f"annotation-{index:03d}"


def _write_timeline(root: Path, project, timeline: dict[str, Any]) -> None:
    payload = project.to_dict()
    payload["timeline"] = timeline
    manifest = root / "project.json"
    temporary = root / "project.json.tmp"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(manifest)
    validate_hermes_project(root)
