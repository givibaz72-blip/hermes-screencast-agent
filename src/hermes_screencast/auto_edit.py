from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from hermes_screencast.demo.events import EVENT_SCHEMA
from hermes_screencast.project import validate_hermes_project, validate_project_timeline


AUTO_EDIT_TRACK_ID = "auto-edit"


@dataclass(frozen=True)
class AutoEditSettings:
    preserve_threshold_seconds: float = 1.25
    cut_threshold_seconds: float = 4.0
    speed_factor: float = 4.0
    context_seconds: float = 0.25
    minimum_edit_seconds: float = 0.2

    def validate(self) -> None:
        values = {
            "preserve_threshold_seconds": self.preserve_threshold_seconds,
            "cut_threshold_seconds": self.cut_threshold_seconds,
            "speed_factor": self.speed_factor,
            "context_seconds": self.context_seconds,
            "minimum_edit_seconds": self.minimum_edit_seconds,
        }
        if any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value < 0
            for value in values.values()
        ):
            raise ValueError("Auto edit settings must be finite and non-negative")
        if self.cut_threshold_seconds <= self.preserve_threshold_seconds:
            raise ValueError("Auto edit cut threshold must exceed preserve threshold")
        if self.speed_factor <= 1:
            raise ValueError("Auto edit speed factor must exceed 1")

    def to_dict(self) -> dict[str, float]:
        return {
            "preserve_threshold_seconds": self.preserve_threshold_seconds,
            "cut_threshold_seconds": self.cut_threshold_seconds,
            "speed_factor": self.speed_factor,
            "context_seconds": self.context_seconds,
            "minimum_edit_seconds": self.minimum_edit_seconds,
        }


def apply_auto_edit(
    project_directory: str | Path,
    *,
    settings: AutoEditSettings | None = None,
) -> dict[str, Any]:
    root = Path(project_directory).expanduser().resolve()
    project = validate_hermes_project(root)
    events_asset = project.assets["events"]
    events_path = root / Path(*PurePosixPath(events_asset.path).parts)
    event_log = json.loads(events_path.read_text(encoding="utf-8"))
    track = build_auto_edit_track(event_log, settings=settings)
    tracks = [
        copy.deepcopy(item) for item in project.timeline["tracks"]
        if item.get("id") != AUTO_EDIT_TRACK_ID
    ]
    tracks.append(track)
    timeline = {"tracks": tracks}
    validate_project_timeline(timeline, composition=project.composition)
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


def build_auto_edit_track(
    event_log: dict[str, Any], *, settings: AutoEditSettings | None = None
) -> dict[str, Any]:
    config = settings or AutoEditSettings()
    config.validate()
    if (
        not isinstance(event_log, dict) or event_log.get("schema") != EVENT_SCHEMA
        or not isinstance(event_log.get("events"), list)
    ):
        raise ValueError("Auto edit requires a recording event log")
    events = [event for event in event_log["events"] if _valid_event(event)]
    events.sort(key=lambda item: (item["time_seconds"], item["sequence"]))
    intervals = _collect_editable_intervals(events)
    segments: list[dict[str, Any]] = []
    for interval in intervals:
        gap_duration = interval["end_seconds"] - interval["start_seconds"]
        if gap_duration <= config.preserve_threshold_seconds:
            continue
        start = interval["start_seconds"] + config.context_seconds
        end = interval["end_seconds"] - config.context_seconds
        if end - start < config.minimum_edit_seconds:
            continue
        mode = "cut" if gap_duration >= config.cut_threshold_seconds else "speed"
        segment = {
            "id": f"auto-edit-{len(segments) + 1:03d}",
            "mode": mode,
            "start_seconds": round(start, 6),
            "end_seconds": round(end, 6),
            "reason": interval["reason"],
            "source_event_sequences": interval["source_event_sequences"],
        }
        if mode == "speed":
            segment["speed_factor"] = config.speed_factor
        segments.append(segment)
    source_duration = _source_duration(events)
    removed = sum(
        (segment["end_seconds"] - segment["start_seconds"])
        * (1.0 if segment["mode"] == "cut" else 1 - 1 / segment["speed_factor"])
        for segment in segments
    )
    return {
        "id": AUTO_EDIT_TRACK_ID,
        "type": "time.edit",
        "source": "automatic",
        "settings": config.to_dict(),
        "segments": segments,
        "summary": {
            "source_duration_seconds": round(source_duration, 6),
            "estimated_duration_seconds": round(max(0.0, source_duration - removed), 6),
            "removed_seconds": round(removed, 6),
        },
    }


def _collect_editable_intervals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    wait_starts: dict[int, dict[str, Any]] = {}
    boundary: dict[str, Any] | None = None
    for event in events:
        event_type = event.get("type")
        action = event.get("action")
        step_index = event.get("step_index")
        if event_type == "recording_started":
            boundary = event
        elif event_type == "step_started":
            if boundary is not None:
                _append_interval(intervals, boundary, event, "idle_gap")
            boundary = None
            if action == "wait" and isinstance(step_index, int):
                wait_starts[step_index] = event
        elif event_type in {"step_completed", "step_failed"}:
            if action == "wait" and isinstance(step_index, int):
                started = wait_starts.pop(step_index, None)
                if started is not None:
                    _append_interval(intervals, started, event, "wait_step")
            boundary = event
        elif event_type == "recording_finished" and boundary is not None:
            _append_interval(intervals, boundary, event, "idle_gap")
            boundary = None
    intervals.sort(key=lambda item: (item["start_seconds"], item["end_seconds"]))
    return intervals


def _append_interval(
    intervals: list[dict[str, Any]],
    before: dict[str, Any],
    after: dict[str, Any],
    reason: str,
) -> None:
    start = float(before["time_seconds"])
    end = float(after["time_seconds"])
    if end <= start:
        return
    intervals.append({
        "start_seconds": start,
        "end_seconds": end,
        "reason": reason,
        "source_event_sequences": [before["sequence"], after["sequence"]],
    })


def _source_duration(events: list[dict[str, Any]]) -> float:
    finished = [
        float(event["time_seconds"])
        for event in events if event.get("type") == "recording_finished"
    ]
    return max(finished) if finished else max(
        (float(event["time_seconds"]) for event in events), default=0.0
    )


def _valid_event(event: Any) -> bool:
    if not isinstance(event, dict):
        return False
    sequence = event.get("sequence")
    timestamp = event.get("time_seconds")
    return (
        isinstance(sequence, int) and not isinstance(sequence, bool) and sequence >= 0
        and isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool)
        and math.isfinite(timestamp) and timestamp >= 0
    )
