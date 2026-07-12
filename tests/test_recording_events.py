from __future__ import annotations

import json
from dataclasses import dataclass, field

from hermes_screencast.demo.events import (
    EventLoggingDemoRunner,
    RecordingEventJournal,
    default_events_path,
    redact_url,
    resolve_page_state,
    resolve_target_snapshot,
)
from hermes_screencast.demo.script import DemoActionType, DemoScript, DemoStep


@dataclass
class FakeClock:
    values: list[float]

    def __call__(self) -> float:
        return self.values.pop(0)


@dataclass
class FakeExecutor:
    calls: list[tuple] = field(default_factory=list)
    fail_click: bool = False
    fail_fill_with_text: bool = False

    def click(self, selector: str) -> None:
        self.calls.append(("click", selector))
        if self.fail_click:
            raise RuntimeError("click failed")

    def fill(self, selector: str, text: str) -> None:
        self.calls.append(("fill", selector, text))
        if self.fail_fill_with_text:
            raise RuntimeError(f"could not fill {text}")


def test_event_journal_uses_monotonic_relative_timestamps(tmp_path) -> None:
    journal = RecordingEventJournal(clock=FakeClock([100.0, 100.0, 100.25, 100.5]))
    journal.start({"title": "Demo"})
    journal.emit("custom")
    journal.finish(success=True)
    output = journal.write(tmp_path / "events.json")

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "hermes.recording.events.v1"
    assert [event["time_seconds"] for event in payload["events"]] == [0.0, 0.25, 0.5]
    assert [event["sequence"] for event in payload["events"]] == [0, 1, 2]


def test_event_runner_records_target_state_and_cursor() -> None:
    journal = RecordingEventJournal(clock=FakeClock([0, 0, 0.1, 0.2]))
    journal.start()
    script = DemoScript(
        title="Click demo",
        steps=[DemoStep(action=DemoActionType.CLICK, selector="#save")],
    )
    result = EventLoggingDemoRunner(
        executor=FakeExecutor(),
        journal=journal,
        target_resolver=lambda selector: {"selector": selector, "x": 10},
        state_resolver=lambda: {"scroll_y": 25},
        cursor_resolver=lambda: {"x": 20.0, "y": 30.0},
    ).run(script)

    assert result.success is True
    assert [event.event_type for event in journal.events] == [
        "recording_started", "step_started", "step_completed"
    ]
    completed = journal.events[-1].data
    assert completed["target"] == {"selector": "#save", "x": 10}
    assert completed["state"] == {"scroll_y": 25}
    assert completed["cursor"] == {"x": 20.0, "y": 30.0}


def test_event_runner_never_logs_filled_text() -> None:
    secret = "secret-password"
    journal = RecordingEventJournal(clock=FakeClock([0, 0, 0.1, 0.2]))
    journal.start()
    script = DemoScript(
        title="Fill demo",
        steps=[DemoStep(action=DemoActionType.FILL, selector="#password", text=secret)],
    )
    result = EventLoggingDemoRunner(executor=FakeExecutor(), journal=journal).run(script)

    assert result.success is True
    assert secret not in json.dumps(journal.to_dict())
    assert journal.events[1].data["text_redacted"] is True


def test_failed_fill_error_never_logs_filled_text() -> None:
    secret = "secret-password"
    journal = RecordingEventJournal(clock=FakeClock([0, 0, 0.1, 0.2]))
    journal.start()
    script = DemoScript(
        title="Fill failure",
        steps=[DemoStep(action=DemoActionType.FILL, selector="#password", text=secret)],
    )
    EventLoggingDemoRunner(
        executor=FakeExecutor(fail_fill_with_text=True), journal=journal
    ).run(script)

    assert secret not in json.dumps(journal.to_dict())
    assert journal.events[-1].data["error"] == "Fill action failed"


def test_event_runner_records_failed_step() -> None:
    journal = RecordingEventJournal(clock=FakeClock([0, 0, 0.1, 0.2]))
    journal.start()
    script = DemoScript(
        title="Failure demo",
        steps=[DemoStep(action=DemoActionType.CLICK, selector="#missing")],
    )
    result = EventLoggingDemoRunner(
        executor=FakeExecutor(fail_click=True), journal=journal
    ).run(script)

    assert result.success is False
    assert journal.events[-1].event_type == "step_failed"
    assert journal.events[-1].data["error_type"] == "RuntimeError"


def test_url_redaction_removes_credentials_values_and_fragment() -> None:
    result = redact_url("https://user:pass@example.com/path?token=secret&mode=x#part")
    assert result == "https://example.com/path?token=REDACTED&mode=REDACTED"


@dataclass
class FakeRuntime:
    results: list[object]

    def evaluate(self, script: str):
        return self.results.pop(0)


def test_browser_snapshot_helpers_normalize_values() -> None:
    runtime = FakeRuntime([
        {"x": 10.123, "y": 20.456, "width": 100.789, "height": 40.111},
        {
            "url": "https://example.com/page?token=secret",
            "scroll_x": 1.25, "scroll_y": 50.75,
            "viewport_width": 1920, "viewport_height": 1080,
        },
    ])
    target = resolve_target_snapshot(runtime, "#save")
    state = resolve_page_state(runtime)

    assert target == {
        "selector": "#save", "x": 10.12, "y": 20.46,
        "width": 100.79, "height": 40.11,
    }
    assert state["url"] == "https://example.com/page?token=REDACTED"
    assert state["scroll_y"] == 50.75


def test_default_events_path_replaces_video_extension(tmp_path) -> None:
    assert default_events_path(tmp_path / "demo.mp4") == (
        tmp_path / "demo.events.json"
    ).resolve()
