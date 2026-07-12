from __future__ import annotations

import json
import math
import subprocess
import time
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from hermes_screencast.project import validate_hermes_project
from hermes_screencast.verifier import verify_mp4


SUPPORTED_RENDER_TRACKS = {
    "annotation.overlay", "camera.zoom", "cursor.motion", "time.edit",
}
RENDER_FPS = 30
VIDEO_ENCODERS = {
    "software": "libx264", "nvenc": "h264_nvenc",
    "qsv": "h264_qsv", "amf": "h264_amf",
}


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
    has_audio: bool
    video_encoder: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source), "output": str(self.output),
            "command": list(self.command), "filter_complex": self.filter_complex,
            "unsupported_tracks": list(self.unsupported_tracks),
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "has_audio": self.has_audio,
            "video_encoder": self.video_encoder,
        }


def build_render_plan(
    project_directory: str | Path,
    output_file: str | Path,
    *,
    allow_unrendered: bool = False,
    ffmpeg: str = "ffmpeg",
    audio_probe: Callable[[Path], bool] | None = None,
    video_encoder: str = "software",
    encoder_probe: Callable[[str], bool] | None = None,
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
    cursor_track = next(
        (
            track for track in project.timeline["tracks"]
            if track["type"] == "cursor.motion"
        ),
        None,
    )
    annotation_track = next(
        (
            track for track in project.timeline["tracks"]
            if track["type"] == "annotation.overlay"
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
        cursor_track,
        annotation_track,
        time_track,
        source_duration,
        max(estimated, 0.001),
        source_width,
        source_height,
    )
    has_audio = (audio_probe or _has_audio_stream)(source)
    selected_encoder = _select_video_encoder(video_encoder, encoder_probe)
    if has_audio:
        graph += ";" + _audio_filter_graph(time_track, source_duration)
    command_parts = [
        ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-i", str(source),
        "-filter_complex", graph, "-map", "[outv]",
    ]
    if has_audio:
        command_parts.extend(["-map", "[outa]", "-c:a", "aac", "-b:a", "192k"])
    else:
        command_parts.append("-an")
    command_parts.extend(_video_encoder_args(selected_encoder))
    command_parts.extend(["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)])
    command = tuple(command_parts)
    return RenderPlan(
        source, output, command, graph, unsupported, estimated, has_audio,
        selected_encoder,
    )


def render_hermes_project(
    project_directory: str | Path,
    output_file: str | Path,
    *,
    allow_unrendered: bool = False,
    video_encoder: str = "auto",
    runner: Callable[..., Any] = subprocess.run,
    verifier: Callable[[Path], Path] = verify_mp4,
) -> Path:
    plan = build_render_plan(
        project_directory, output_file, allow_unrendered=allow_unrendered,
        video_encoder=video_encoder,
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
    cursor_track: dict[str, Any] | None,
    annotation_track: dict[str, Any] | None,
    time_track: dict[str, Any] | None,
    source_duration: float,
    output_duration: float,
    source_width: int,
    source_height: int,
) -> str:
    filters: list[str] = []
    source_label = _append_cursor_filter(
        filters, cursor_track, source_duration
    )
    source_label = _append_camera_filter(
        filters, camera_track, source_width, source_height, source_label
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
    if annotation_track is None or not annotation_track["segments"]:
        filters.append(
            f"[{base}][{frame_label}]overlay={padding}:{padding}:shortest=1,"
            "fps=30,format=yuv420p[outv]"
        )
    else:
        filters.append(
            f"[{base}][{frame_label}]overlay={padding}:{padding}:shortest=1,"
            "fps=30,format=rgba[composed]"
        )
        _append_annotation_filters(
            filters, annotation_track, "composed"
        )
    return ";".join(filters)


def _append_annotation_filters(
    filters: list[str], track: dict[str, Any], input_label: str
) -> str:
    vector_script = " ".join(
        script for segment in track["segments"]
        if (script := _vector_annotation_script(segment))
    )
    label = input_label
    index = 0
    if vector_script:
        label = "annotations_vector"
        filters.append(
            f"[{input_label}]drawvg=script='{vector_script}'[{label}]"
        )
    for segment in track["segments"]:
        if segment["kind"] != "text":
            continue
        next_label = f"annotation_text_{index}"
        style = segment["style"]
        position = segment["position"]
        text = _escape_drawtext(segment["text"])
        font_file = _annotation_font_file(int(style["font_weight"]))
        filters.append(
            f"[{label}]drawtext=text='{text}':expansion=none:"
            f"fontfile='{font_file}':"
            f"fontcolor={style['color']}:fontsize={style['font_size']}:"
            f"x={position['x']}:y={position['y']}:box=1:"
            f"boxcolor={style['background_color']}:"
            f"boxborderw={style['padding']}:alpha={style['opacity']}:"
            f"enable='between(t,{segment['start_seconds']},{segment['end_seconds']})'"
            f"[{next_label}]"
        )
        label = next_label
        index += 1
    filters.append(f"[{label}]format=yuv420p[outv]")
    return "outv"


def _vector_annotation_script(segment: dict[str, Any]) -> str:
    kind = segment["kind"]
    if kind == "text":
        return ""
    start, end = segment["start_seconds"], segment["end_seconds"]
    style = segment["style"]
    color = f"{style['color']}@{style['opacity']}"
    if kind in {"box", "highlight"}:
        bounds = segment["bounds"]
        path = _rounded_rect_path(
            float(bounds["x"]), float(bounds["y"]),
            float(bounds["width"]), float(bounds["height"]),
            float(style["corner_radius"]),
        )
        operation = "fill" if kind == "highlight" else (
            f"setlinewidth {style['stroke_width']} setlinejoin round stroke"
        )
        return (
            f"if (between(t,{start},{end})) {{ {path} "
            f"setcolor {color} {operation} }}"
        )
    if kind == "arrow":
        origin, target = segment["from"], segment["to"]
        x1, y1 = float(origin["x"]), float(origin["y"])
        x2, y2 = float(target["x"]), float(target["y"])
        dx, dy = x2 - x1, y2 - y1
        length = max(math.hypot(dx, dy), 0.001)
        ux, uy = dx / length, dy / length
        head = float(style["head_size"])
        wing = head * 0.55
        left = (x2 - head * ux - wing * uy, y2 - head * uy + wing * ux)
        right = (x2 - head * ux + wing * uy, y2 - head * uy - wing * ux)
        return (
            f"if (between(t,{start},{end})) {{ setcolor {color} "
            f"setlinewidth {style['stroke_width']} setlinecap round "
            f"M {x1} {y1} L {x2} {y2} stroke "
            f"M {x2} {y2} L {left[0]} {left[1]} {right[0]} {right[1]} Z fill }}"
        )
    raise ValueError(f"Unsupported annotation kind: {kind}")


def _rounded_rect_path(
    x: float, y: float, width: float, height: float, radius: float
) -> str:
    radius = max(0.0, min(radius, width / 2, height / 2))
    if radius == 0:
        return f"rect {x} {y} {width} {height}"
    return (
        f"M {x+radius} {y} L {x+width-radius} {y} "
        f"arc {x+width-radius} {y+radius} {radius} (-PI/2) 0 "
        f"L {x+width} {y+height-radius} "
        f"arc {x+width-radius} {y+height-radius} {radius} 0 (PI/2) "
        f"L {x+radius} {y+height} "
        f"arc {x+radius} {y+height-radius} {radius} (PI/2) (PI) "
        f"L {x} {y+radius} arc {x+radius} {y+radius} {radius} (PI) (3*PI/2) Z"
    )


def _escape_drawtext(value: str) -> str:
    return (
        value.replace("\\", "\\\\").replace("'", "\\'")
        .replace(":", "\\:").replace("\n", "\\n")
    )


def _annotation_font_file(weight: int) -> str:
    bold = weight >= 600
    candidates = (
        [
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ] if bold else [
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        ]
    )
    font = next((path for path in candidates if path.is_file()), None)
    if font is None:
        raise ValueError("Text annotation rendering requires a system font")
    return font.as_posix().replace(":", "\\:").replace("'", "\\'")


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


def _audio_filter_graph(
    track: dict[str, Any] | None, duration: float
) -> str:
    if track is None or not track["segments"]:
        return "[0:a]asetpts=PTS-STARTPTS[outa]"
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
    filters = []
    labels = []
    for index, (start, end, speed) in enumerate(pieces):
        label = f"apart{index}"
        tempo = f",atempo={speed:.6f}" if speed != 1 else ""
        filters.append(
            f"[0:a]atrim=start={start:.6f}:end={end:.6f},"
            f"asetpts=PTS-STARTPTS{tempo}[{label}]"
        )
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[outa]")
    return ";".join(filters)


def _has_audio_stream(source: Path) -> bool:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=index", "-of", "csv=p=0", str(source),
            ],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _select_video_encoder(
    requested: str, probe: Callable[[str], bool] | None = None
) -> str:
    if requested not in {"auto", *VIDEO_ENCODERS}:
        raise ValueError(f"Unknown video encoder mode: {requested}")
    if requested != "auto":
        return VIDEO_ENCODERS[requested]
    if probe is not None:
        for mode in ("nvenc", "qsv", "amf"):
            encoder = VIDEO_ENCODERS[mode]
            if probe(encoder):
                return encoder
        return VIDEO_ENCODERS["software"]
    software = VIDEO_ENCODERS["software"]
    best_encoder = software
    best_score = _encoder_benchmark(software)
    for mode in ("nvenc", "qsv", "amf"):
        encoder = VIDEO_ENCODERS[mode]
        score = _encoder_benchmark(encoder)
        if score < best_score * 0.9:
            best_encoder, best_score = encoder, score
    return best_encoder


@lru_cache(maxsize=None)
def _encoder_benchmark(encoder: str) -> float:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc2=s=640x360:r=30:d=0.5",
                "-c:v", encoder, "-f", "null", "-",
            ],
            capture_output=True, text=True, check=False, timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return math.inf
    return time.perf_counter() - started if result.returncode == 0 else math.inf


def _video_encoder_args(encoder: str) -> list[str]:
    if encoder == "h264_nvenc":
        return ["-c:v", encoder, "-preset", "p5", "-cq", "18", "-b:v", "0"]
    if encoder == "h264_qsv":
        return ["-c:v", encoder, "-preset", "medium", "-global_quality", "18"]
    if encoder == "h264_amf":
        return ["-c:v", encoder, "-quality", "quality", "-qp_i", "18", "-qp_p", "18"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]


def _append_camera_filter(
    filters: list[str], track: dict[str, Any] | None, width: int, height: int,
    input_label: str,
) -> str:
    if track is None or not track["segments"]:
        return input_label
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
        f"[{input_label}]fps={RENDER_FPS},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:"
        f"s={width}x{height}:fps={RENDER_FPS}[camera]"
    )
    return "camera"


def _append_cursor_filter(
    filters: list[str], track: dict[str, Any] | None, duration: float
) -> str:
    if track is None or not track["anchors"]:
        return "0:v"
    x = _cursor_coordinate_expression(track, "x")
    y = _cursor_coordinate_expression(track, "y")
    click_script = _cursor_click_script(track)
    input_label = "0:v"
    if click_script:
        input_label = "cursor_clicks"
        filters.append(
            f"[0:v]drawvg=script='{click_script}'[{input_label}]"
        )
    outer = "between(Y,2,32)*between(X,2,2+0.72*(Y-2))"
    inner = "between(Y,5,28)*between(X,4,2+0.62*(Y-3))"
    filters.append(
        f"color=c=black@0:s=28x36:r={RENDER_FPS}:d={duration:.6f},"
        f"format=rgba,geq=r='if({inner},255,20)':"
        f"g='if({inner},255,20)':b='if({inner},255,20)':"
        f"a='if({outer},255,0)'[cursor_sprite]"
    )
    filters.append(
        f"[{input_label}][cursor_sprite]overlay=x='{x}-2':y='{y}-2':"
        "shortest=1:format=auto[cursor]"
    )
    return "cursor"


def _cursor_click_script(track: dict[str, Any]) -> str:
    duration = 0.35
    scripts = []
    for anchor in track["anchors"]:
        if anchor["action"] != "click":
            continue
        start = float(anchor["time_seconds"])
        end = start + duration
        x = float(anchor["position"]["x"])
        y = float(anchor["position"]["y"])
        progress = f"((t-{start:.6f})/{duration:.6f})"
        scripts.append(
            f"if (between(t,{start:.6f},{end:.6f})) {{ "
            f"circle {x:.6f} {y:.6f} (8+28*{progress}) "
            f"setrgba 1 1 1 (0.8*(1-{progress})) "
            "setlinewidth 4 stroke }"
        )
    return " ".join(scripts)


def _cursor_coordinate_expression(track: dict[str, Any], axis: str) -> str:
    anchors = track["anchors"]
    segments = track["segments"]
    if not segments:
        return f"{float(anchors[0]['position'][axis]):.6f}"
    expression = f"{float(segments[-1]['to'][axis]):.6f}"
    for segment in reversed(segments):
        start = float(segment["start_seconds"])
        end = float(segment["end_seconds"])
        moving = _cursor_bezier_expression(segment, axis, start, end)
        origin = float(segment["from"][axis])
        expression = (
            f"if(lt(t,{start:.6f}),{origin:.6f},"
            f"if(lte(t,{end:.6f}),{moving},{expression}))"
        )
    return expression


def _cursor_bezier_expression(
    segment: dict[str, Any], axis: str, start: float, end: float
) -> str:
    if end <= start:
        return f"{float(segment['to'][axis]):.6f}"
    progress = f"max(0,min(1,(t-{start:.6f})/{end-start:.6f}))"
    eased = f"({progress})*({progress})*(3-2*({progress}))"
    inverse = f"(1-({eased}))"
    p0 = float(segment["from"][axis])
    p1 = float(segment["control_1"][axis])
    p2 = float(segment["control_2"][axis])
    p3 = float(segment["to"][axis])
    return (
        f"({inverse})^3*{p0:.6f}+3*({inverse})^2*({eased})*{p1:.6f}+"
        f"3*({inverse})*({eased})^2*{p2:.6f}+({eased})^3*{p3:.6f}"
    )


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
