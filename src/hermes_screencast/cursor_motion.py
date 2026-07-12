from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from hermes_screencast.demo.events import EVENT_SCHEMA
from hermes_screencast.project import (
    validate_hermes_project,
    validate_project_timeline,
)


CURSOR_MOTION_TRACK_ID = "cursor-motion"
CURSOR_ACTIONS = {"click", "hover", "fill"}


@dataclass(frozen=True)
class CursorMotionSettings:
    speed_pixels_per_second: float = 1400.0
    minimum_move_seconds: float = 0.12
    maximum_move_seconds: float = 0.75
    settle_seconds: float = 0.06
    tension: float = 0.6
    easing: str = "ease_in_out_cubic"

    def validate(self) -> None:
        numeric = {
            "speed_pixels_per_second": self.speed_pixels_per_second,
            "minimum_move_seconds": self.minimum_move_seconds,
            "maximum_move_seconds": self.maximum_move_seconds,
            "settle_seconds": self.settle_seconds,
            "tension": self.tension,
        }
        for name, value in numeric.items():
            if (
                not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or value < 0
            ):
                raise ValueError(f"Cursor motion {name} must be finite and non-negative")
        if self.speed_pixels_per_second <= 0:
            raise ValueError("Cursor motion speed must be positive")
        if self.minimum_move_seconds > self.maximum_move_seconds:
            raise ValueError("Cursor motion minimum duration must not exceed maximum")
        if self.tension > 1:
            raise ValueError("Cursor motion tension must not exceed 1")
        if self.easing != "ease_in_out_cubic":
            raise ValueError("Cursor motion easing must be ease_in_out_cubic")

    def to_dict(self) -> dict[str, Any]:
        return {
            "speed_pixels_per_second": self.speed_pixels_per_second,
            "minimum_move_seconds": self.minimum_move_seconds,
            "maximum_move_seconds": self.maximum_move_seconds,
            "settle_seconds": self.settle_seconds,
            "tension": self.tension,
            "easing": self.easing,
        }


def apply_cursor_motion(
    project_directory: str | Path,
    *,
    settings: CursorMotionSettings | None = None,
) -> dict[str, Any]:
    root = Path(project_directory).expanduser().resolve()
    project = validate_hermes_project(root)
    config = settings or CursorMotionSettings()
    config.validate()

    events_asset = project.assets["events"]
    events_path = root / Path(*PurePosixPath(events_asset.path).parts)
    event_log = json.loads(events_path.read_text(encoding="utf-8"))
    track = build_cursor_motion_track(
        event_log,
        composition=project.composition,
        settings=config,
    )

    tracks = [
        item for item in project.timeline["tracks"]
        if item.get("id") != CURSOR_MOTION_TRACK_ID
    ]
    tracks.append(track)
    timeline = {"tracks": tracks}
    validate_project_timeline(timeline)

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
    return track


def build_cursor_motion_track(
    event_log: dict[str, Any],
    *,
    composition: dict[str, Any],
    settings: CursorMotionSettings | None = None,
) -> dict[str, Any]:
    config = settings or CursorMotionSettings()
    config.validate()
    if (
        not isinstance(event_log, dict) or event_log.get("schema") != EVENT_SCHEMA
        or not isinstance(event_log.get("events"), list)
    ):
        raise ValueError("Cursor motion requires a recording event log")
    metadata = event_log.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    width, height = _video_dimensions(metadata, composition)
    anchors = [
        anchor
        for event in event_log["events"]
        if (anchor := _anchor_for_event(
            event,
            metadata=metadata,
            video_width=width,
            video_height=height,
        )) is not None
    ]
    anchors.sort(key=lambda item: (item["time_seconds"], item["source_event_sequence"]))
    segments = _build_segments(anchors, config, width, height)
    return {
        "id": CURSOR_MOTION_TRACK_ID,
        "type": "cursor.motion",
        "source": "automatic",
        "settings": config.to_dict(),
        "anchors": [_public_anchor(anchor) for anchor in anchors],
        "segments": segments,
    }


def _anchor_for_event(
    event: Any,
    *,
    metadata: dict[str, Any],
    video_width: float,
    video_height: float,
) -> dict[str, Any] | None:
    if not isinstance(event, dict) or event.get("type") != "step_completed":
        return None
    action = event.get("action")
    sequence = event.get("sequence")
    timestamp = _finite_number(event.get("time_seconds"))
    data = event.get("data")
    if (
        action not in CURSOR_ACTIONS
        or not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0
        or timestamp is None or not isinstance(data, dict)
    ):
        return None
    cursor = data.get("cursor")
    if not isinstance(cursor, dict):
        return None
    x = _finite_number(cursor.get("x"))
    y = _finite_number(cursor.get("y"))
    if x is None or y is None:
        return None
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    y += _browser_content_offset(metadata, state, video_height)
    return {
        "time_seconds": timestamp,
        "position": {
            "x": _clamp(x, 0.0, video_width),
            "y": _clamp(y, 0.0, video_height),
        },
        "action": action,
        "source_event_sequence": sequence,
    }


def _build_segments(
    anchors: list[dict[str, Any]],
    settings: CursorMotionSettings,
    video_width: float,
    video_height: float,
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for index in range(len(anchors) - 1):
        previous = anchors[index]
        current = anchors[index + 1]
        start_point = previous["position"]
        end_point = current["position"]
        distance = math.hypot(
            end_point["x"] - start_point["x"],
            end_point["y"] - start_point["y"],
        )
        available = max(0.0, current["time_seconds"] - previous["time_seconds"])
        settle = min(settings.settle_seconds, available / 3)
        movement_end = current["time_seconds"] - settle
        movement_window = max(0.0, movement_end - previous["time_seconds"])
        if distance < 0.5 or movement_window <= 0:
            continue
        preferred = _clamp(
            distance / settings.speed_pixels_per_second,
            settings.minimum_move_seconds,
            settings.maximum_move_seconds,
        )
        duration = min(preferred, movement_window)
        movement_start = movement_end - duration
        before = anchors[index - 1]["position"] if index > 0 else start_point
        after = (
            anchors[index + 2]["position"]
            if index + 2 < len(anchors) else end_point
        )
        control_1 = _clamped_point(
            start_point["x"] + (end_point["x"] - before["x"]) * settings.tension / 6,
            start_point["y"] + (end_point["y"] - before["y"]) * settings.tension / 6,
            video_width,
            video_height,
        )
        control_2 = _clamped_point(
            end_point["x"] - (after["x"] - start_point["x"]) * settings.tension / 6,
            end_point["y"] - (after["y"] - start_point["y"]) * settings.tension / 6,
            video_width,
            video_height,
        )
        segments.append({
            "start_seconds": round(movement_start, 6),
            "end_seconds": round(movement_end, 6),
            "arrival_seconds": round(current["time_seconds"], 6),
            "from": _public_point(start_point),
            "to": _public_point(end_point),
            "control_1": control_1,
            "control_2": control_2,
            "source_event_sequences": [
                previous["source_event_sequence"], current["source_event_sequence"]
            ],
        })
    return segments


def _public_anchor(anchor: dict[str, Any]) -> dict[str, Any]:
    return {
        "time_seconds": round(anchor["time_seconds"], 6),
        "position": _public_point(anchor["position"]),
        "action": anchor["action"],
        "source_event_sequence": anchor["source_event_sequence"],
    }


def _public_point(point: dict[str, float]) -> dict[str, float]:
    return {"x": round(point["x"], 2), "y": round(point["y"], 2)}


def _clamped_point(
    x: float, y: float, video_width: float, video_height: float
) -> dict[str, float]:
    return {
        "x": round(_clamp(x, 0.0, video_width), 2),
        "y": round(_clamp(y, 0.0, video_height), 2),
    }


def _video_dimensions(
    metadata: dict[str, Any], composition: dict[str, Any]
) -> tuple[float, float]:
    canvas = composition.get("canvas") if isinstance(composition, dict) else None
    if not isinstance(canvas, dict):
        canvas = {}
    width = _finite_number(metadata.get("width")) or _finite_number(canvas.get("width"))
    height = _finite_number(metadata.get("height")) or _finite_number(canvas.get("height"))
    if width is None or height is None or width <= 0 or height <= 0:
        raise ValueError("Cursor motion requires positive video dimensions")
    return width, height


def _browser_content_offset(
    metadata: dict[str, Any], state: dict[str, Any], video_height: float
) -> float:
    if metadata.get("browser_ui") != "visible":
        return 0.0
    viewport_height = _finite_number(state.get("viewport_height"))
    if viewport_height is None:
        return 0.0
    return max(0.0, video_height - viewport_height)


def _finite_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
