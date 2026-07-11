from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from hermes_screencast.demo.browser_executor import BrowserDemoExecutor


@dataclass
class FakePage:
    authenticated: bool = True

    def is_authenticated(self) -> bool:
        return self.authenticated


@dataclass
class FakeBrowserRuntime:
    page: FakePage | None = None
    evaluate_result: Any = True
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    def goto(self, url: str) -> None:
        self.calls.append(("goto", (url,)))

    def click(self, selector: str) -> None:
        self.calls.append(("click", (selector,)))

    def hover(self, selector: str) -> None:
        self.calls.append(("hover", (selector,)))

    def fill(self, selector: str, text: str) -> None:
        self.calls.append(("fill", (selector, text)))

    def wait(self, seconds: float) -> None:
        self.calls.append(("wait", (seconds,)))

    def evaluate(self, script: str) -> Any:
        self.calls.append(("evaluate", (script,)))
        return self.evaluate_result


def test_browser_demo_executor_delegates_basic_browser_actions() -> None:
    runtime = FakeBrowserRuntime()
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.goto("https://example.com")
    executor.click("#button")
    executor.hover("#menu")
    executor.fill("#email", "demo@example.com")
    executor.wait(1.5)

    assert runtime.calls == [
        ("goto", ("https://example.com",)),
        ("click", ("#button",)),
        ("hover", ("#menu",)),
        ("fill", ("#email", "demo@example.com")),
        ("wait", (1.5,)),
    ]


def test_browser_demo_executor_scroll_uses_window_scroll_by() -> None:
    runtime = FakeBrowserRuntime()
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.scroll(300)

    assert len(runtime.calls) == 1
    name, args = runtime.calls[0]

    assert name == "evaluate"
    assert "window.scrollBy(0, 300);" in args[0]


def test_browser_demo_executor_visual_actions_use_selector() -> None:
    runtime = FakeBrowserRuntime()
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.zoom("#hero")
    executor.highlight("#hero")
    executor.draw_box("#hero")
    executor.draw_arrow("#hero")

    scripts = [args[0] for name, args in runtime.calls if name == "evaluate"]

    assert len(scripts) == 4
    assert all("document.querySelector('#hero')" in script for script in scripts)
    assert "scale(1.03)" in scripts[0]
    assert "outline" in scripts[1]
    assert "data-hermes-demo-overlay" in scripts[2]
    assert "➜" in scripts[3]


def test_browser_demo_executor_narration_renders_overlay_text() -> None:
    runtime = FakeBrowserRuntime()
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.narration("Hello from Hermes")

    assert len(runtime.calls) == 1
    name, args = runtime.calls[0]

    assert name == "evaluate"
    assert "data-hermes-demo-narration" in args[0]
    assert "Hello from Hermes" in args[0]


def test_browser_demo_executor_auth_check_passes_when_no_page_exists() -> None:
    runtime = FakeBrowserRuntime(page=None)
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.auth_check()


def test_browser_demo_executor_auth_check_passes_when_authenticated() -> None:
    runtime = FakeBrowserRuntime(page=FakePage(authenticated=True))
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.auth_check()


def test_browser_demo_executor_auth_check_fails_when_not_authenticated() -> None:
    runtime = FakeBrowserRuntime(page=FakePage(authenticated=False))
    executor = BrowserDemoExecutor(runtime=runtime)

    with pytest.raises(RuntimeError, match="Browser page is not authenticated"):
        executor.auth_check()


def test_browser_demo_executor_assert_text_visible_passes_when_text_exists() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=True)
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.assert_text_visible("Welcome")

    assert len(runtime.calls) == 1
    name, args = runtime.calls[0]

    assert name == "evaluate"
    assert "bodyText.includes(expectedText)" in args[0]
    assert "Welcome" in args[0]


def test_browser_demo_executor_assert_text_visible_fails_when_text_is_missing() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=False)
    executor = BrowserDemoExecutor(runtime=runtime)

    with pytest.raises(AssertionError, match="Text not visible: Missing text"):
        executor.assert_text_visible("Missing text")


def test_browser_demo_executor_assert_element_visible_passes_when_element_is_visible() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=True)
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.assert_element_visible("#hero")

    assert len(runtime.calls) == 1
    name, args = runtime.calls[0]

    assert name == "evaluate"
    assert "document.querySelector('#hero')" in args[0]
    assert "getBoundingClientRect" in args[0]


def test_browser_demo_executor_assert_element_visible_fails_when_element_is_missing() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=False)
    executor = BrowserDemoExecutor(runtime=runtime)

    with pytest.raises(AssertionError, match="Element not visible: #missing"):
        executor.assert_element_visible("#missing")


def test_browser_demo_executor_assert_url_contains_passes_when_url_matches() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=True)
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.assert_url_contains("/dashboard")

    assert len(runtime.calls) == 1
    name, args = runtime.calls[0]

    assert name == "evaluate"
    assert "window.location.href.includes(expectedUrlPart)" in args[0]
    assert "/dashboard" in args[0]


def test_browser_demo_executor_assert_url_contains_fails_when_url_does_not_match() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=False)
    executor = BrowserDemoExecutor(runtime=runtime)

    with pytest.raises(AssertionError, match="URL does not contain: /settings"):
        executor.assert_url_contains("/settings")


def test_browser_demo_executor_wait_for_element_returns_when_visible() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=True)
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.wait_for_element("#hero", timeout_seconds=2)

    assert len(runtime.calls) == 1
    name, args = runtime.calls[0]

    assert name == "evaluate"
    assert "document.querySelector('#hero')" in args[0]
    assert "getBoundingClientRect" in args[0]


def test_browser_demo_executor_wait_for_element_fails_when_timeout_expires() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=False)
    executor = BrowserDemoExecutor(runtime=runtime)

    with pytest.raises(TimeoutError, match="Timed out waiting for element: #missing"):
        executor.wait_for_element("#missing", timeout_seconds=0)

    assert len(runtime.calls) == 1
    name, args = runtime.calls[0]

    assert name == "evaluate"
    assert "document.querySelector('#missing')" in args[0]


def test_browser_demo_executor_wait_for_url_contains_returns_when_url_matches() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=True)
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.wait_for_url_contains("/dashboard", timeout_seconds=2)

    assert len(runtime.calls) == 1
    name, args = runtime.calls[0]

    assert name == "evaluate"
    assert "window.location.href.includes(expectedUrlPart)" in args[0]
    assert "/dashboard" in args[0]


def test_browser_demo_executor_wait_for_url_contains_fails_when_timeout_expires() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=False)
    executor = BrowserDemoExecutor(runtime=runtime)

    with pytest.raises(TimeoutError, match="Timed out waiting for URL to contain: /settings"):
        executor.wait_for_url_contains("/settings", timeout_seconds=0)

    assert len(runtime.calls) == 1
    name, args = runtime.calls[0]

    assert name == "evaluate"
    assert "/settings" in args[0]


def test_browser_demo_executor_wait_for_text_visible_returns_when_text_exists() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=True)
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.wait_for_text_visible("Welcome", timeout_seconds=2)

    assert len(runtime.calls) == 1
    name, args = runtime.calls[0]

    assert name == "evaluate"
    assert "bodyText.includes(expectedText)" in args[0]
    assert "Welcome" in args[0]


def test_browser_demo_executor_wait_for_text_visible_fails_when_timeout_expires() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=False)
    executor = BrowserDemoExecutor(runtime=runtime)

    with pytest.raises(TimeoutError, match="Timed out waiting for text: Missing"):
        executor.wait_for_text_visible("Missing", timeout_seconds=0)

    assert len(runtime.calls) == 1
    name, args = runtime.calls[0]

    assert name == "evaluate"
    assert "Missing" in args[0]


def test_browser_demo_executor_wait_for_navigation_idle_uses_timeout() -> None:
    runtime = FakeBrowserRuntime()
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.wait_for_navigation_idle(timeout_seconds=2)

    assert runtime.calls == [
        ("wait", (2,)),
    ]


def test_browser_demo_executor_wait_for_navigation_idle_uses_default_timeout() -> None:
    runtime = FakeBrowserRuntime()
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.wait_for_navigation_idle()

    assert runtime.calls == [
        ("wait", (1.0,)),
    ]


def test_browser_demo_executor_assert_not_text_visible_passes_when_text_is_absent() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=False)
    executor = BrowserDemoExecutor(runtime=runtime)

    executor.assert_not_text_visible("Error")

    assert runtime.calls == [
        ("evaluate", (
            """
                (() => {
                    const expectedText = 'Error';
                    const bodyText = document.body ? document.body.innerText : "";
                    return bodyText.includes(expectedText);
                })();
                """,
        )),
    ]


def test_browser_demo_executor_assert_not_text_visible_fails_when_text_is_visible() -> None:
    runtime = FakeBrowserRuntime(evaluate_result=True)
    executor = BrowserDemoExecutor(runtime=runtime)

    with pytest.raises(AssertionError, match="Text unexpectedly visible: Error"):
        executor.assert_not_text_visible("Error")
