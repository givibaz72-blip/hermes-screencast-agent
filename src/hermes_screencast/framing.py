from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from hermes_screencast.project import (
    validate_hermes_project,
    validate_project_composition,
    validate_project_timeline,
)


FRAMING_PRESETS: dict[str, dict[str, Any]] = {
    "source": {
        "preset": "source",
        "canvas": {"width": 1920, "height": 1080, "aspect_ratio": "16:9"},
        "background": {"type": "color", "value": "#111827"},
        "frame": {
            "fit": "contain",
            "padding": 0,
            "corner_radius": 0,
            "shadow": {
                "enabled": False, "color": "#000000", "opacity": 0.0,
                "blur": 0, "offset_x": 0, "offset_y": 0,
            },
        },
    },
    "studio": {
        "preset": "studio",
        "canvas": {"width": 1920, "height": 1080, "aspect_ratio": "16:9"},
        "background": {
            "type": "linear_gradient",
            "colors": ["#0F172A", "#312E81"],
            "angle_degrees": 135,
        },
        "frame": {
            "fit": "contain",
            "padding": 96,
            "corner_radius": 24,
            "shadow": {
                "enabled": True, "color": "#000000", "opacity": 0.28,
                "blur": 48, "offset_x": 0, "offset_y": 18,
            },
        },
    },
    "clean": {
        "preset": "clean",
        "canvas": {"width": 1920, "height": 1080, "aspect_ratio": "16:9"},
        "background": {"type": "color", "value": "#F8FAFC"},
        "frame": {
            "fit": "contain",
            "padding": 64,
            "corner_radius": 18,
            "shadow": {
                "enabled": True, "color": "#0F172A", "opacity": 0.16,
                "blur": 32, "offset_x": 0, "offset_y": 10,
            },
        },
    },
    "social-square": {
        "preset": "social-square",
        "canvas": {"width": 1080, "height": 1080, "aspect_ratio": "1:1"},
        "background": {
            "type": "linear_gradient",
            "colors": ["#111827", "#7C3AED"],
            "angle_degrees": 145,
        },
        "frame": {
            "fit": "contain",
            "padding": 64,
            "corner_radius": 24,
            "shadow": {
                "enabled": True, "color": "#000000", "opacity": 0.3,
                "blur": 42, "offset_x": 0, "offset_y": 16,
            },
        },
    },
    "social-vertical": {
        "preset": "social-vertical",
        "canvas": {"width": 1080, "height": 1920, "aspect_ratio": "9:16"},
        "background": {
            "type": "linear_gradient",
            "colors": ["#0F172A", "#0F766E"],
            "angle_degrees": 160,
        },
        "frame": {
            "fit": "contain",
            "padding": 72,
            "corner_radius": 28,
            "shadow": {
                "enabled": True, "color": "#000000", "opacity": 0.32,
                "blur": 48, "offset_x": 0, "offset_y": 18,
            },
        },
    },
    "cinematic": {
        "preset": "cinematic",
        "canvas": {"width": 2560, "height": 1080, "aspect_ratio": "64:27"},
        "background": {"type": "color", "value": "#030712"},
        "frame": {
            "fit": "contain",
            "padding": 90,
            "corner_radius": 22,
            "shadow": {
                "enabled": True, "color": "#000000", "opacity": 0.38,
                "blur": 56, "offset_x": 0, "offset_y": 20,
            },
        },
    },
}


def available_framing_presets() -> tuple[str, ...]:
    return tuple(sorted(FRAMING_PRESETS))


def build_framing_composition(
    preset: str,
    *,
    background_color: str | None = None,
    padding: int | None = None,
    corner_radius: int | None = None,
    shadow_enabled: bool | None = None,
    canvas_width: int | None = None,
    canvas_height: int | None = None,
) -> dict[str, Any]:
    if preset not in FRAMING_PRESETS:
        choices = ", ".join(available_framing_presets())
        raise ValueError(f"Unknown framing preset {preset!r}; choose one of: {choices}")
    composition = copy.deepcopy(FRAMING_PRESETS[preset])
    canvas = composition["canvas"]
    frame = composition["frame"]
    if background_color is not None:
        composition["background"] = {"type": "color", "value": background_color}
    if padding is not None:
        frame["padding"] = padding
    if corner_radius is not None:
        frame["corner_radius"] = corner_radius
    if shadow_enabled is not None:
        frame["shadow"]["enabled"] = shadow_enabled
    if canvas_width is not None:
        canvas["width"] = canvas_width
    if canvas_height is not None:
        canvas["height"] = canvas_height
    if canvas_width is not None or canvas_height is not None:
        width, height = canvas["width"], canvas["height"]
        if (
            isinstance(width, int) and not isinstance(width, bool) and width > 0
            and isinstance(height, int) and not isinstance(height, bool) and height > 0
        ):
            divisor = math.gcd(width, height)
            canvas["aspect_ratio"] = f"{width // divisor}:{height // divisor}"
    validate_project_composition(composition)
    return composition


def apply_framing_preset(
    project_directory: str | Path,
    *,
    preset: str,
    background_color: str | None = None,
    padding: int | None = None,
    corner_radius: int | None = None,
    shadow_enabled: bool | None = None,
    canvas_width: int | None = None,
    canvas_height: int | None = None,
) -> dict[str, Any]:
    root = Path(project_directory).expanduser().resolve()
    project = validate_hermes_project(root)
    composition = build_framing_composition(
        preset,
        background_color=background_color,
        padding=padding,
        corner_radius=corner_radius,
        shadow_enabled=shadow_enabled,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
    )
    validate_project_timeline(project.timeline, composition=composition)
    payload = project.to_dict()
    payload["composition"] = composition
    manifest = root / "project.json"
    temporary = root / "project.json.tmp"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(manifest)
    validate_hermes_project(root)
    return composition
