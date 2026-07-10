from __future__ import annotations

from hermes_screencast.browser.runtime import BrowserRuntime, BrowserRuntimeConfig


def test_browser_runtime_passes_config_to_session() -> None:
    config = BrowserRuntimeConfig(
        profile="test-profile",
        headless=True,
        viewport_width=1280,
        viewport_height=720,
        locale="en-US",
    )

    runtime = BrowserRuntime(config=config)

    assert runtime.session.config.profile == "test-profile"
    assert runtime.session.config.headless is True
    assert runtime.session.config.viewport_width == 1280
    assert runtime.session.config.viewport_height == 720
    assert runtime.session.config.locale == "en-US"
