from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from hermes_screencast.project import validate_hermes_project
from hermes_screencast.verifier import verify_mp4


SUPPORTED_RENDER_TRACKS = {"camera.zoom", "time.edit"}
RENDER_FPS = 30


class UnsupportedRenderTracksError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderPlan:
    source: Path
    output: Path
    command: tuple[str, ...]
    filter_complex: str
    unsupported_tracks: tuple[str, ...]
    estimated_duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source), "output": str(self.output),
            "command": list(self.command), "filter_complex": self.filter_complex,
            "unsupported_tracks": list(self.unsupported_tracks),
            "estimated_duration_seconds": self.estimated_duration_seconds,
        }


def build_render_plan(
    project_directory: str | Path,
    output_file: str | Path,
    *,
    allow_unrendered: bool = False,
    ffmpeg: str = "ffmpeg",
) -> RenderPlan:
    root = Path(project_directory).expanduser().resolve()
    project = validate_hermes_project(root)
    source = root / Path(*PurePosixPath(project.assets["video"].path).parts)
    output = Path(output_file).expanduser().resolve()
    if output.suffix.lower() != ".mp4":
        raise ValueError("Rendered output must use .mp4 extension")
    if output == source:
        raise ValueError("Rendered output must not overwrite the source MP4")
    unsupported = tuple(sorted({
        track["type"] for track in project.timeline["tracks"]
        if track["type"] not in SUPPORTED_RENDER_TRACKS
    }))
    if unsupported and not allow_unrendered:
        raise UnsupportedRenderTracksError(
            "Renderer does not yet support tracks: " + ", ".join(unsupported)
        )
    time_track = next(
        (track for track in project.timeline["tracks"] if track["type"] == "time.edit"),
        None,
    )
    camera_track = next(
        (
            track for track in project.timeline["tracks"]
            if track["type"] == "camera.zoom"
        ),
        None,
    )
    event_log = _load_event_log(root, project)
    source_duration = _source_duration(event_log, time_track)
    source_width, source_height = _source_dimensions(
        event_log, project.composition
    )
    estimated = (
        float(time_track["summary"]["estimated_duration_seconds"])
        if time_track is not None else source_duration
    )
    graph = _build_filter_graph(
        project.composition,
        camera_track,
        time_track,
        source_duration,
        max(estimated, 0.001),
        source_width,
        source_height,
    )
    command = (
        ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-i", str(source),
        "-filter_complex", graph, "-map", "[outv]", "-an", "-c:v", "libx264",
        "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(output),
    )
    return RenderPlan(source, output, command, graph, unsupported, estimated)


def render_hermes_project(
    project_directory: str | Path,
    output_file: str | Path,
    *,
    allow_unrendered: bool = False,
    runner: Callable[..., Any] = subprocess.run,
    verifier: Callable[[Path], Path] = verify_mp4,
) -> Path:
    plan = build_render_plan(
        project_directory, output_file, allow_unrendered=allow_unrendered
    )
    plan.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = runner(list(plan.command), capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required to render HermesProject") from exc
    if result.returncode != 0:
        error = (result.stderr or "unknown ffmpeg error").strip()
        raise RuntimeError(f"HermesProject render failed: {error}")
    verifier(plan.output)
    return plan.output


def _build_filter_graph(
    composition: dict[str, Any],
    camera_track: dict[str, Any] | None,
    time_track: dict[str, Any] | None,
    source_duration: float,
    output_duration: float,
    source_width: int,
    source_height: int,
) -> str:
    filters: list[str] = []
    source_label = _append_camera_filter(
        filters, camera_track, source_width, source_height
    )
    timed_label = _append_time_filters(
        filters, time_track, source_duration, source_label
    )
    canvas = composition["canvas"]
    frame = composition["frame"]
    width, height, padding = canvas["width"], canvas["height"], frame["padding"]
    content_width, content_height = width - 2 * padding, height - 2 * padding
    fit = "decrease" if frame["fit"] == "contain" else "increase"
    frame_filters = (
        f"[{timed_label}]scale={content_width}:{content_height}:force_original_aspect_ratio={fit},"
        f"crop='min(iw,{content_width})':'min(ih,{content_height})',"
        f"pad={content_width}:{content_height}:(ow-iw)/2:(oh-ih)/2:color=black,format=rgba"
    )
    radius = frame["corner_radius"]
    if radius > 0:
        alpha = (
            f"if(lte(hypot({radius}-min({radius},min(X,W-X)),"
            f"{radius}-min({radius},min(Y,H-Y))),{radius}),255,0)"
        )
        frame_filters += (
            f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{alpha}'"
        )
    filters.append(frame_filters + "[frame]")
    filters.append(_background_filter(composition["background"], width, height, output_duration))
    shadow = frame["shadow"]
    if shadow["enabled"]:
        filters.append(
            f"[frame]split[frame_main][shadow_src];[shadow_src]colorchannelmixer=rr=0:gg=0:bb=0:aa={shadow['opacity']},"
            f"gblur=sigma={max(0.1, shadow['blur'] / 3):.3f}[shadow]"
        )
        filters.append(
            f"[bg][shadow]overlay={padding + shadow['offset_x']}:{padding + shadow['offset_y']}:shortest=1[with_shadow]"
        )
        base = "with_shadow"
        frame_label = "frame_main"
    else:
        base, frame_label = "bg", "frame"
    filters.append(
        f"[{base}][{frame_label}]overlay={padding}:{padding}:shortest=1,fps=30,format=yuv420p[outv]"
    )
    return ";".join(filters)


def _append_time_filters(
    filters: list[str],
    track: dict[str, Any] | None,
    duration: float,
    input_label: str,
) -> str:
    if track is None or not track["segments"]:
        filters.append(f"[{input_label}]setpts=PTS-STARTPTS[timed]")
        return "timed"
    pieces: list[tuple[float, float, float]] = []
    cursor = 0.0
    for segment in track["segments"]:
        start, end = float(segment["start_seconds"]), float(segment["end_seconds"])
        if start > cursor:
            pieces.append((cursor, start, 1.0))
        if segment["mode"] == "speed":
            pieces.append((start, end, float(segment["speed_factor"])))
        cursor = end
    if cursor < duration:
        pieces.append((cursor, duration, 1.0))
    if not pieces:
        raise ValueError("Time edit removes the complete source video")
    labels = []
    for index, (start, end, speed) in enumerate(pieces):
        label = f"part{index}"
        filters.append(
            f"[{input_label}]trim=start={start:.6f}:end={end:.6f},"
            f"setpts=(PTS-STARTPTS)/{speed:.6f}[{label}]"
        )
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[timed]")
    return "timed"


def _append_camera_filter(
    filters: list[str], track: dict[str, Any] | None, width: int, height: int
) -> str:
    if track is None or not track["segments"]:
        return "0:v"
    zoom = "1"
    x = "(iw-iw/zoom)/2"
    y = "(ih-ih/zoom)/2"
    for segment in reversed(track["segments"]):
        start = float(segment["start_seconds"]) * RENDER_FPS
        focus = float(segment["focus_seconds"]) * RENDER_FPS
        hold = float(segment["hold_until_seconds"]) * RENDER_FPS
        end = float(segment["end_seconds"]) * RENDER_FPS
        scale = float(segment["scale"])
        rise = _zoom_transition("1", f"{scale:.6f}", start, focus)
        fall = _zoom_transition(f"{scale:.6f}", "1", hold, end)
        active_zoom = (
            f"if(lt(on,{focus:.6f}),{rise},"
            f"if(lte(on,{hold:.6f}),{scale:.6f},{fall}))"
        )
        active = f"between(on,{start:.6f},{end:.6f})"
        zoom = f"if({active},{active_zoom},{zoom})"
        focus_x = float(segment["focus"]["x"]) / width
        focus_y = float(segment["focus"]["y"]) / height
        target_x = f"max(0,min(iw-iw/zoom,{focus_x:.9f}*iw-iw/zoom/2))"
        target_y = f"max(0,min(ih-ih/zoom,{focus_y:.9f}*ih-ih/zoom/2))"
        x = f"if({active},{target_x},{x})"
        y = f"if({active},{target_y},{y})"
    filters.append(
        f"[0:v]fps={RENDER_FPS},zoompan=z='{zoom}':x='{x}':y='{y}':d=1:"
        f"s={width}x{height}:fps={RENDER_FPS}[camera]"
    )
    return "camera"


def _zoom_transition(
    start_value: str, end_value: str, start_frame: float, end_frame: float
) -> str:
    if end_frame <= start_frame:
        return end_value
    progress = (
        f"max(0,min(1,(on-{start_frame:.6f})/"
        f"{end_frame - start_frame:.6f}))"
    )
    eased = f"({progress})*({progress})*(3-2*({progress}))"
    return f"({start_value})+(({end_value})-({start_value}))*({eased})"


def _background_filter(background: dict[str, Any], width: int, height: int, duration: float) -> str:
    if background["type"] == "color":
        return f"color=c={background['value']}:s={width}x{height}:r=30:d={duration:.6f}[bg]"
    colors = background["colors"]
    if len(colors) != 2:
        raise ValueError("Renderer currently supports two-color gradients")
    angle = math.radians(float(background["angle_degrees"]))
    cx, cy = width / 2, height / 2
    dx, dy = math.cos(angle) * width / 2, math.sin(angle) * height / 2
    return (
        f"gradients=s={width}x{height}:c0={colors[0]}:c1={colors[1]}:"
        f"x0={round(cx-dx)}:y0={round(cy-dy)}:x1={round(cx+dx)}:y1={round(cy+dy)}:d={duration:.6f}[bg]"
    )


def _load_event_log(root: Path, project) -> dict[str, Any]:
    path = root / Path(*PurePosixPath(project.assets["events"].path).parts)
    return json.loads(path.read_text(encoding="utf-8"))


def _source_duration(
    payload: dict[str, Any], time_track: dict[str, Any] | None
) -> float:
    if time_track is not None:
        return float(time_track["summary"]["source_duration_seconds"])
    times = [
        float(event["time_seconds"]) for event in payload.get("events", [])
        if isinstance(event, dict) and event.get("type") == "recording_finished"
        and isinstance(event.get("time_seconds"), (int, float))
    ]
    if not times:
        raise ValueError("Renderer requires recording duration or a time edit summary")
    return max(times)


def _source_dimensions(
    payload: dict[str, Any], composition: dict[str, Any]
) -> tuple[int, int]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    canvas = composition["canvas"]
    width = metadata.get("width", canvas["width"])
    height = metadata.get("height", canvas["height"])
    if (
        not isinstance(width, (int, float)) or isinstance(width, bool)
        or not isinstance(height, (int, float)) or isinstance(height, bool)
        or not math.isfinite(width) or not math.isfinite(height)
        or width <= 0 or height <= 0
    ):
        raise ValueError("Renderer requires positive source video dimensions")
    return round(width), round(height)
