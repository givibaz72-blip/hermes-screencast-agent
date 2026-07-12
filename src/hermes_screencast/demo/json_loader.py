from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hermes_screencast.demo.script import DemoActionType, DemoScript, DemoStep


_ALLOWED_SCRIPT_FIELDS = {
    "title",
    "target",
    "preferences",
    "metadata",
    "steps",
}


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
    if not isinstance(payload, dict):
        raise ValueError("DemoScript JSON root must be an object")

    unknown_fields = set(payload) - _ALLOWED_SCRIPT_FIELDS
    if unknown_fields:
        fields = ", ".join(sorted(unknown_fields))
        raise ValueError(f"DemoScript JSON unknown field(s): {fields}")

    title = payload.get("title")
    target = _optional_object_field(payload, "target")
    preferences = _optional_object_field(payload, "preferences")
    metadata = _optional_object_field(payload, "metadata")
    steps_payload = payload.get("steps")

    if not isinstance(title, str):
        raise ValueError("DemoScript JSON requires string field: title")

    if not isinstance(steps_payload, list):
        raise ValueError("DemoScript JSON requires list field: steps")

    steps = [_demo_step_from_dict(index, step) for index, step in enumerate(steps_payload)]

    script = DemoScript(
        title=title,
        steps=steps,
        target=target,
        preferences=preferences,
        metadata=metadata,
    )
    script.validate()
    return script


def demo_script_to_dict(script: DemoScript) -> dict[str, Any]:
    script.validate()

    return {
        "title": script.title,
        "target": dict(script.target),
        "preferences": dict(script.preferences),
        "metadata": dict(script.metadata),
        "steps": [_demo_step_to_dict(step) for step in script.steps],
    }


def _optional_object_field(payload: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = payload.get(field_name, {})
    if not isinstance(value, dict):
        raise ValueError(f"DemoScript JSON field must be an object: {field_name}")
    return value


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


def _demo_step_to_dict(step: DemoStep) -> dict[str, Any]:
    payload: dict[str, Any] = {"action": step.action.value}

    for field_name in ("selector", "url", "text", "seconds", "value", "note"):
        value = getattr(step, field_name)
        if value is not None:
            payload[field_name] = value

    if step.metadata:
        payload["metadata"] = dict(step.metadata)

    return payload
