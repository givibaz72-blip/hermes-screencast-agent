from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from hermes_screencast.cursor import (
    VISUAL_CURSOR_INIT_SCRIPT,
    VisualCursor,
)


@dataclass
class FakeMouse:
    calls: list[tuple[float, float, int]] = field(default_factory=list)

    def move(self, x: float, y: float, *, steps: int) -> None:
        self.calls.append((x, y, steps))


@dataclass
class FakeRuntime:
    center: dict[str, float] | None = field(
        default_factory=lambda: {"x": 320.0, "y": 180.0}
    )
    mouse: FakeMouse = field(default_factory=FakeMouse)
    init_scripts: list[str] = field(default_factory=list)
    evaluated_scripts: list[str] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)

    def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    def evaluate(self, script: str) -> Any:
        self.evaluated_scripts.append(script)

        if "getBoundingClientRect" in script and "return {" in script:
            return self.center

        return None

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)


def test_visual_cursor_installs_for_current_and_future_pages() -> None:
    runtime = FakeRuntime()
    cursor = VisualCursor(runtime=runtime)

    cursor.install()
    cursor.install()

    assert runtime.init_scripts == [VISUAL_CURSOR_INIT_SCRIPT]
    assert len(runtime.evaluated_scripts) == 1
    assert "__hermesInstallVisualCursor" in runtime.evaluated_scripts[0]


def test_visual_cursor_moves_smoothly_to_element_center() -> None:
    runtime = FakeRuntime(center={"x": 420.5, "y": 240.25})
    cursor = VisualCursor(runtime=runtime, movement_steps=30)

    position = cursor.move_to_selector("#submit")

    assert position == (420.5, 240.25)
    assert cursor.position == (420.5, 240.25)
    assert runtime.waits == [0.25]
    assert runtime.mouse.calls == [(420.5, 240.25, 30)]
    assert any(
        "document.querySelector('#submit')" in script
        for script in runtime.evaluated_scripts
    )


def test_visual_cursor_fails_when_element_is_missing() -> None:
    runtime = FakeRuntime(center=None)
    cursor = VisualCursor(runtime=runtime)

    with pytest.raises(RuntimeError, match="Element not found: #missing"):
        cursor.move_to_selector("#missing")


def test_visual_cursor_renders_click_ripple_at_current_position() -> None:
    runtime = FakeRuntime(center={"x": 100.0, "y": 200.0})
    cursor = VisualCursor(runtime=runtime)

    cursor.move_to_selector("#button")
    cursor.show_click_ripple()

    assert "__hermesClickRipple(100.0, 200.0)" in runtime.evaluated_scripts[-1]
