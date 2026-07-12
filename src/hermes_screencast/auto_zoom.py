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


AUTO_ZOOM_TRACK_ID = "auto-zoom"


@dataclass(frozen=True)
class AutoZoomSettings:
    scale: float = 1.35
    lead_seconds: float = 0.25
    hold_seconds: float = 0.65
    transition_seconds: float = 0.35
    target_margin: float = 80.0
    merge_distance: float = 120.0
    easing: str = "ease_in_out_cubic"

    def validate(self) -> None:
        numeric = {
            "scale": self.scale,
            "lead_seconds": self.lead_seconds,
            "hold_seconds": self.hold_seconds,
            "transition_seconds": self.transition_seconds,
            "target_margin": self.target_margin,
            "merge_distance": self.merge_distance,
        }
        for name, value in numeric.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"Auto zoom {name} must be numeric")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Auto zoom {name} must be finite and non-negative")
        if self.scale < 1:
            raise ValueError("Auto zoom scale must be at least 1")
        if self.easing != "ease_in_out_cubic":
            raise ValueError("Auto zoom easing must be ease_in_out_cubic")

    def to_dict(self) -> dict[str, Any]:
        return {
            "scale": self.scale,
            "lead_seconds": self.lead_seconds,
            "hold_seconds": self.hold_seconds,
            "transition_seconds": self.transition_seconds,
            "target_margin": self.target_margin,
            "merge_distance": self.merge_distance,
            "easing": self.easing,
        }


def apply_auto_zoom(
    project_directory: str | Path,
    *,
    settings: AutoZoomSettings | None = None,
) -> dict[str, Any]:
    root = Path(project_directory).expanduser().resolve()
    project = validate_hermes_project(root)
    config = settings or AutoZoomSettings()
    config.validate()

    events_asset = project.assets["events"]
    events_path = root / Path(*PurePosixPath(events_asset.path).parts)
    event_log = json.loads(events_path.read_text(encoding="utf-8"))
    track = build_auto_zoom_track(
        event_log,
        composition=project.composition,
        settings=config,
    )

    tracks = [
        item for item in project.timeline["tracks"]
        if item.get("id") != AUTO_ZOOM_TRACK_ID
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


def build_auto_zoom_track(
    event_log: dict[str, Any],
    *,
    composition: dict[str, Any],
    settings: AutoZoomSettings | None = None,
) -> dict[str, Any]:
    config = settings or AutoZoomSettings()
    config.validate()
    if (
        not isinstance(event_log, dict) or event_log.get("schema") != EVENT_SCHEMA
        or not isinstance(event_log.get("events"), list)
    ):
        raise ValueError("Auto zoom requires a recording event log")

    metadata = event_log.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    width, height = _video_dimensions(metadata, composition)
    duration = _recording_duration(event_log["events"])
    candidates = [
        segment
        for event in event_log["events"]
        if (segment := _candidate_for_event(
            event,
            metadata=metadata,
            video_width=width,
            video_height=height,
            duration=duration,
            settings=config,
        )) is not None
    ]
    candidates.sort(key=lambda item: (item["focus_seconds"], item["_sequence"]))
    segments = _resolve_overlaps(candidates, config.merge_distance)
    return {
        "id": AUTO_ZOOM_TRACK_ID,
        "type": "camera.zoom",
        "source": "automatic",
        "settings": config.to_dict(),
        "segments": [_public_segment(segment) for segment in segments],
    }


def _candidate_for_event(
    event: Any,
    *,
    metadata: dict[str, Any],
    video_width: float,
    video_height: float,
    duration: float | None,
    settings: AutoZoomSettings,
) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    if event.get("type") != "step_completed" or event.get("action") != "click":
        return None
    sequence = event.get("sequence")
    timestamp = _finite_number(event.get("time_seconds"))
    data = event.get("data")
    if (
        not isinstance(sequence, int) or isinstance(sequence, bool)
        or sequence < 0 or timestamp is None
    ):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("target"), dict):
        return None
    target = data["target"]
    x = _finite_number(target.get("x"))
    y = _finite_number(target.get("y"))
    target_width = _finite_number(target.get("width"))
    target_height = _finite_number(target.get("height"))
    if (
        x is None or y is None or target_width is None or target_height is None
        or target_width < 0 or target_height < 0
    ):
        return None

    scale = min(
        settings.scale,
        video_width / max(1.0, target_width + 2 * settings.target_margin),
        video_height / max(1.0, target_height + 2 * settings.target_margin),
    )
    scale = max(1.0, scale)
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    offset_y = _browser_content_offset(metadata, state, video_height)
    focus_x = x + target_width / 2
    focus_y = y + target_height / 2 + offset_y
    crop_width = video_width / scale
    crop_height = video_height / scale
    focus_x = _clamp(focus_x, crop_width / 2, video_width - crop_width / 2)
    focus_y = _clamp(focus_y, crop_height / 2, video_height - crop_height / 2)

    start = max(0.0, timestamp - settings.lead_seconds)
    hold_until = timestamp + settings.hold_seconds
    end = hold_until + settings.transition_seconds
    if duration is not None:
        hold_until = min(hold_until, duration)
        end = min(end, duration)
    focus_time = min(timestamp, hold_until)
    if end <= start:
        return None
    return {
        "start_seconds": start,
        "focus_seconds": max(start, focus_time),
        "hold_until_seconds": max(focus_time, hold_until),
        "end_seconds": end,
        "scale": scale,
        "focus": {"x": focus_x, "y": focus_y},
        "source_event_sequences": [sequence],
        "_sequence": sequence,
        "_last_event_seconds": timestamp,
        "_video_width": video_width,
        "_video_height": video_height,
    }


def _resolve_overlaps(
    candidates: list[dict[str, Any]], merge_distance: float
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for current in candidates:
        if not resolved:
            resolved.append(current)
            continue
        previous = resolved[-1]
        if current["start_seconds"] >= previous["end_seconds"]:
            resolved.append(current)
            continue
        if _focus_distance(previous, current) <= merge_distance:
            count = len(previous["source_event_sequences"])
            previous["focus"]["x"] = (
                previous["focus"]["x"] * count + current["focus"]["x"]
            ) / (count + 1)
            previous["focus"]["y"] = (
                previous["focus"]["y"] * count + current["focus"]["y"]
            ) / (count + 1)
            previous["hold_until_seconds"] = max(
                previous["hold_until_seconds"], current["hold_until_seconds"]
            )
            previous["end_seconds"] = max(
                previous["end_seconds"], current["end_seconds"]
            )
            previous["scale"] = min(previous["scale"], current["scale"])
            crop_width = previous["_video_width"] / previous["scale"]
            crop_height = previous["_video_height"] / previous["scale"]
            previous["focus"]["x"] = _clamp(
                previous["focus"]["x"],
                crop_width / 2,
                previous["_video_width"] - crop_width / 2,
            )
            previous["focus"]["y"] = _clamp(
                previous["focus"]["y"],
                crop_height / 2,
                previous["_video_height"] - crop_height / 2,
            )
            previous["source_event_sequences"].extend(
                current["source_event_sequences"]
            )
            previous["_last_event_seconds"] = current["_last_event_seconds"]
            continue

        boundary = (
            previous["_last_event_seconds"] + current["focus_seconds"]
        ) / 2
        previous["end_seconds"] = boundary
        previous["hold_until_seconds"] = min(
            previous["hold_until_seconds"], previous["end_seconds"]
        )
        current["start_seconds"] = max(current["start_seconds"], previous["end_seconds"])
        current["focus_seconds"] = max(current["focus_seconds"], current["start_seconds"])
        current["hold_until_seconds"] = max(
            current["hold_until_seconds"], current["focus_seconds"]
        )
        current["end_seconds"] = max(
            current["end_seconds"], current["hold_until_seconds"]
        )
        resolved.append(current)
    return resolved


def _public_segment(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "start_seconds": round(segment["start_seconds"], 6),
        "focus_seconds": round(segment["focus_seconds"], 6),
        "hold_until_seconds": round(segment["hold_until_seconds"], 6),
        "end_seconds": round(segment["end_seconds"], 6),
        "scale": round(segment["scale"], 4),
        "focus": {
            "x": round(segment["focus"]["x"], 2),
            "y": round(segment["focus"]["y"], 2),
        },
        "source_event_sequences": list(segment["source_event_sequences"]),
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
        raise ValueError("Auto zoom requires positive video dimensions")
    return width, height


def _recording_duration(events: list[Any]) -> float | None:
    finished = [
        value
        for event in events
        if isinstance(event, dict) and event.get("type") == "recording_finished"
        if (value := _finite_number(event.get("time_seconds"))) is not None
    ]
    return max(finished) if finished else None


def _browser_content_offset(
    metadata: dict[str, Any], state: dict[str, Any], video_height: float
) -> float:
    if metadata.get("browser_ui") != "visible":
        return 0.0
    viewport_height = _finite_number(state.get("viewport_height"))
    if viewport_height is None:
        return 0.0
    return max(0.0, video_height - viewport_height)


def _focus_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    return math.hypot(
        left["focus"]["x"] - right["focus"]["x"],
        left["focus"]["y"] - right["focus"]["y"],
    )


def _finite_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if minimum > maximum:
        return (minimum + maximum) / 2
    return max(minimum, min(maximum, value))
