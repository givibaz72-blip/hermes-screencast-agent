from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_screencast.browser.factory import (
    BrowserConfig,
    BrowserFactory,
)


class FakeChromium:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def launch_persistent_context(self, **kwargs):
        self.calls.append(kwargs)
        return object()


class FakePlaywright:
    def __init__(self) -> None:
        self.chromium = FakeChromium()


def test_browser_factory_uses_clean_app_recording_mode(
    tmp_path: Path,
) -> None:
    config = BrowserConfig(
        profile="recording",
        headless=False,
        viewport_width=1920,
        viewport_height=1080,
        kiosk=True,
    )
    factory = BrowserFactory(config)
    factory.session_manager.ensure_profile = lambda _: tmp_path

    playwright = FakePlaywright()
    factory.create(playwright)

    options = playwright.chromium.calls[0]
    args = options["args"]

    assert "--app=about:blank" in args
    assert "--start-fullscreen" not in args
    assert "--window-size=1920,1080" in args
    assert "--hide-crash-restore-bubble" in args
    assert "--start-maximized" not in args

    assert options["no_viewport"] is True
    assert "viewport" not in options


def test_browser_factory_keeps_viewport_in_normal_mode(
    tmp_path: Path,
) -> None:
    config = BrowserConfig(
        profile="normal",
        viewport_width=1920,
        viewport_height=1080,
    )
    factory = BrowserFactory(config)
    factory.session_manager.ensure_profile = lambda _: tmp_path

    playwright = FakePlaywright()
    factory.create(playwright)

    options = playwright.chromium.calls[0]
    args = options["args"]

    assert "--start-maximized" in args
    assert "--app=about:blank" not in args
    assert "no_viewport" not in options
    assert options["viewport"] == {
        "width": 1920,
        "height": 1080,
    }
