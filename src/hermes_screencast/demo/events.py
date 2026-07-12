from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from hermes_screencast.demo.runner import DemoRunner
from hermes_screencast.demo.script import DemoActionType, DemoStep


EVENT_SCHEMA = "hermes.recording.events.v1"
INTERACTIVE_CURSOR_ACTIONS = {
    DemoActionType.CLICK,
    DemoActionType.HOVER,
    DemoActionType.FILL,
}


@dataclass(frozen=True)
class RecordingEvent:
    sequence: int
    time_seconds: float
    event_type: str
    step_index: int | None = None
    action: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sequence": self.sequence,
            "time_seconds": self.time_seconds,
            "type": self.event_type,
        }
        if self.step_index is not None:
            payload["step_index"] = self.step_index
        if self.action is not None:
            payload["action"] = self.action
        if self.data:
            payload["data"] = dict(self.data)
        return payload


@dataclass
class RecordingEventJournal:
    clock: Callable[[], float] = time.monotonic

    _origin: float | None = field(default=None, init=False)
    _metadata: dict[str, Any] = field(default_factory=dict, init=False)
    _events: list[RecordingEvent] = field(default_factory=list, init=False)
    _finished: bool = field(default=False, init=False)

    @property
    def events(self) -> tuple[RecordingEvent, ...]:
        return tuple(self._events)

    def start(self, metadata: dict[str, Any] | None = None) -> None:
        if self._origin is not None:
            raise RuntimeError("Recording event journal is already started")
        self._origin = self.clock()
        self._metadata = dict(metadata or {})
        self.emit("recording_started")

    def emit(
        self,
        event_type: str,
        *,
        step_index: int | None = None,
        action: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> RecordingEvent:
        if self._origin is None:
            raise RuntimeError("Recording event journal is not started")
        if self._finished:
            raise RuntimeError("Recording event journal is already finished")
        event = RecordingEvent(
            sequence=len(self._events),
            time_seconds=round(max(0.0, self.clock() - self._origin), 6),
            event_type=event_type,
            step_index=step_index,
            action=action,
            data=dict(data or {}),
        )
        self._events.append(event)
        return event

    def finish(self, *, success: bool, error: BaseException | None = None) -> None:
        data: dict[str, Any] = {"success": success}
        if error is not None:
            data["error_type"] = type(error).__name__
        self.emit("recording_finished", data=data)
        self._finished = True

    def to_dict(self) -> dict[str, Any]:
        if self._origin is None:
            raise RuntimeError("Recording event journal is not started")
        return {
            "schema": EVENT_SCHEMA,
            "metadata": dict(self._metadata),
            "events": [event.to_dict() for event in self._events],
        }

    def write(self, path: str | Path) -> Path:
        output_path = Path(path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return output_path


@dataclass
class EventLoggingDemoRunner(DemoRunner):
    journal: RecordingEventJournal
    target_resolver: Callable[[str], dict[str, Any] | None] | None = None
    state_resolver: Callable[[], dict[str, Any] | None] | None = None
    cursor_resolver: Callable[[], dict[str, float] | None] | None = None
    _next_step_index: int = field(default=0, init=False)

    def _run_step(self, step: DemoStep) -> None:
        index = self._next_step_index
        action = step.action.value
        self.journal.emit(
            "step_started",
            step_index=index,
            action=action,
            data=_safe_step_data(step),
        )
        try:
            super()._run_step(step)
        except BaseException as exc:
            error_message = (
                "Fill action failed"
                if step.action == DemoActionType.FILL
                else str(exc)[:500]
            )
            data = {"error_type": type(exc).__name__, "error": error_message}
            target = self._resolve_target(step.selector)
            if target is not None:
                data["target"] = target
            self.journal.emit(
                "step_failed", step_index=index, action=action, data=data
            )
            raise
        else:
            data: dict[str, Any] = {}
            target = self._resolve_target(step.selector)
            if target is not None:
                data["target"] = target
            state = self._resolve_state()
            if state is not None:
                data["state"] = state
            if step.action in INTERACTIVE_CURSOR_ACTIONS:
                cursor = self._resolve_cursor()
                if cursor is not None:
                    data["cursor"] = cursor
            self.journal.emit(
                "step_completed", step_index=index, action=action, data=data
            )
        finally:
            self._next_step_index += 1

    def _resolve_target(self, selector: str | None) -> dict[str, Any] | None:
        if selector is None or self.target_resolver is None:
            return None
        try:
            return self.target_resolver(selector)
        except Exception:
            return None

    def _resolve_state(self) -> dict[str, Any] | None:
        if self.state_resolver is None:
            return None
        try:
            return self.state_resolver()
        except Exception:
            return None

    def _resolve_cursor(self) -> dict[str, float] | None:
        if self.cursor_resolver is None:
            return None
        try:
            return self.cursor_resolver()
        except Exception:
            return None


def resolve_target_snapshot(runtime, selector: str) -> dict[str, Any] | None:
    payload = runtime.evaluate(
        f"""
        (() => {{
            const element = document.querySelector({selector!r});
            if (!element) return null;
            const rect = element.getBoundingClientRect();
            return {{x: rect.x, y: rect.y, width: rect.width, height: rect.height}};
        }})();
        """
    )
    if not isinstance(payload, dict):
        return None
    return {
        "selector": selector,
        "x": round(float(payload.get("x", 0.0)), 2),
        "y": round(float(payload.get("y", 0.0)), 2),
        "width": round(float(payload.get("width", 0.0)), 2),
        "height": round(float(payload.get("height", 0.0)), 2),
    }


def resolve_page_state(runtime) -> dict[str, Any] | None:
    payload = runtime.evaluate(
        """
        (() => ({
            url: window.location.href,
            scroll_x: window.scrollX,
            scroll_y: window.scrollY,
            viewport_width: window.innerWidth,
            viewport_height: window.innerHeight
        }))();
        """
    )
    if not isinstance(payload, dict):
        return None
    url = payload.get("url")
    return {
        "url": redact_url(url) if isinstance(url, str) else None,
        "scroll_x": round(float(payload.get("scroll_x", 0.0)), 2),
        "scroll_y": round(float(payload.get("scroll_y", 0.0)), 2),
        "viewport_width": int(payload.get("viewport_width", 0)),
        "viewport_height": int(payload.get("viewport_height", 0)),
    }


def redact_url(value: str) -> str:
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    netloc = hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    query = urlencode(
        [(key, "REDACTED") for key, _ in parse_qsl(parsed.query, keep_blank_values=True)]
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))


def default_events_path(video_path: str | Path) -> Path:
    return Path(video_path).expanduser().resolve().with_suffix(".events.json")


def _safe_step_data(step: DemoStep) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if step.selector is not None:
        data["selector"] = step.selector
    if step.url is not None:
        data["url"] = redact_url(step.url)
    if step.seconds is not None:
        data["seconds"] = step.seconds
    if step.value is not None:
        data["value"] = step.value
    if step.action == DemoActionType.NARRATION and step.text is not None:
        data["text"] = step.text
    if step.action == DemoActionType.FILL:
        data["text_redacted"] = True
    return data
