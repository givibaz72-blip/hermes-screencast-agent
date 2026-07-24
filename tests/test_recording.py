from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import hermes_screencast.recording as recording
import pytest


class FakeProcess:
    def __init__(self, *, timeout_on_first_wait: bool = False):
        self.return_code: int | None = None
        self.timeout_on_first_wait = timeout_on_first_wait
        self.wait_calls = 0
        self.terminate_called = False
        self.kill_called = False

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.terminate_called = True

    def kill(self) -> None:
        self.kill_called = True

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1

        if (
            self.timeout_on_first_wait
            and self.wait_calls == 1
            and not self.kill_called
        ):
            raise subprocess.TimeoutExpired("fake-process", timeout)

        self.return_code = 0
        return 0


def test_terminate_process_stops_running_process() -> None:
    process = FakeProcess()

    recording.terminate_process(process, timeout=1)

    assert process.terminate_called is True
    assert process.kill_called is False
    assert process.wait_calls == 1


def test_terminate_process_kills_process_after_timeout() -> None:
    process = FakeProcess(timeout_on_first_wait=True)

    recording.terminate_process(process, timeout=1)

    assert process.terminate_called is True
    assert process.kill_called is True
    assert process.wait_calls == 2


def test_virtual_display_starts_and_stops_processes(monkeypatch) -> None:
    created_processes: list[tuple[list[str], FakeProcess]] = []
    run_calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(command, **kwargs):
        process = FakeProcess()
        created_processes.append((command, process))
        return process

    def fake_run(command, **kwargs):
        run_calls.append((command, kwargs))
        # xdpyinfo check should raise CalledProcessError (display not in use)
        # xdotool should return success
        if command[0] == "xdpyinfo":
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(recording.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(recording.subprocess, "run", fake_run)
    monkeypatch.setattr(recording.time, "sleep", lambda _: None)
    monkeypatch.setenv("DISPLAY", ":old")

    display = recording.VirtualDisplay(
        display=":99",
        width=1920,
        height=1080,
    )

    with display:
        assert recording.os.environ["DISPLAY"] == ":99"

    # Xvfb should be started first (display not in use)
    assert created_processes[0][0] == [
        "Xvfb",
        ":99",
        "-screen",
        "0",
        "1920x1080x24",
        "-ac",
        "-nocursor",
    ]
    # unclutter should be started second
    assert created_processes[1][0][0] == "unclutter"
    # xdotool mousemove should be called
    assert run_calls[1][0] == ["xdotool", "mousemove", "9999", "9999"]

    assert created_processes[0][1].terminate_called is True
    assert created_processes[1][1].terminate_called is True


def test_screen_recorder_builds_professional_mp4_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []
    process = FakeProcess()

    def fake_popen(command, **kwargs):
        commands.append(command)
        return process

    monkeypatch.setattr(recording.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(recording.time, "sleep", lambda _: None)

    output = tmp_path / "videos" / "demo.mp4"

    with recording.ScreenRecorder(
        output_file=output,
        offset_x=12,
        offset_y=84,
    ):
        assert output.parent.exists()

    command = commands[0]

    assert command[0] == "ffmpeg"
    assert "-framerate" in command
    assert "30" in command
    assert "-video_size" in command
    assert "1920x1080" in command
    assert "-crf" in command
    assert "18" in command
    assert "-pix_fmt" in command
    assert "yuv420p" in command

    input_index = command.index("-i")
    assert command[input_index + 1] == ":99.0+12,84"

    assert command[-1] == str(output.resolve())
    assert process.terminate_called is True


def test_focus_display_point_uses_real_x11_click(
    monkeypatch,
) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(
        recording.subprocess,
        "run",
        fake_run,
    )

    recording.focus_display_point(
        x=960,
        y=500,
        display=":99",
    )

    command, options = calls[0]

    assert command == [
        "xdotool",
        "mousemove",
        "960",
        "500",
        "click",
        "1",
    ]
    assert options["env"]["DISPLAY"] == ":99"
    assert options["check"] is True


# =============================================================================
# Auth Preflight Tests
# =============================================================================

class MockBrowserPage:
    """Mock BrowserPage for testing auth preflight checks."""

    def __init__(self, url="https://example.com/", title="Dashboard", selectors=None):
        self._url = url
        self._title = title
        self._selectors = selectors or {}

    def url(self):
        return self._url

    def title(self):
        return self._title

    def locator(self, selector: str):
        mock_locator = MagicMock()
        mock_locator.count.return_value = self._selectors.get(selector, 0)
        if self._selectors.get(selector, 0) > 0:
            mock_first = MagicMock()
            mock_first.is_visible.return_value = True
            mock_locator.first = mock_first
        else:
            mock_first = MagicMock()
            mock_first.is_visible.return_value = False
            mock_locator.first = mock_first
        return mock_locator


class MockBrowserRuntime:
    """Mock BrowserRuntime for testing."""

    def __init__(self, page):
        self._page = page

    @property
    def page(self):
        return self._page


def test_auth_preflight_check_rejects_auth_heygen_com():
    """Test that auth.heygen.com URL is rejected with authentication_not_completed."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, AuthBlockedConfig

    # Create mock page on auth.heygen.com
    page = MockBrowserPage(url="https://auth.heygen.com/login")
    handoff = AssistedLoginHandoff.__new__(AssistedLoginHandoff)
    handoff._browser_runtime = MockBrowserRuntime(page)
    handoff.blocked_config = AuthBlockedConfig(
        blocked_url_prefixes=("https://auth.heygen.com/",),
        blocked_selectors=(),
        blocked_title_contains=(),
        check_google_unsafe=True,
        check_cloudflare_verification=True,
    )
    handoff.target_url = "https://app.heygen.com/"
    handoff.profile = "default"  # Use default profile that exists

    # The _check_login_state method should detect auth.heygen.com
    result = handoff._check_login_state()
    assert result is not None, f"Expected HandoffResult, got {result}"
    assert result.status == "authentication_not_completed", f"Expected authentication_not_completed, got {result.status}"


def test_auth_preflight_check_rejects_login_title():
    """Test that page title containing 'Login' is rejected."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, AuthBlockedConfig

    page = MockBrowserPage(url="https://app.example.com/", title="Login - My App")
    handoff = AssistedLoginHandoff.__new__(AssistedLoginHandoff)
    handoff._browser_runtime = MockBrowserRuntime(page)
    handoff.blocked_config = AuthBlockedConfig(
        blocked_url_prefixes=(),
        blocked_selectors=(),
        blocked_title_contains=("login", "sign in", "sign-in", "signin"),
        check_google_unsafe=True,
        check_cloudflare_verification=True,
    )
    handoff.target_url = "https://app.example.com/"
    handoff.profile = "test"

    # The _preflight_auth_check should detect login in title
    result = handoff._preflight_auth_check()
    assert result is not None, f"Expected HandoffResult, got {result}"
    assert result.status == "authentication_not_completed", f"Expected authentication_not_completed, got {result.status}"


def test_auth_preflight_check_rejects_sign_in_title():
    """Test that page title containing 'Sign in' is rejected."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, AuthBlockedConfig

    page = MockBrowserPage(url="https://app.example.com/", title="Sign in to your account")
    handoff = AssistedLoginHandoff.__new__(AssistedLoginHandoff)
    handoff._browser_runtime = MockBrowserRuntime(page)
    handoff.blocked_config = AuthBlockedConfig(
        blocked_url_prefixes=(),
        blocked_selectors=(),
        blocked_title_contains=("login", "sign in", "sign-in", "signin"),
        check_google_unsafe=True,
        check_cloudflare_verification=True,
    )
    handoff.target_url = "https://app.example.com/"
    handoff.profile = "test"

    result = handoff._preflight_auth_check()
    assert result is not None, f"Expected HandoffResult, got {result}"
    assert result.status == "authentication_not_completed", f"Expected authentication_not_completed, got {result.status}"


def test_auth_preflight_check_rejects_visible_sign_in_with_google():
    """Test that visible 'Sign in with Google' button is rejected."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, AuthBlockedConfig

    selectors = {
        "button:has-text('Sign in with Google')": 1,
    }
    page = MockBrowserPage(url="https://app.example.com/", title="Dashboard", selectors=selectors)
    handoff = AssistedLoginHandoff.__new__(AssistedLoginHandoff)
    handoff._browser_runtime = MockBrowserRuntime(page)
    handoff.blocked_config = AuthBlockedConfig(
        blocked_url_prefixes=(),
        blocked_selectors=(),
        blocked_title_contains=("login", "sign in", "sign-in", "signin"),
        check_google_unsafe=True,
        check_cloudflare_verification=True,
    )
    handoff.target_url = "https://app.example.com/"
    handoff.profile = "test"

    result = handoff._preflight_auth_check()
    assert result is not None, f"Expected HandoffResult, got {result}"
    assert result.status == "authentication_not_completed", f"Expected authentication_not_completed, got {result.status}"


def test_auth_preflight_check_rejects_visible_sign_in_with_apple():
    """Test that visible 'Sign in with Apple' button is rejected."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, AuthBlockedConfig

    selectors = {
        "button:has-text('Sign in with Apple')": 1,
    }
    page = MockBrowserPage(url="https://app.example.com/", title="Dashboard", selectors=selectors)
    handoff = AssistedLoginHandoff.__new__(AssistedLoginHandoff)
    handoff._browser_runtime = MockBrowserRuntime(page)
    handoff.blocked_config = AuthBlockedConfig(
        blocked_url_prefixes=(),
        blocked_selectors=(),
        blocked_title_contains=("login", "sign in", "sign-in", "signin"),
        check_google_unsafe=True,
        check_cloudflare_verification=True,
    )
    handoff.target_url = "https://app.example.com/"
    handoff.profile = "test"

    result = handoff._preflight_auth_check()
    assert result is not None, f"Expected HandoffResult, got {result}"
    assert result.status == "authentication_not_completed", f"Expected authentication_not_completed, got {result.status}"


def test_auth_preflight_check_rejects_visible_use_email():
    """Test that visible 'Use email' button is rejected."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, AuthBlockedConfig

    selectors = {
        "button:has-text('Use email')": 1,
    }
    page = MockBrowserPage(url="https://app.example.com/", title="Dashboard", selectors=selectors)
    handoff = AssistedLoginHandoff.__new__(AssistedLoginHandoff)
    handoff._browser_runtime = MockBrowserRuntime(page)
    handoff.blocked_config = AuthBlockedConfig(
        blocked_url_prefixes=(),
        blocked_selectors=(),
        blocked_title_contains=("login", "sign in", "sign-in", "signin"),
        check_google_unsafe=True,
        check_cloudflare_verification=True,
    )
    handoff.target_url = "https://app.example.com/"
    handoff.profile = "test"

    result = handoff._preflight_auth_check()
    assert result is not None, f"Expected HandoffResult, got {result}"
    assert result.status == "authentication_not_completed", f"Expected authentication_not_completed, got {result.status}"


def test_auth_preflight_check_rejects_visible_use_sso():
    """Test that visible 'Use SSO' button is rejected."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, AuthBlockedConfig

    selectors = {
        "button:has-text('Use SSO')": 1,
    }
    page = MockBrowserPage(url="https://app.example.com/", title="Dashboard", selectors=selectors)
    handoff = AssistedLoginHandoff.__new__(AssistedLoginHandoff)
    handoff._browser_runtime = MockBrowserRuntime(page)
    handoff.blocked_config = AuthBlockedConfig(
        blocked_url_prefixes=(),
        blocked_selectors=(),
        blocked_title_contains=("login", "sign in", "sign-in", "signin"),
        check_google_unsafe=True,
        check_cloudflare_verification=True,
    )
    handoff.target_url = "https://app.example.com/"
    handoff.profile = "test"

    result = handoff._preflight_auth_check()
    assert result is not None, f"Expected HandoffResult, got {result}"
    assert result.status == "authentication_not_completed", f"Expected authentication_not_completed, got {result.status}"


def test_auth_preflight_check_google_unsafe_browser():
    """Test that Google unsafe browser warning returns auth_provider_blocked."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, AuthBlockedConfig

    selectors = {
        "div[aria-label*='unsafe']": 1,
    }
    page = MockBrowserPage(url="https://accounts.google.com/", title="Google", selectors=selectors)
    handoff = AssistedLoginHandoff.__new__(AssistedLoginHandoff)
    handoff._browser_runtime = MockBrowserRuntime(page)
    handoff.blocked_config = AuthBlockedConfig(
        blocked_url_prefixes=("https://accounts.google.com/",),
        blocked_selectors=("div[aria-label*='unsafe']",),
        blocked_title_contains=("login", "sign in", "sign-in", "signin"),
        check_google_unsafe=True,
        check_cloudflare_verification=True,
    )
    handoff.target_url = "https://accounts.google.com/"
    handoff.profile = "default"

    result = handoff._check_login_state()
    assert result is not None, f"Expected HandoffResult, got {result}"
    assert result.status == "auth_provider_blocked", f"Expected auth_provider_blocked, got {result.status}"


def test_auth_preflight_check_cloudflare_verification_failure():
    """Test that Cloudflare verification failure returns auth_provider_blocked."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, AuthBlockedConfig

    selectors = {
        "#challenge-running": 1,
    }
    page = MockBrowserPage(url="https://app.example.com/", title="Cloudflare Challenge", selectors=selectors)
    handoff = AssistedLoginHandoff.__new__(AssistedLoginHandoff)
    handoff._browser_runtime = MockBrowserRuntime(page)
    handoff.blocked_config = AuthBlockedConfig(
        blocked_url_prefixes=(),
        blocked_selectors=("#challenge-running", ".cf-challenge-running", "div.ray-id"),
        blocked_title_contains=("login", "sign in", "sign-in", "signin"),
        check_google_unsafe=True,
        check_cloudflare_verification=True,
    )
    handoff.target_url = "https://app.example.com/"
    handoff.profile = "default"

    result = handoff._check_login_state()
    assert result is not None, f"Expected HandoffResult, got {result}"
    assert result.status == "auth_provider_blocked", f"Expected auth_provider_blocked, got {result.status}"


def test_auth_preflight_check_allows_positive_success_selector():
    """Test that positive success_selector allows recording."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, AuthSuccessConfig, AuthBlockedConfig

    selectors = {
        ".user-avatar": 1,
    }
    page = MockBrowserPage(url="https://app.example.com/dashboard", title="Dashboard", selectors=selectors)
    handoff = AssistedLoginHandoff.__new__(AssistedLoginHandoff)
    handoff._browser_runtime = MockBrowserRuntime(page)
    handoff.success_config = AuthSuccessConfig(success_selector=".user-avatar")
    handoff.blocked_config = AuthBlockedConfig(
        blocked_url_prefixes=(),
        blocked_selectors=(),
        blocked_title_contains=(),
        check_google_unsafe=True,
        check_cloudflare_verification=True,
    )

    # The _monitor_authentication should detect success selector
    import threading
    handoff._authenticated = threading.Event()
    handoff._cancelled = threading.Event()
    handoff._lock = threading.Lock()
    handoff._result = None
    handoff.profile = "test"
    handoff.target_url = "https://app.example.com/login"
    handoff.timeout = 300

    # Run monitoring once
    handoff._monitor_authentication()

    assert handoff._authenticated.is_set()
    assert handoff._result is not None
    assert handoff._result.status == "authenticated"
    assert handoff._result.final_url == "https://app.example.com/dashboard"


def test_auth_preflight_check_allows_positive_success_url_prefix():
    """Test that positive success_url_prefix allows recording."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, AuthSuccessConfig, AuthBlockedConfig

    page = MockBrowserPage(url="https://app.example.com/dashboard", title="Dashboard")
    handoff = AssistedLoginHandoff.__new__(AssistedLoginHandoff)
    handoff._browser_runtime = MockBrowserRuntime(page)
    handoff.success_config = AuthSuccessConfig(success_url_prefix="https://app.example.com/dashboard")
    handoff.blocked_config = AuthBlockedConfig(
        blocked_url_prefixes=(),
        blocked_selectors=(),
        blocked_title_contains=(),
        check_google_unsafe=True,
        check_cloudflare_verification=True,
    )

    import threading
    handoff._authenticated = threading.Event()
    handoff._cancelled = threading.Event()
    handoff._lock = threading.Lock()
    handoff._result = None
    handoff.profile = "test"
    handoff.target_url = "https://app.example.com/login"
    handoff.timeout = 300

    handoff._monitor_authentication()

    assert handoff._authenticated.is_set()
    assert handoff._result is not None
    assert handoff._result.status == "authenticated"
    assert handoff._result.final_url == "https://app.example.com/dashboard"


# =============================================================================
# Runner Tests for Auth Preflight
# =============================================================================

def test_runner_preflight_failure_returns_nonzero_exit_and_safe_json(capsys):
    """Test that runner returns non-zero exit and safe JSON on preflight failure."""
    from hermes_screencast.runner import run_demo_record_command
    from hermes_screencast.demo.script import DemoActionType
    import argparse
    import pytest

    # Create a mock demo script that points to a login page
    mock_script = MagicMock()
    mock_script.steps = [
        MagicMock(action=DemoActionType.GOTO, url="https://app.example.com/login"),
        MagicMock(action=DemoActionType.WAIT, seconds=1),
    ]
    mock_script.validate = MagicMock()
    mock_script.title = "Test Demo"
    mock_script.preferences = {}
    mock_script.target = {"requires_auth": True}
    mock_script.metadata = {}

    # Mock auth_preflight_check to return a failed result
    from hermes_screencast.auth.handoff import HandoffResult
    mock_auth_result = HandoffResult(
        status="authentication_not_completed",
        profile="demo-record",
        profile_path="/tmp/demo-record",
        target_url="https://app.example.com/login",
        final_url="https://app.example.com/login",
        handoff_closed=True,
    )

    with patch('hermes_screencast.runner.load_demo_script', return_value=mock_script):
        with patch('hermes_screencast.demo.recording.auth_preflight_check', return_value=mock_auth_result):
            # Note: record_demo_script calls auth_preflight_checker (the parameter),
            # which defaults to auth_preflight_check, so the patch works
            args = argparse.Namespace(
                demo_json="/tmp/demo.json",
                output="/tmp/output.mp4",
                profile="demo-record",
                events_output=None,
            )

            # The command should raise SystemExit with code 1 and print safe JSON
            with pytest.raises(SystemExit) as exc_info:
                run_demo_record_command(args)

            assert exc_info.value.code == 1

            # Check that safe JSON was printed
            captured = capsys.readouterr()
            assert "authentication_not_completed" in captured.out
            assert "password" not in captured.out.lower()
            assert "cookie" not in captured.out.lower()
            assert "localstorage" not in captured.out.lower()
            assert "otp" not in captured.out.lower()
            assert "token" not in captured.out.lower()
            assert "secret" not in captured.out.lower()


def test_runner_preflight_json_no_secrets():
    """Test that error JSON doesn't contain internal secrets."""
    from hermes_screencast.auth.handoff import HandoffResult

    result = HandoffResult(
        status="authentication_not_completed",
        profile="test-profile",
        profile_path="/tmp/test-profile",
        target_url="https://app.example.com/login",  # No secrets in URL
        final_url="https://app.example.com/login",
        handoff_closed=True,
    )

    json_str = result.to_json()
    data = json.loads(json_str)

    # Check no internal secrets in JSON
    assert "password" not in json_str.lower()
    assert "cookie" not in json_str.lower()
    assert "localstorage" not in json_str.lower()
    assert "otp" not in json_str.lower()
    assert "token" not in json_str.lower()
    assert "secret" not in json_str.lower()

    # Verify structure
    assert data["status"] == "authentication_not_completed"
    assert data["profile"] == "test-profile"
    assert data["target_url"] == "https://app.example.com/login"
    assert data["final_url"] == "https://app.example.com/login"
    assert data["handoff_closed"] is True


# =============================================================================
# NoVNC URL Format Tests
# =============================================================================

def test_handoff_url_uses_encoded_path():
    """Test that handoff URL uses encoded path parameter with token."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, LoopbackConfig, create_handoff

    handoff = create_handoff("http://example.com/login")
    url = handoff._build_handoff_url(8080)

    # URL should contain path parameter
    assert "path=" in url, f"Expected path= in URL: {url}"
    assert "autoconnect=1" in url, f"Expected autoconnect=1 in URL: {url}"
    assert "resize=scale" in url, f"Expected resize=scale in URL: {url}"

    # Path should be URL-encoded websockify?token=<token>
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    query_params = urllib.parse.parse_qs(parsed.query)
    path_param = query_params.get('path', [''])[0]
    decoded_path = urllib.parse.unquote(path_param)

    assert decoded_path.startswith("websockify?token="), f"Expected websockify?token= in decoded path: {decoded_path}"
    assert handoff.token in decoded_path, f"Expected token in decoded path: {decoded_path}"


def test_handoff_token_not_in_regular_logs():
    """Test that token is not present in regular log output.

    This is a pure unit test - no Playwright, Chromium, Xvfb, or network listeners.
    """
    from hermes_screencast.auth.handoff import HandoffResult

    # Create a result with a known token-like value
    token = "test_token_abcdefghijklmnopqrstuvwxyz123456"
    result = HandoffResult(
        status="authenticated",
        profile="test-profile",
        profile_path="/tmp/test-profile",
        target_url="https://app.example.com/dashboard",
        final_url="https://app.example.com/dashboard",
        handoff_closed=True,
    )

    # Verify token is not in result JSON
    json_str = result.to_json()
    assert token not in json_str, "Token should not be in result JSON"

    # Verify token is not in dict representation
    result_dict = result.to_dict()
    json_dict_str = str(result_dict)
    assert token not in json_dict_str, "Token should not be in result dict"

    # Verify safe diagnostic fields don't contain token
    assert "token" not in json_str.lower()
    assert "secret" not in json_str.lower()
    assert "password" not in json_str.lower()
    assert "cookie" not in json_str.lower()
    assert "localstorage" not in json_str.lower()
    assert "sessionstorage" not in json_str.lower()
    assert "otp" not in json_str.lower()

    # Verify expected structure is present
    assert "authenticated" in json_str
    assert "test-profile" in json_str
    assert "dashboard" in json_str


# =============================================================================
# Cleanup Tests
# =============================================================================

def test_stop_cleans_up_only_owned_processes():
    """Test that stop() only cleans up owned processes."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, LoopbackConfig, create_handoff
    from unittest.mock import MagicMock

    handoff = create_handoff("http://example.com/login")

    # Set up mock processes
    mock_browser = MagicMock()
    mock_websockify = MagicMock()
    mock_x11vnc = MagicMock()
    mock_vdisplay = MagicMock()
    mock_vdisplay.cursor_hider = MagicMock()

    handoff._browser_runtime = mock_browser
    handoff._websockify_proc = mock_websockify
    handoff._x11vnc_proc = mock_x11vnc
    handoff._vdisplay = mock_vdisplay
    handoff._owns_display = True
    handoff._token_file = "/tmp/test_token_file"

    with patch('os.unlink') as mock_unlink:
        handoff.stop()

    # Verify all owned processes cleaned up
    mock_browser.__exit__.assert_called_once()
    mock_websockify.terminate.assert_called_once()
    mock_x11vnc.terminate.assert_called_once()
    mock_vdisplay.close.assert_called_once()
    mock_unlink.assert_called_once_with("/tmp/test_token_file")


def test_stop_does_not_close_external_display():
    """Test that stop() does not close external display."""
    from hermes_screencast.auth.handoff import AssistedLoginHandoff, LoopbackConfig, create_handoff
    from unittest.mock import MagicMock

    handoff = create_handoff("http://example.com/login")

    mock_browser = MagicMock()
    mock_websockify = MagicMock()
    mock_x11vnc = MagicMock()
    mock_vdisplay = MagicMock()
    mock_vdisplay.cursor_hider = MagicMock()

    handoff._browser_runtime = mock_browser
    handoff._websockify_proc = mock_websockify
    handoff._x11vnc_proc = mock_x11vnc
    handoff._vdisplay = mock_vdisplay
    handoff._owns_display = False  # External display

    with patch('os.unlink'):
        handoff.stop()

    # External display should NOT be closed
    mock_vdisplay.close.assert_not_called()
    # But cursor hider should be terminated
    mock_vdisplay.cursor_hider.terminate.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
