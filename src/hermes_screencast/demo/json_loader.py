from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hermes_screencast.demo.script import DemoActionType, DemoScript, DemoStep


_ALLOWED_STEP_FIELDS = {
    "action",
    "selector",
    "url",
    "text",
    "seconds",
    "value",
    "note",
    "metadata",
}


def load_demo_script(path: Path) -> DemoScript:
    script_path = path.expanduser().resolve()

    if not script_path.exists():
        raise FileNotFoundError(script_path)

    payload = json.loads(script_path.read_text(encoding="utf-8"))
    return demo_script_from_dict(payload)


def demo_script_from_dict(payload: dict[str, Any]) -> DemoScript:
    title = payload.get("title")
    steps_payload = payload.get("steps")

    if not isinstance(title, str):
        raise ValueError("DemoScript JSON requires string field: title")

    if not isinstance(steps_payload, list):
        raise ValueError("DemoScript JSON requires list field: steps")

    steps = [_demo_step_from_dict(index, step) for index, step in enumerate(steps_payload)]

    script = DemoScript(
        title=title,
        steps=steps,
    )
    script.validate()
    return script


def _demo_step_from_dict(index: int, payload: dict[str, Any]) -> DemoStep:
    if not isinstance(payload, dict):
        raise ValueError(f"Step {index}: step must be an object")

    unknown_fields = set(payload) - _ALLOWED_STEP_FIELDS
    if unknown_fields:
        fields = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Step {index}: unknown field(s): {fields}")

    action_value = payload.get("action")
    if not isinstance(action_value, str):
        raise ValueError(f"Step {index}: action must be a string")

    try:
        action = DemoActionType(action_value)
    except ValueError as exc:
        raise ValueError(f"Step {index}: unsupported action: {action_value}") from exc

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError(f"Step {index}: metadata must be an object")

    return DemoStep(
        action=action,
        selector=payload.get("selector"),
        url=payload.get("url"),
        text=payload.get("text"),
        seconds=payload.get("seconds"),
        value=payload.get("value"),
        note=payload.get("note"),
        metadata=metadata,
    )
