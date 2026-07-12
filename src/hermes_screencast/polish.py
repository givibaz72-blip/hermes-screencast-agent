from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_screencast.auto_edit import apply_auto_edit
from hermes_screencast.auto_zoom import apply_auto_zoom
from hermes_screencast.cursor_motion import apply_cursor_motion
from hermes_screencast.framing import apply_framing_preset
from hermes_screencast.preview import write_project_preview
from hermes_screencast.renderer import render_hermes_project


@dataclass(frozen=True)
class PolishResult:
    project: Path
    output: Path
    preview: Path
    zoom_segments: int
    cursor_segments: int
    edit_segments: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": str(self.project), "output": str(self.output),
            "preview": str(self.preview), "zoom_segments": self.zoom_segments,
            "cursor_segments": self.cursor_segments,
            "edit_segments": self.edit_segments,
        }


def polish_hermes_project(
    project_directory: str | Path,
    output_file: str | Path,
    *,
    preview_file: str | Path | None = None,
    preset: str = "studio",
    encoder: str = "auto",
    quality: str = "high",
    fade_in_seconds: float = 0.2,
    fade_out_seconds: float = 0.25,
    normalize_audio: bool = True,
) -> PolishResult:
    root = Path(project_directory).expanduser().resolve()
    output = Path(output_file).expanduser().resolve()
    preview = (
        Path(preview_file).expanduser().resolve()
        if preview_file is not None else output.with_suffix(".preview.html")
    )
    if preset != "keep":
        apply_framing_preset(root, preset=preset)
    zoom = apply_auto_zoom(root)
    cursor = apply_cursor_motion(root)
    edit = apply_auto_edit(root)
    duration = float(edit["summary"]["estimated_duration_seconds"])
    fade_in, fade_out = _fit_fades(
        fade_in_seconds, fade_out_seconds, duration
    )
    write_project_preview(root, preview)
    rendered = render_hermes_project(
        root, output, video_encoder=encoder, quality_profile=quality,
        fade_in_seconds=fade_in, fade_out_seconds=fade_out,
        normalize_audio=normalize_audio,
    )
    return PolishResult(
        root, rendered, preview, len(zoom["segments"]),
        len(cursor["segments"]), len(edit["segments"]),
    )


def _fit_fades(fade_in: float, fade_out: float, duration: float) -> tuple[float, float]:
    if fade_in < 0 or fade_out < 0:
        raise ValueError("Polish fade durations must be non-negative")
    total = fade_in + fade_out
    if total == 0 or total <= duration:
        return fade_in, fade_out
    scale = duration * 0.8 / total
    return fade_in * scale, fade_out * scale
