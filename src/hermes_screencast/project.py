from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from hermes_screencast.demo.events import EVENT_SCHEMA
from hermes_screencast.demo.json_loader import load_demo_script
from hermes_screencast.verifier import verify_mp4


PROJECT_SCHEMA = "hermes.project.v1"
REQUIRED_ASSETS = {"video", "events", "script"}
HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")


@dataclass(frozen=True)
class ProjectAsset:
    path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size_bytes": self.size_bytes, "sha256": self.sha256}


@dataclass(frozen=True)
class HermesProject:
    title: str
    assets: dict[str, ProjectAsset]
    composition: dict[str, Any]
    timeline: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PROJECT_SCHEMA,
            "title": self.title,
            "assets": {name: asset.to_dict() for name, asset in sorted(self.assets.items())},
            "composition": dict(self.composition),
            "timeline": dict(self.timeline),
        }


def create_hermes_project(
    project_directory: str | Path,
    *,
    title: str,
    video_file: str | Path,
    events_file: str | Path,
    script_file: str | Path,
    video_verifier: Callable[[Path], Path] = verify_mp4,
) -> Path:
    if not title.strip():
        raise ValueError("HermesProject title cannot be empty")
    root = Path(project_directory).expanduser().resolve()
    manifest_path = root / "project.json"
    if manifest_path.exists():
        raise FileExistsError(f"HermesProject already exists: {manifest_path}")

    video = _existing_file(video_file, "video")
    events = _existing_file(events_file, "events")
    script = _existing_file(script_file, "script")
    video_verifier(video)
    _validate_events_file(events)
    load_demo_script(script)

    destinations = {
        "video": (video, PurePosixPath("assets/source.mp4")),
        "events": (events, PurePosixPath("events/recording.events.json")),
        "script": (script, PurePosixPath("script/demo.json")),
    }
    assets: dict[str, ProjectAsset] = {}
    for name, (source, relative) in destinations.items():
        destination = root / Path(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        assets[name] = _asset_for_file(destination, relative.as_posix())

    project = HermesProject(
        title=title,
        assets=assets,
        composition={
            "preset": "source",
            "canvas": {"width": 1920, "height": 1080, "aspect_ratio": "16:9"},
            "background": {"type": "color", "value": "#111827"},
            "frame": {
                "fit": "contain",
                "padding": 0,
                "corner_radius": 0,
                "shadow": {
                    "enabled": False,
                    "color": "#000000",
                    "opacity": 0.0,
                    "blur": 0,
                    "offset_x": 0,
                    "offset_y": 0,
                },
            },
        },
        timeline={"tracks": []},
    )
    root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(project.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    validate_hermes_project(root)
    return manifest_path


def load_hermes_project(project_directory: str | Path) -> HermesProject:
    root = Path(project_directory).expanduser().resolve()
    manifest = root / "project.json"
    if not manifest.exists():
        raise FileNotFoundError(manifest)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != PROJECT_SCHEMA:
        raise ValueError(f"HermesProject must use schema {PROJECT_SCHEMA}")
    if set(payload) - {"schema", "title", "assets", "composition", "timeline"}:
        raise ValueError("HermesProject contains unknown top-level fields")
    title = payload.get("title")
    assets_payload = payload.get("assets")
    composition = _normalize_project_composition(payload.get("composition"))
    timeline = payload.get("timeline")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("HermesProject requires non-empty title")
    if not isinstance(assets_payload, dict) or not REQUIRED_ASSETS.issubset(assets_payload):
        raise ValueError("HermesProject requires video, events, and script assets")
    if not isinstance(composition, dict):
        raise ValueError("HermesProject composition must be an object")
    validate_project_composition(composition)
    validate_project_timeline(timeline)
    assets = {name: _asset_from_dict(name, value) for name, value in assets_payload.items()}
    return HermesProject(
        title=title,
        assets=assets,
        composition=composition,
        timeline=timeline,
    )


def validate_hermes_project(project_directory: str | Path) -> HermesProject:
    root = Path(project_directory).expanduser().resolve()
    project = load_hermes_project(root)
    resolved: dict[str, Path] = {}
    for name, asset in project.assets.items():
        path = _resolve_relative_asset(root, asset.path)
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != asset.size_bytes:
            raise ValueError(f"HermesProject asset size mismatch: {name}")
        if _sha256(path) != asset.sha256:
            raise ValueError(f"HermesProject asset checksum mismatch: {name}")
        resolved[name] = path
    _validate_events_file(resolved["events"])
    load_demo_script(resolved["script"])
    return project


def _asset_from_dict(name: str, payload: Any) -> ProjectAsset:
    if not isinstance(payload, dict) or set(payload) != {"path", "size_bytes", "sha256"}:
        raise ValueError(f"HermesProject asset is invalid: {name}")
    path, size, digest = payload["path"], payload["size_bytes"], payload["sha256"]
    if not isinstance(path, str) or not isinstance(size, int) or size < 0:
        raise ValueError(f"HermesProject asset is invalid: {name}")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"HermesProject asset checksum is invalid: {name}")
    _validate_relative_path(path)
    return ProjectAsset(path=path, size_bytes=size, sha256=digest)


def _resolve_relative_asset(root: Path, value: str) -> Path:
    _validate_relative_path(value)
    resolved = (root / Path(*PurePosixPath(value).parts)).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("HermesProject asset escapes project directory")
    return resolved


def _validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"HermesProject asset path must be safe and relative: {value}")


def _existing_file(value: str | Path, name: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"HermesProject {name} file not found: {path}")
    return path


def _validate_events_file(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != EVENT_SCHEMA:
        raise ValueError(f"Recording events must use schema {EVENT_SCHEMA}")
    if not isinstance(payload.get("events"), list):
        raise ValueError("Recording events must contain events list")


def validate_project_timeline(payload: Any) -> None:
    if not isinstance(payload, dict) or set(payload) != {"tracks"}:
        raise ValueError("HermesProject timeline must contain only tracks")
    tracks = payload["tracks"]
    if not isinstance(tracks, list):
        raise ValueError("HermesProject timeline tracks must be a list")
    identifiers: set[str] = set()
    for track in tracks:
        if not isinstance(track, dict):
            raise ValueError("HermesProject timeline track must be an object")
        identifier = track.get("id")
        track_type = track.get("type")
        segments = track.get("segments")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("HermesProject timeline track requires an id")
        if identifier in identifiers:
            raise ValueError(f"HermesProject timeline track id is duplicated: {identifier}")
        identifiers.add(identifier)
        if not isinstance(track_type, str) or not track_type:
            raise ValueError("HermesProject timeline track requires a type")
        if not isinstance(segments, list):
            raise ValueError("HermesProject timeline track segments must be a list")
        if track_type == "camera.zoom":
            _validate_camera_zoom_track(track)
        if track_type == "cursor.motion":
            _validate_cursor_motion_track(track)


def validate_project_composition(payload: Any) -> None:
    if not isinstance(payload, dict) or set(payload) != {
        "preset", "canvas", "background", "frame"
    }:
        raise ValueError("HermesProject composition has invalid fields")
    preset = payload["preset"]
    if not isinstance(preset, str) or not preset:
        raise ValueError("HermesProject composition preset is invalid")

    canvas = payload["canvas"]
    if not isinstance(canvas, dict) or set(canvas) != {
        "width", "height", "aspect_ratio"
    }:
        raise ValueError("HermesProject canvas is invalid")
    width, height = canvas["width"], canvas["height"]
    if (
        not isinstance(width, int) or isinstance(width, bool) or width <= 0
        or not isinstance(height, int) or isinstance(height, bool) or height <= 0
    ):
        raise ValueError("HermesProject canvas dimensions must be positive integers")
    divisor = math.gcd(width, height)
    expected_ratio = f"{width // divisor}:{height // divisor}"
    if canvas["aspect_ratio"] != expected_ratio:
        raise ValueError("HermesProject canvas aspect ratio does not match dimensions")

    _validate_project_background(payload["background"])
    frame = payload["frame"]
    if not isinstance(frame, dict) or set(frame) != {
        "fit", "padding", "corner_radius", "shadow"
    }:
        raise ValueError("HermesProject frame is invalid")
    if frame["fit"] not in {"contain", "cover"}:
        raise ValueError("HermesProject frame fit is invalid")
    padding = frame["padding"]
    radius = frame["corner_radius"]
    if (
        not isinstance(padding, int) or isinstance(padding, bool) or padding < 0
        or padding * 2 >= width or padding * 2 >= height
    ):
        raise ValueError("HermesProject frame padding is invalid")
    if (
        not isinstance(radius, int) or isinstance(radius, bool) or radius < 0
        or radius * 2 > min(width - 2 * padding, height - 2 * padding)
    ):
        raise ValueError("HermesProject frame corner radius is invalid")
    _validate_project_shadow(frame["shadow"])


def _normalize_project_composition(payload: Any) -> Any:
    if not isinstance(payload, dict) or "preset" in payload:
        return payload
    if set(payload) != {"canvas", "background", "frame"}:
        return payload
    canvas = payload.get("canvas")
    background = payload.get("background")
    frame = payload.get("frame")
    if (
        not isinstance(canvas, dict) or set(canvas) != {"width", "height"}
        or not isinstance(frame, dict)
        or set(frame) != {"padding", "corner_radius", "shadow"}
        or not isinstance(frame.get("shadow"), bool)
    ):
        return payload
    width, height = canvas.get("width"), canvas.get("height")
    if (
        not isinstance(width, int) or isinstance(width, bool) or width <= 0
        or not isinstance(height, int) or isinstance(height, bool) or height <= 0
    ):
        return payload
    divisor = math.gcd(width, height)
    shadow_enabled = frame["shadow"]
    return {
        "preset": "legacy",
        "canvas": {
            "width": width,
            "height": height,
            "aspect_ratio": f"{width // divisor}:{height // divisor}",
        },
        "background": background,
        "frame": {
            "fit": "contain",
            "padding": frame["padding"],
            "corner_radius": frame["corner_radius"],
            "shadow": {
                "enabled": shadow_enabled,
                "color": "#000000",
                "opacity": 0.28 if shadow_enabled else 0.0,
                "blur": 48 if shadow_enabled else 0,
                "offset_x": 0,
                "offset_y": 18 if shadow_enabled else 0,
            },
        },
    }


def _validate_project_background(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("HermesProject background is invalid")
    if payload.get("type") == "color":
        if set(payload) != {"type", "value"} or not _is_hex_color(payload["value"]):
            raise ValueError("HermesProject color background is invalid")
        return
    if payload.get("type") == "linear_gradient":
        colors = payload.get("colors")
        angle = payload.get("angle_degrees")
        if (
            set(payload) != {"type", "colors", "angle_degrees"}
            or not isinstance(colors, list) or not 2 <= len(colors) <= 4
            or any(not _is_hex_color(color) for color in colors)
            or not isinstance(angle, (int, float)) or isinstance(angle, bool)
            or not math.isfinite(angle) or not 0 <= angle < 360
        ):
            raise ValueError("HermesProject gradient background is invalid")
        return
    raise ValueError("HermesProject background type is invalid")


def _validate_project_shadow(payload: Any) -> None:
    if not isinstance(payload, dict) or set(payload) != {
        "enabled", "color", "opacity", "blur", "offset_x", "offset_y"
    }:
        raise ValueError("HermesProject frame shadow is invalid")
    if not isinstance(payload["enabled"], bool) or not _is_hex_color(payload["color"]):
        raise ValueError("HermesProject frame shadow is invalid")
    opacity = payload["opacity"]
    if (
        not isinstance(opacity, (int, float)) or isinstance(opacity, bool)
        or not math.isfinite(opacity) or not 0 <= opacity <= 1
    ):
        raise ValueError("HermesProject frame shadow opacity is invalid")
    for name in ("blur", "offset_x", "offset_y"):
        value = payload[name]
        if (
            not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError(f"HermesProject frame shadow field is invalid: {name}")
    if payload["blur"] < 0:
        raise ValueError("HermesProject frame shadow blur is invalid")


def _is_hex_color(value: Any) -> bool:
    return isinstance(value, str) and HEX_COLOR_PATTERN.fullmatch(value) is not None


def _validate_camera_zoom_track(track: dict[str, Any]) -> None:
    if set(track) != {"id", "type", "source", "settings", "segments"}:
        raise ValueError("HermesProject camera zoom track has invalid fields")
    if track["source"] != "automatic":
        raise ValueError("HermesProject camera zoom track source must be automatic")
    settings = track["settings"]
    if not isinstance(settings, dict):
        raise ValueError("HermesProject camera zoom settings must be an object")
    expected_settings = {
        "scale", "lead_seconds", "hold_seconds", "transition_seconds",
        "target_margin", "merge_distance", "easing",
    }
    if set(settings) != expected_settings or settings["easing"] != "ease_in_out_cubic":
        raise ValueError("HermesProject camera zoom settings are invalid")
    for name in expected_settings - {"easing"}:
        value = settings[name]
        if (
            not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value < 0
        ):
            raise ValueError(f"HermesProject camera zoom setting is invalid: {name}")
    if settings["scale"] < 1:
        raise ValueError("HermesProject camera zoom scale must be at least 1")

    previous_end = -1.0
    expected_segment_fields = {
        "start_seconds", "focus_seconds", "hold_until_seconds", "end_seconds",
        "scale", "focus", "source_event_sequences",
    }
    for segment in track["segments"]:
        if not isinstance(segment, dict) or set(segment) != expected_segment_fields:
            raise ValueError("HermesProject camera zoom segment is invalid")
        times = [
            segment["start_seconds"], segment["focus_seconds"],
            segment["hold_until_seconds"], segment["end_seconds"],
        ]
        if any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value < 0
            for value in times
        ) or times != sorted(times):
            raise ValueError("HermesProject camera zoom segment times are invalid")
        if times[0] < previous_end:
            raise ValueError("HermesProject camera zoom segments must not overlap")
        previous_end = times[-1]
        scale = segment["scale"]
        focus = segment["focus"]
        sequences = segment["source_event_sequences"]
        if (
            not isinstance(scale, (int, float)) or isinstance(scale, bool)
            or not math.isfinite(scale) or scale < 1
        ):
            raise ValueError("HermesProject camera zoom segment scale is invalid")
        if (
            not isinstance(focus, dict) or set(focus) != {"x", "y"}
            or any(
                not isinstance(focus[name], (int, float))
                or isinstance(focus[name], bool)
                or not math.isfinite(focus[name])
                for name in ("x", "y")
            )
        ):
            raise ValueError("HermesProject camera zoom segment focus is invalid")
        if (
            not isinstance(sequences, list) or not sequences
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in sequences
            )
        ):
            raise ValueError("HermesProject camera zoom event references are invalid")


def _validate_cursor_motion_track(track: dict[str, Any]) -> None:
    expected_fields = {"id", "type", "source", "settings", "anchors", "segments"}
    if set(track) != expected_fields:
        raise ValueError("HermesProject cursor motion track has invalid fields")
    if track["source"] != "automatic":
        raise ValueError("HermesProject cursor motion track source must be automatic")
    settings = track["settings"]
    expected_settings = {
        "speed_pixels_per_second", "minimum_move_seconds",
        "maximum_move_seconds", "settle_seconds", "tension", "easing",
    }
    if (
        not isinstance(settings, dict) or set(settings) != expected_settings
        or settings["easing"] != "ease_in_out_cubic"
    ):
        raise ValueError("HermesProject cursor motion settings are invalid")
    for name in expected_settings - {"easing"}:
        value = settings[name]
        if (
            not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value < 0
        ):
            raise ValueError(f"HermesProject cursor motion setting is invalid: {name}")
    if settings["speed_pixels_per_second"] <= 0:
        raise ValueError("HermesProject cursor speed must be positive")
    if settings["minimum_move_seconds"] > settings["maximum_move_seconds"]:
        raise ValueError("HermesProject cursor move duration range is invalid")
    if settings["tension"] > 1:
        raise ValueError("HermesProject cursor tension must not exceed 1")

    anchors = track["anchors"]
    if not isinstance(anchors, list):
        raise ValueError("HermesProject cursor anchors must be a list")
    previous_time = -1.0
    for anchor in anchors:
        if not isinstance(anchor, dict) or set(anchor) != {
            "time_seconds", "position", "action", "source_event_sequence"
        }:
            raise ValueError("HermesProject cursor anchor is invalid")
        timestamp = anchor["time_seconds"]
        sequence = anchor["source_event_sequence"]
        if not _is_finite_non_negative(timestamp) or timestamp < previous_time:
            raise ValueError("HermesProject cursor anchor times are invalid")
        previous_time = timestamp
        if not isinstance(anchor["action"], str) or not anchor["action"]:
            raise ValueError("HermesProject cursor anchor action is invalid")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError("HermesProject cursor anchor event reference is invalid")
        _validate_cursor_point(anchor["position"])

    previous_end = -1.0
    expected_segment_fields = {
        "start_seconds", "end_seconds", "arrival_seconds", "from", "to",
        "control_1", "control_2", "source_event_sequences",
    }
    for segment in track["segments"]:
        if not isinstance(segment, dict) or set(segment) != expected_segment_fields:
            raise ValueError("HermesProject cursor motion segment is invalid")
        times = [
            segment["start_seconds"], segment["end_seconds"],
            segment["arrival_seconds"],
        ]
        if any(not _is_finite_non_negative(value) for value in times):
            raise ValueError("HermesProject cursor motion segment times are invalid")
        if times != sorted(times) or times[0] < previous_end:
            raise ValueError("HermesProject cursor motion segments must not overlap")
        previous_end = times[1]
        for name in ("from", "to", "control_1", "control_2"):
            _validate_cursor_point(segment[name])
        sequences = segment["source_event_sequences"]
        if (
            not isinstance(sequences, list) or len(sequences) != 2
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in sequences
            )
        ):
            raise ValueError("HermesProject cursor motion event references are invalid")


def _validate_cursor_point(payload: Any) -> None:
    if (
        not isinstance(payload, dict) or set(payload) != {"x", "y"}
        or any(not _is_finite_non_negative(payload[name]) for name in ("x", "y"))
    ):
        raise ValueError("HermesProject cursor point is invalid")


def _is_finite_non_negative(value: Any) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and value >= 0
    )


def _asset_for_file(path: Path, relative: str) -> ProjectAsset:
    return ProjectAsset(path=relative, size_bytes=path.stat().st_size, sha256=_sha256(path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
