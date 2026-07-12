from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from hermes_screencast.demo.recording import (
    build_recorded_steps_script,
    record_demo_script,
)
from hermes_screencast.demo.script import (
    DemoActionType,
    DemoScript,
    DemoStep,
)


@pytest.fixture(autouse=True)
def disable_real_display_focus(monkeypatch) -> None:
    monkeypatch.setattr(
        "hermes_screencast.demo.recording.focus_display_point",
        lambda **kwargs: None,
    )


@dataclass
class FakeMouse:
    events: list[str]

    def move(
        self,
        x: float,
        y: float,
        *,
        steps: int,
    ) -> None:
        self.events.append(f"mouse.move:{x}:{y}:{steps}")

    def click(self, x: float, y: float) -> None:
        self.events.append(f"mouse.click:{x}:{y}")


@dataclass
class FakeRuntime:
    events: list[str]
    evaluate_result: Any = True
    chrome_offset: int = 86
    mouse: FakeMouse = field(init=False)

    def __post_init__(self) -> None:
        self.mouse = FakeMouse(self.events)

    def __enter__(self) -> "FakeRuntime":
        self.events.append("runtime.enter")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.events.append("runtime.exit")

    def goto(self, url: str) -> None:
        self.events.append(f"goto:{url}")

    def click(self, selector: str) -> None:
        self.events.append(f"click:{selector}")

    def hover(self, selector: str) -> None:
        self.events.append(f"hover:{selector}")

    def fill(self, selector: str, text: str) -> None:
        self.events.append(f"fill:{selector}:{text}")

    def wait(self, seconds: float) -> None:
        self.events.append(f"wait:{seconds}")

    def evaluate(self, script: str) -> Any:
        self.events.append("evaluate")

        if "window.outerHeight - window.innerHeight" in script:
            return self.chrome_offset

        return self.evaluate_result

    def add_init_script(self, script: str) -> None:
        self.events.append("add_init_script")


@dataclass
class FakeDisplay:
    events: list[str]

    def __enter__(self) -> "FakeDisplay":
        self.events.append("display.enter")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.events.append("display.exit")


@dataclass
class FakeRecorder:
    events: list[str]

    def __enter__(self) -> "FakeRecorder":
        self.events.append("recorder.enter")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.events.append("recorder.exit")


def make_script(
    *steps: DemoStep,
    preferences: dict | None = None,
) -> DemoScript:
    return DemoScript(
        title="Recorded demo",
        steps=list(steps),
        preferences=preferences or {},
    )


def test_build_recorded_steps_script_removes_initial_goto() -> None:
    script = make_script(
        DemoStep(
            action=DemoActionType.GOTO,
            url="https://example.com",
        ),
        DemoStep(
            action=DemoActionType.WAIT,
            seconds=1,
        ),
    )

    recorded = build_recorded_steps_script(script)

    assert recorded.title == script.title
    assert recorded.steps == [script.steps[1]]


def test_build_recorded_steps_script_requires_initial_goto() -> None:
    script = make_script(
        DemoStep(
            action=DemoActionType.WAIT,
            seconds=1,
        ),
    )

    with pytest.raises(
        ValueError,
        match="requires goto as the first step",
    ):
        build_recorded_steps_script(script)


def test_record_demo_script_starts_recording_after_page_preparation(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    output = tmp_path / "demo.mp4"

    script = make_script(
        DemoStep(
            action=DemoActionType.GOTO,
            url="https://example.com",
        ),
        DemoStep(
            action=DemoActionType.WAIT,
            seconds=0.5,
        ),
    )

    def display_factory(**kwargs):
        events.append(f"display.factory:{kwargs['display']}")
        return FakeDisplay(events)

    def runtime_factory(**kwargs):
        events.append(f"runtime.factory:{kwargs['config'].profile}")
        return FakeRuntime(events)

    def recorder_factory(**kwargs):
        events.append(f"recorder.factory:{kwargs['output_file']}")
        return FakeRecorder(events)

    def verifier(path: Path) -> Path:
        events.append(f"verify:{path}")
        return path

    result = record_demo_script(
        script,
        output,
        browser_warmup_seconds=1.25,
        recording_tail_seconds=0.35,
        display_factory=display_factory,
        runtime_factory=runtime_factory,
        recorder_factory=recorder_factory,
        verifier=verifier,
    )

    assert result == output.resolve()

    goto_index = events.index("goto:https://example.com")
    recorder_enter_index = events.index("recorder.enter")
    script_wait_index = events.index("wait:0.5")
    recorder_exit_index = events.index("recorder.exit")
    runtime_exit_index = events.index("runtime.exit")
    display_exit_index = events.index("display.exit")
    verify_index = events.index(f"verify:{output.resolve()}")

    assert goto_index < recorder_enter_index
    assert events.index("wait:1.25") < recorder_enter_index
    assert recorder_enter_index < script_wait_index
    assert script_wait_index < recorder_exit_index
    assert recorder_exit_index < runtime_exit_index
    assert runtime_exit_index < display_exit_index
    assert display_exit_index < verify_index


def test_record_demo_script_cleans_up_when_step_fails(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    script = make_script(
        DemoStep(
            action=DemoActionType.GOTO,
            url="https://example.com",
        ),
        DemoStep(
            action=DemoActionType.ASSERT_TEXT_VISIBLE,
            text="Missing text",
        ),
    )

    def display_factory(**kwargs):
        return FakeDisplay(events)

    def runtime_factory(**kwargs):
        return FakeRuntime(
            events,
            evaluate_result=False,
        )

    def recorder_factory(**kwargs):
        return FakeRecorder(events)

    def verifier(path: Path) -> Path:
        events.append("verify")
        return path

    with pytest.raises(
        RuntimeError,
        match="Text not visible: Missing text",
    ):
        record_demo_script(
            script,
            tmp_path / "failed.mp4",
            browser_warmup_seconds=0,
            recording_tail_seconds=0,
            display_factory=display_factory,
            runtime_factory=runtime_factory,
            recorder_factory=recorder_factory,
            verifier=verifier,
        )

    assert "recorder.exit" in events
    assert "runtime.exit" in events
    assert "display.exit" in events
    assert "verify" not in events

def test_record_demo_script_keeps_browser_ui_visible_by_default(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    display_options: list[dict] = []
    recorder_options: list[dict] = []

    script = make_script(
        DemoStep(
            action=DemoActionType.GOTO,
            url="https://example.com",
        ),
        DemoStep(
            action=DemoActionType.WAIT,
            seconds=0,
        ),
    )

    def display_factory(**kwargs):
        display_options.append(kwargs)
        return FakeDisplay(events)

    def runtime_factory(**kwargs):
        return FakeRuntime(events, chrome_offset=86)

    def recorder_factory(**kwargs):
        recorder_options.append(kwargs)
        return FakeRecorder(events)

    record_demo_script(
        script,
        tmp_path / "visible.mp4",
        browser_warmup_seconds=0,
        recording_tail_seconds=0,
        display_factory=display_factory,
        runtime_factory=runtime_factory,
        recorder_factory=recorder_factory,
        verifier=lambda path: path,
    )

    assert display_options[0]["height"] == 1080
    assert recorder_options[0]["height"] == 1080
    assert recorder_options[0]["offset_y"] == 0


def test_record_demo_script_can_crop_browser_ui(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    display_options: list[dict] = []
    recorder_options: list[dict] = []

    script = make_script(
        DemoStep(
            action=DemoActionType.GOTO,
            url="https://example.com",
        ),
        DemoStep(
            action=DemoActionType.WAIT,
            seconds=0,
        ),
        preferences={
            "browser_ui": "content_only",
        },
    )

    def display_factory(**kwargs):
        display_options.append(kwargs)
        return FakeDisplay(events)

    def runtime_factory(**kwargs):
        return FakeRuntime(events, chrome_offset=86)

    def recorder_factory(**kwargs):
        recorder_options.append(kwargs)
        return FakeRecorder(events)

    record_demo_script(
        script,
        tmp_path / "content-only.mp4",
        browser_warmup_seconds=0,
        recording_tail_seconds=0,
        display_factory=display_factory,
        runtime_factory=runtime_factory,
        recorder_factory=recorder_factory,
        verifier=lambda path: path,
    )

    assert display_options[0]["height"] == 1240
    assert recorder_options[0]["height"] == 1080
    assert recorder_options[0]["offset_y"] == 86


def test_record_demo_script_rejects_unknown_browser_ui(
    tmp_path: Path,
) -> None:
    script = make_script(
        DemoStep(
            action=DemoActionType.GOTO,
            url="https://example.com",
        ),
        DemoStep(
            action=DemoActionType.WAIT,
            seconds=0,
        ),
        preferences={
            "browser_ui": "unknown",
        },
    )

    with pytest.raises(
        ValueError,
        match="preferences.browser_ui",
    ):
        record_demo_script(
            script,
            tmp_path / "invalid.mp4",
        )
