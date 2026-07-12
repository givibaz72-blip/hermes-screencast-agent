from __future__ import annotations

import html
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any

from hermes_screencast.project import validate_hermes_project


TRACK_COLORS = {
    "camera.zoom": "#8B5CF6",
    "cursor.motion": "#38BDF8",
    "annotation.overlay": "#FACC15",
    "time.edit": "#FB7185",
}


def build_project_preview_model(project_directory: str | Path) -> dict[str, Any]:
    root = Path(project_directory).expanduser().resolve()
    project = validate_hermes_project(root)
    events_asset = project.assets["events"]
    events_path = root / Path(*PurePosixPath(events_asset.path).parts)
    event_log = json.loads(events_path.read_text(encoding="utf-8"))
    duration = _source_duration(event_log, project.timeline["tracks"])
    time_track = next(
        (track for track in project.timeline["tracks"] if track.get("type") == "time.edit"),
        None,
    )
    estimated = (
        time_track["summary"]["estimated_duration_seconds"]
        if time_track is not None else duration
    )
    tracks = [_preview_track(track) for track in project.timeline["tracks"]]
    return {
        "schema": "hermes.preview.v1",
        "title": project.title,
        "source_duration_seconds": duration,
        "estimated_duration_seconds": estimated,
        "composition": project.composition,
        "tracks": tracks,
    }


def write_project_preview(
    project_directory: str | Path, output_file: str | Path | None = None
) -> Path:
    root = Path(project_directory).expanduser().resolve()
    model = build_project_preview_model(root)
    output = (
        Path(output_file).expanduser().resolve()
        if output_file is not None else root / "preview.html"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_preview_html(model), encoding="utf-8")
    return output


def _preview_track(track: dict[str, Any]) -> dict[str, Any]:
    track_type = track["type"]
    segments = []
    for segment in track["segments"]:
        start = float(segment.get("start_seconds", 0))
        end = float(
            segment.get("end_seconds", segment.get("arrival_seconds", start))
        )
        segments.append({
            "start_seconds": start,
            "end_seconds": end,
            "label": _segment_label(track_type, segment),
            "detail": segment,
        })
    return {
        "id": track["id"],
        "type": track_type,
        "color": TRACK_COLORS.get(track_type, "#94A3B8"),
        "segments": segments,
        "anchor_count": len(track.get("anchors", [])),
    }


def _segment_label(track_type: str, segment: dict[str, Any]) -> str:
    if track_type == "camera.zoom":
        return f"{segment['scale']}x zoom"
    if track_type == "cursor.motion":
        return "cursor move"
    if track_type == "annotation.overlay":
        return f"{segment['kind']}: {segment['id']}"
    if track_type == "time.edit":
        return f"{segment['mode']}: {segment['reason']}"
    return segment.get("id", "segment")


def _source_duration(event_log: dict[str, Any], tracks: list[dict[str, Any]]) -> float:
    times = [
        float(event["time_seconds"])
        for event in event_log.get("events", [])
        if isinstance(event, dict)
        and isinstance(event.get("time_seconds"), (int, float))
        and not isinstance(event.get("time_seconds"), bool)
        and math.isfinite(event["time_seconds"])
    ]
    for track in tracks:
        summary = track.get("summary")
        if isinstance(summary, dict):
            value = summary.get("source_duration_seconds")
            if isinstance(value, (int, float)) and math.isfinite(value):
                times.append(float(value))
        for segment in track.get("segments", []):
            for name in ("end_seconds", "arrival_seconds"):
                value = segment.get(name)
                if isinstance(value, (int, float)) and math.isfinite(value):
                    times.append(float(value))
    return round(max(times, default=0.0), 6)


def _render_preview_html(model: dict[str, Any]) -> str:
    duration = max(float(model["source_duration_seconds"]), 0.001)
    composition = model["composition"]
    canvas = composition["canvas"]
    frame = composition["frame"]
    shadow = frame["shadow"]
    background = composition["background"]
    if background["type"] == "color":
        background_css = background["value"]
    else:
        background_css = (
            f"linear-gradient({background['angle_degrees']}deg, "
            + ", ".join(background["colors"])
            + ")"
        )
    shadow_css = "none"
    if shadow["enabled"]:
        shadow_css = (
            f"{shadow['offset_x']}px {shadow['offset_y']}px {shadow['blur']}px "
            f"{_hex_with_opacity(shadow['color'], shadow['opacity'])}"
        )
    track_rows = "\n".join(_render_track_row(track, duration) for track in model["tracks"])
    if not track_rows:
        track_rows = '<div class="empty">No generated timeline tracks yet.</div>'
    safe_title = html.escape(model["title"])
    json_text = json.dumps(model, ensure_ascii=False, indent=2)
    safe_json_script = json.dumps(model, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title} · Hermes preview</title>
<style>
:root{{--bg:#070b14;--panel:#101827;--line:#263247;--muted:#94a3b8;--text:#f8fafc}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at top,#172036,var(--bg) 55%);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,sans-serif}}
main{{width:min(1180px,calc(100% - 32px));margin:32px auto 56px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:24px}}h1{{font-size:28px;margin:0 0 4px}}.muted{{color:var(--muted)}}.stats{{display:flex;gap:10px;flex-wrap:wrap}}.pill{{padding:8px 12px;border:1px solid var(--line);background:#0d1422;border-radius:999px}}
.grid{{display:grid;grid-template-columns:minmax(300px,0.9fr) minmax(420px,1.4fr);gap:20px}}.panel{{background:color-mix(in srgb,var(--panel) 94%,transparent);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 22px 70px #0006}}
.canvas-wrap{{display:grid;place-items:center;min-height:360px;padding:18px;border-radius:14px;background:{background_css}}}.frame{{width:min(100%,640px);aspect-ratio:{canvas['width']}/{canvas['height']};margin:{max(0, frame['padding'] / canvas['width'] * 100):.2f}%;border-radius:{frame['corner_radius']}px;background:linear-gradient(145deg,#e2e8f0,#64748b);box-shadow:{shadow_css};display:grid;place-items:center;color:#0f172a;font-weight:700;overflow:hidden}}.frame span{{background:#ffffffd9;padding:10px 14px;border-radius:10px}}
.timeline{{margin-top:20px}}.scrubber{{display:flex;align-items:center;gap:12px;margin:12px 0 18px}}input[type=range]{{width:100%;accent-color:#8b5cf6}}.track{{display:grid;grid-template-columns:150px 1fr;gap:12px;align-items:center;margin:10px 0}}.track-label{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#cbd5e1}}.lane{{height:34px;position:relative;border:1px solid var(--line);border-radius:9px;background:repeating-linear-gradient(90deg,#0b1220 0,#0b1220 calc(10% - 1px),#243047 10%)}}.segment{{position:absolute;top:5px;height:22px;border-radius:6px;min-width:3px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;padding:2px 7px;color:#07111f;font-size:11px;font-weight:700}}.playhead{{position:absolute;top:-5px;bottom:-5px;width:2px;background:#fff;box-shadow:0 0 10px #fff8;pointer-events:none}}.empty{{color:var(--muted);padding:20px;text-align:center}}details{{margin-top:20px}}pre{{overflow:auto;background:#080d17;border:1px solid var(--line);padding:16px;border-radius:12px;color:#cbd5e1}}
@media(max-width:820px){{.grid{{grid-template-columns:1fr}}header{{align-items:start;flex-direction:column}}.track{{grid-template-columns:110px 1fr}}}}
</style></head><body><main>
<header><div><div class="muted">HermesProject preview</div><h1>{safe_title}</h1><div class="muted">{html.escape(composition['preset'])} · {canvas['width']}×{canvas['height']} · {canvas['aspect_ratio']}</div></div><div class="stats"><div class="pill">Source {model['source_duration_seconds']:.2f}s</div><div class="pill">Estimated {model['estimated_duration_seconds']:.2f}s</div><div class="pill">{len(model['tracks'])} tracks</div></div></header>
<div class="grid"><section class="panel"><h2>Composition</h2><div class="canvas-wrap"><div class="frame"><span>Source video frame</span></div></div></section><section class="panel"><h2>Timeline</h2><div class="scrubber"><input id="scrubber" type="range" min="0" max="{duration}" step="0.01" value="0"><output id="time">0.00s</output></div><div class="timeline">{track_rows}</div></section></div>
<details class="panel"><summary>Preview data</summary><pre>{html.escape(json_text)}</pre></details>
<script type="application/json" id="hermes-preview-data">{safe_json_script}</script><script>const s=document.getElementById('scrubber'),t=document.getElementById('time'),heads=[...document.querySelectorAll('.playhead')];function draw(){{const p=(Number(s.value)/Number(s.max))*100;t.value=Number(s.value).toFixed(2)+'s';heads.forEach(h=>h.style.left=p+'%')}}s.addEventListener('input',draw);draw();</script>
</main></body></html>"""


def _render_track_row(track: dict[str, Any], duration: float) -> str:
    segments = []
    for segment in track["segments"]:
        left = max(0.0, min(100.0, segment["start_seconds"] / duration * 100))
        width = max(0.2, min(100.0 - left, (segment["end_seconds"] - segment["start_seconds"]) / duration * 100))
        label = html.escape(segment["label"])
        segments.append(
            f'<div class="segment" title="{label}" style="left:{left:.4f}%;width:{width:.4f}%;background:{track["color"]}">{label}</div>'
        )
    return (
        f'<div class="track"><div class="track-label" title="{html.escape(track["type"])}">'
        f'{html.escape(track["id"])} <span class="muted">({len(track["segments"])})</span></div>'
        f'<div class="lane">{"".join(segments)}<div class="playhead"></div></div></div>'
    )


def _hex_with_opacity(color: str, opacity: float) -> str:
    if len(color) == 9:
        return color
    alpha = round(max(0.0, min(1.0, opacity)) * 255)
    return f"{color}{alpha:02X}"
