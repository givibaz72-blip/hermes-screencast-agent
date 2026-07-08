import pytest

from hermes_screencast.browser.session import BrowserSession


@pytest.mark.skip(reason="Requires Playwright runtime")
def test_browser_session_can_open_example():
    with BrowserSession(profile="legacy") as browser:
        browser.goto("https://example.com")
        assert "Example Domain" in browser.content()
