from __future__ import annotations

from dataclasses import dataclass, field

from hermes_screencast.demo.runner import DemoRunner
from hermes_screencast.demo.script import DemoActionType, DemoScript, DemoStep


@dataclass
class RecordingDemoExecutor:
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    def goto(self, url: str) -> None:
        self.calls.append(("goto", (url,)))

    def click(self, selector: str) -> None:
        self.calls.append(("click", (selector,)))

    def hover(self, selector: str) -> None:
        self.calls.append(("hover", (selector,)))

    def fill(self, selector: str, text: str) -> None:
        self.calls.append(("fill", (selector, text)))

    def scroll(self, amount: int) -> None:
        self.calls.append(("scroll", (amount,)))

    def wait(self, seconds: float) -> None:
        self.calls.append(("wait", (seconds,)))

    def wait_for_element(self, selector: str, timeout_seconds: float | None = None) -> None:
        self.calls.append(("wait_for_element", (selector, timeout_seconds)))

    def wait_for_url_contains(self, url_part: str, timeout_seconds: float | None = None) -> None:
        self.calls.append(("wait_for_url_contains", (url_part, timeout_seconds)))

    def wait_for_text_visible(self, text: str, timeout_seconds: float | None = None) -> None:
        self.calls.append(("wait_for_text_visible", (text, timeout_seconds)))

    def wait_for_navigation_idle(self, timeout_seconds: float | None = None) -> None:
        self.calls.append(("wait_for_navigation_idle", (timeout_seconds,)))

    def zoom(self, selector: str) -> None:
        self.calls.append(("zoom", (selector,)))

    def highlight(self, selector: str) -> None:
        self.calls.append(("highlight", (selector,)))

    def draw_box(self, selector: str) -> None:
        self.calls.append(("draw_box", (selector,)))

    def draw_arrow(self, selector: str) -> None:
        self.calls.append(("draw_arrow", (selector,)))

    def narration(self, text: str) -> None:
        self.calls.append(("narration", (text,)))

    def auth_check(self) -> None:
        self.calls.append(("auth_check", ()))

    def assert_text_visible(self, text: str) -> None:
        self.calls.append(("assert_text_visible", (text,)))

    def assert_not_text_visible(self, text: str) -> None:
        self.calls.append(("assert_not_text_visible", (text,)))

    def assert_element_visible(self, selector: str) -> None:
        self.calls.append(("assert_element_visible", (selector,)))

    def assert_url_contains(self, url_part: str) -> None:
        self.calls.append(("assert_url_contains", (url_part,)))


def test_demo_runner_executes_steps_in_order() -> None:
    executor = RecordingDemoExecutor()
    runner = DemoRunner(executor=executor)

    script = DemoScript(
        title="Demo runner test",
        steps=[
            DemoStep(action=DemoActionType.GOTO, url="https://example.com"),
            DemoStep(action=DemoActionType.AUTH_CHECK),
            DemoStep(action=DemoActionType.CLICK, selector="#login"),
            DemoStep(action=DemoActionType.FILL, selector="#email", text="demo@example.com"),
            DemoStep(action=DemoActionType.SCROLL, value="300"),
            DemoStep(action=DemoActionType.WAIT, seconds=1.5),
            DemoStep(action=DemoActionType.NARRATION, text="Done"),
        ],
    )

    result = runner.run(script)

    assert result.success is True
    assert result.completed_steps == 7
    assert result.error is None
    assert executor.calls == [
        ("goto", ("https://example.com",)),
        ("auth_check", ()),
        ("click", ("#login",)),
        ("fill", ("#email", "demo@example.com")),
        ("scroll", (300,)),
        ("wait", (1.5,)),
        ("narration", ("Done",)),
    ]


def test_demo_runner_stops_after_failed_step() -> None:
    executor = RecordingDemoExecutor()
    runner = DemoRunner(executor=executor)

    script = DemoScript(
        title="Invalid demo runner test",
        steps=[
            DemoStep(action=DemoActionType.GOTO, url="https://example.com"),
            DemoStep(action=DemoActionType.CLICK),
            DemoStep(action=DemoActionType.NARRATION, text="Should not run"),
        ],
    )

    result = runner.run(script)

    assert result.success is False
    assert result.completed_steps == 0
    assert "click requires selector" in str(result.error)
    assert executor.calls == []


def test_demo_runner_executes_assert_text_visible() -> None:
    executor = RecordingDemoExecutor()
    runner = DemoRunner(executor=executor)

    script = DemoScript(
        title="Assertion runner test",
        steps=[
            DemoStep(action=DemoActionType.ASSERT_TEXT_VISIBLE, text="Welcome"),
        ],
    )

    result = runner.run(script)

    assert result.success is True
    assert result.completed_steps == 1
    assert executor.calls == [
        ("assert_text_visible", ("Welcome",)),
    ]


def test_demo_runner_executes_assert_element_visible() -> None:
    executor = RecordingDemoExecutor()
    runner = DemoRunner(executor=executor)

    script = DemoScript(
        title="Element assertion runner test",
        steps=[
            DemoStep(action=DemoActionType.ASSERT_ELEMENT_VISIBLE, selector="#hero"),
        ],
    )

    result = runner.run(script)

    assert result.success is True
    assert result.completed_steps == 1
    assert executor.calls == [
        ("assert_element_visible", ("#hero",)),
    ]


def test_demo_runner_executes_assert_url_contains() -> None:
    executor = RecordingDemoExecutor()
    runner = DemoRunner(executor=executor)

    script = DemoScript(
        title="URL assertion runner test",
        steps=[
            DemoStep(action=DemoActionType.ASSERT_URL_CONTAINS, url="/dashboard"),
        ],
    )

    result = runner.run(script)

    assert result.success is True
    assert result.completed_steps == 1
    assert executor.calls == [
        ("assert_url_contains", ("/dashboard",)),
    ]


def test_demo_runner_executes_wait_for_element() -> None:
    executor = RecordingDemoExecutor()
    runner = DemoRunner(executor=executor)

    script = DemoScript(
        title="Wait runner test",
        steps=[
            DemoStep(
                action=DemoActionType.WAIT_FOR_ELEMENT,
                selector="#hero",
                seconds=2,
            ),
        ],
    )

    result = runner.run(script)

    assert result.success is True
    assert result.completed_steps == 1
    assert executor.calls == [
        ("wait_for_element", ("#hero", 2)),
    ]


def test_demo_runner_executes_wait_for_url_contains() -> None:
    executor = RecordingDemoExecutor()
    runner = DemoRunner(executor=executor)

    script = DemoScript(
        title="Wait URL runner test",
        steps=[
            DemoStep(
                action=DemoActionType.WAIT_FOR_URL_CONTAINS,
                url="/dashboard",
                seconds=2,
            ),
        ],
    )

    result = runner.run(script)

    assert result.success is True
    assert result.completed_steps == 1
    assert executor.calls == [
        ("wait_for_url_contains", ("/dashboard", 2)),
    ]


def test_demo_runner_executes_wait_for_text_visible() -> None:
    executor = RecordingDemoExecutor()
    runner = DemoRunner(executor=executor)

    script = DemoScript(
        title="Wait text runner test",
        steps=[
            DemoStep(
                action=DemoActionType.WAIT_FOR_TEXT_VISIBLE,
                text="Welcome",
                seconds=2,
            ),
        ],
    )

    result = runner.run(script)

    assert result.success is True
    assert result.completed_steps == 1
    assert executor.calls == [
        ("wait_for_text_visible", ("Welcome", 2)),
    ]


def test_demo_runner_executes_wait_for_navigation_idle() -> None:
    executor = RecordingDemoExecutor()
    runner = DemoRunner(executor=executor)

    script = DemoScript(
        title="Wait navigation runner test",
        steps=[
            DemoStep(
                action=DemoActionType.WAIT_FOR_NAVIGATION_IDLE,
                seconds=2,
            ),
        ],
    )

    result = runner.run(script)

    assert result.success is True
    assert result.completed_steps == 1
    assert executor.calls == [
        ("wait_for_navigation_idle", (2,)),
    ]


def test_demo_runner_executes_assert_not_text_visible() -> None:
    executor = RecordingDemoExecutor()
    runner = DemoRunner(executor=executor)

    script = DemoScript(
        title="Negative assertion runner test",
        steps=[
            DemoStep(
                action=DemoActionType.ASSERT_NOT_TEXT_VISIBLE,
                text="Error",
            ),
        ],
    )

    result = runner.run(script)

    assert result.success is True
    assert result.completed_steps == 1
    assert executor.calls == [
        ("assert_not_text_visible", ("Error",)),
    ]
