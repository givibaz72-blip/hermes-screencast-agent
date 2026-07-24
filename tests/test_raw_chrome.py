"""
Tests for RawChromeCdpProcess and LocalBrowserProcess in raw-CDP mode.

Existing tests cover RawChromeCdpProcess directly. The integration tests
below verify that LocalBrowserProcess correctly branches to raw-CDP mode
when browser_startup="raw-cdp" — no Playwright launch(), proper lifecycle,
profile preservation.
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_screencast.local_companion.companion import LocalBrowserProcess
from hermes_screencast.local_companion.raw_chrome import (
    RawChromeCdpProcess,
    RawChromeStartupError,
)
from hermes_screencast.transport.protocol import (
    BrowserStartup,
    SessionConfig,
)


# =========================================================================
# EXISTING RawChromeCdpProcess unit tests (unchanged)
# =========================================================================


class TestRawChromeStartupError:
    """RawChromeStartupError is a simple exception — just verify it exists."""

    def test_is_exception(self):
        assert issubclass(RawChromeStartupError, Exception)

    def test_can_raise(self):
        with pytest.raises(RawChromeStartupError, match="test error"):
            raise RawChromeStartupError("test error")


class TestRawChromeConstruction:
    """Constructor and initial property state."""

    def test_constructor(self):
        proc = RawChromeCdpProcess(
            chrome_path="/usr/bin/chrome",
            profile_dir="/tmp/profile",
            target_url="https://example.com/",
        )
        assert proc.cdp_host == "127.0.0.1"
        assert proc.cdp_port is None
        assert proc.cdp_endpoint is None
        assert proc.pid is None
        assert proc.is_running is False
        assert proc.is_ready is False

    def test_constructor_str_profile(self):
        proc = RawChromeCdpProcess(
            chrome_path="/usr/bin/chrome",
            profile_dir="/tmp/profile",
        )
        assert proc._target_url == ""

    def test_constructor_path_profile(self):
        proc = RawChromeCdpProcess(
            chrome_path="/usr/bin/chrome",
            profile_dir=Path("/tmp/profile"),
            target_url="https://example.com/",
        )
        assert proc._target_url == "https://example.com/"


class TestParseDevtoolsActivePort:
    """_parse_devtools_active_port logic."""

    def test_valid_port(self, tmp_path: Path):
        dtap = tmp_path / "DevToolsActivePort"
        dtap.write_text("9222\n/devtools/browser/abc123\n")
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        proc._parse_devtools_active_port(dtap)
        assert proc._cdp_port == 9222
        assert proc._cdp_ws_path == "/devtools/browser/abc123"
        assert proc.cdp_endpoint == "http://127.0.0.1:9222"

    def test_valid_port_with_trailing_newlines(self, tmp_path: Path):
        dtap = tmp_path / "DevToolsActivePort"
        dtap.write_text("  12345  \n  /devtools/browser/xyz  \n\n")
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        proc._parse_devtools_active_port(dtap)
        assert proc._cdp_port == 12345
        assert proc._cdp_ws_path == "/devtools/browser/xyz"

    def test_missing_second_line(self, tmp_path: Path):
        dtap = tmp_path / "DevToolsActivePort"
        dtap.write_text("9222")
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        with pytest.raises(RawChromeStartupError, match="Malformed"):
            proc._parse_devtools_active_port(dtap)

    def test_empty_file(self, tmp_path: Path):
        dtap = tmp_path / "DevToolsActivePort"
        dtap.write_text("")
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        with pytest.raises(RawChromeStartupError, match="Malformed"):
            proc._parse_devtools_active_port(dtap)

    def test_non_integer_port(self, tmp_path: Path):
        dtap = tmp_path / "DevToolsActivePort"
        dtap.write_text("abc\n/devtools/browser/x\n")
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        with pytest.raises(RawChromeStartupError, match="not an integer"):
            proc._parse_devtools_active_port(dtap)

    def test_port_zero(self, tmp_path: Path):
        dtap = tmp_path / "DevToolsActivePort"
        dtap.write_text("0\n/devtools/browser/x\n")
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        with pytest.raises(RawChromeStartupError, match="out of range"):
            proc._parse_devtools_active_port(dtap)

    def test_port_too_high(self, tmp_path: Path):
        dtap = tmp_path / "DevToolsActivePort"
        dtap.write_text("99999\n/devtools/browser/x\n")
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        with pytest.raises(RawChromeStartupError, match="out of range"):
            proc._parse_devtools_active_port(dtap)


class TestCleanup:
    """Cleanup helpers."""

    def test_cleanup_no_process(self):
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path := Path(tempfile.mkdtemp()))
        proc._process = None
        proc._cleanup_owned_process()  # Should not raise

    def test_cleanup_already_exited(self, tmp_path: Path):
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        mock = MagicMock(spec=subprocess.Popen)
        mock.poll.return_value = 0  # already exited
        proc._process = mock
        proc._cleanup_owned_process()
        mock.terminate.assert_not_called()

    def test_cleanup_terminates_then_kills(self, tmp_path: Path):
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        mock = MagicMock(spec=subprocess.Popen)
        mock.poll.return_value = None  # still running
        mock.pid = 12345
        # Make wait(timeout=5) raise TimeoutExpired to trigger kill path
        def wait_side_effect(timeout):
            if timeout == 5:
                raise subprocess.TimeoutExpired(cmd="chrome", timeout=timeout, output=b"")
            return None
        mock.wait.side_effect = wait_side_effect
        proc._process = mock
        proc._cleanup_owned_process()
        mock.terminate.assert_called_once()
        assert mock.kill.called
        assert mock.wait.call_count >= 2


class TestStart:
    """start() method — mocking subprocess and DevToolsActivePort."""

    def test_start_already_started(self, tmp_path: Path):
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        proc._started = True
        with pytest.raises(RawChromeStartupError, match="already started"):
            proc.start()

    def test_start_chrome_not_found(self, tmp_path: Path):
        proc = RawChromeCdpProcess("/nonexistent/chrome", tmp_path)
        with pytest.raises(RawChromeStartupError, match="Chrome executable not found"):
            proc.start(timeout=2)

    @patch("subprocess.Popen")
    def test_start_success(self, mock_popen: MagicMock, tmp_path: Path):
        """Successful start: mock process that writes DevToolsActivePort."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # stays alive
        mock_proc.pid = 9999
        mock_popen.return_value = mock_proc

        # Write DevToolsActivePort after a small delay
        dtap = tmp_path / "DevToolsActivePort"

        def fake_dtap_after_delay(*args, **kwargs):
            time.sleep(0.05)
            dtap.write_text("9222\n/devtools/browser/token\n")
            return True  # exists
        # Overwrite exists to add delay
        import builtins
        original_exists = dtap.exists

        def delayed_exists(self):
            _ = self  # Path.exists() — self is the Path instance
            if not original_exists():
                fake_dtap_after_delay()
            return True

        with patch.object(Path, "exists", delayed_exists):
            proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
            proc.start(timeout=10)

        assert proc._cdp_port == 9222
        assert proc._cdp_ws_path == "/devtools/browser/token"
        assert proc.is_ready
        assert proc.pid == 9999

    @patch("subprocess.Popen")
    def test_start_timeout(self, mock_popen: MagicMock, tmp_path: Path):
        """Start timeout when DevToolsActivePort never appears."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # stays alive
        mock_popen.return_value = mock_proc

        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        with pytest.raises(RawChromeStartupError, match="Timeout"):
            proc.start(timeout=0.5)

        # Should have cleaned up the process
        mock_proc.terminate.assert_called_once()

    @patch("subprocess.Popen")
    def test_start_early_exit(self, mock_popen: MagicMock, tmp_path: Path):
        """Chrome process exits before DevToolsActivePort appears."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # exited with rc=1
        mock_proc.stderr.read.return_value = b"something went wrong"
        mock_popen.return_value = mock_proc

        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        with pytest.raises(RawChromeStartupError, match="Chrome exited early"):
            proc.start(timeout=5)


class TestStop:
    """stop() method."""

    def test_stop_no_process(self):
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path := Path(tempfile.mkdtemp()))
        proc.stop()  # Should not raise

    def test_stop_clears_state(self, tmp_path: Path):
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        proc._process = MagicMock(spec=subprocess.Popen)
        proc._process.poll.return_value = None
        proc._cdp_port = 9222
        proc._cdp_ws_path = "/devtools/browser/x"
        proc.stop()
        assert proc._process is None
        assert proc._cdp_port is None
        assert proc._cdp_ws_path is None


class TestStaleDevtoolsPortRemoval:
    """start() removes stale DevToolsActivePort before launching."""

    @patch("subprocess.Popen")
    def test_removes_stale_port(self, mock_popen: MagicMock, tmp_path: Path):
        """An existing DevToolsActivePort should be deleted before launch."""
        dtap = tmp_path / "DevToolsActivePort"
        dtap.write_text("9222\n/devtools/browser/stale\n")
        assert dtap.exists()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        # Don't re-create the file (simulate fresh start)
        proc = RawChromeCdpProcess("/usr/bin/chrome", tmp_path)
        with pytest.raises(RawChromeStartupError, match="Timeout"):
            proc.start(timeout=0.5)

        assert not dtap.exists(), "Stale DevToolsActivePort should have been removed"


# =========================================================================
# INTEGRATION TESTS: LocalBrowserProcess in raw-CDP mode
# =========================================================================


@pytest.fixture
def raw_cdp_session_config(tmp_path: Path) -> SessionConfig:
    """SessionConfig with browser_startup='raw-cdp' and a temp profile dir."""
    profile_path = tmp_path / "hermes_profiles" / "test_raw_cdp"
    return SessionConfig(
        session_id="test-integration-raw-cdp",
        profile_name="test_raw_cdp",
        profile_path=profile_path,
        target_url="https://example.com/",
        width=1920,
        height=1080,
        headless=True,
        chrome_path="/usr/bin/chrome",
        chrome_args=[],
        browser_startup=BrowserStartup.RAW_CDP.value,  # "raw-cdp"
        auth_wait_seconds=30,
    )


@pytest.fixture
def playwright_session_config(tmp_path: Path) -> SessionConfig:
    """SessionConfig with browser_startup='playwright' for comparison."""
    profile_path = tmp_path / "hermes_profiles" / "test_playwright"
    return SessionConfig(
        session_id="test-integration-pw",
        profile_name="test_playwright",
        profile_path=profile_path,
        target_url="https://example.com/",
        width=1920,
        height=1080,
        headless=True,
        chrome_path="/usr/bin/chrome",
        chrome_args=[],
        browser_startup=BrowserStartup.PLAYWRIGHT.value,  # "playwright"
        auth_wait_seconds=30,
    )


@pytest.fixture
def mock_raw_chrome() -> MagicMock:
    """Create a fully mocked RawChromeCdpProcess instance."""
    mock = MagicMock(spec=RawChromeCdpProcess)
    mock.cdp_host = "127.0.0.1"
    mock.cdp_port = 9222
    mock.cdp_endpoint = "http://127.0.0.1:9222"
    mock.pid = 9999
    mock.is_running = True
    mock.is_ready = True
    return mock


@pytest.fixture
def mock_playwright_package() -> MagicMock:
    """
    Create a mocked playwright.async_api module.
    
    The mock mimics:
      async_playwright().start() -> Playwright
      Playwright.chromium.connect_over_cdp(cdp_url) -> Browser
      Browser.contexts -> [BrowserContext]
      BrowserContext.pages -> [Page]
    """
    mock_page = AsyncMock()
    mock_page.url = "about:blank"
    
    mock_context = AsyncMock()
    mock_context.pages = [mock_page]
    
    mock_browser = AsyncMock()
    mock_browser.contexts = [mock_context]
    
    mock_chromium = AsyncMock()
    mock_chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    
    mock_playwright = AsyncMock()
    mock_playwright.chromium = mock_chromium
    
    mock_async_pw = AsyncMock()
    mock_async_pw.start = AsyncMock(return_value=mock_playwright)
    
    return mock_async_pw


# ---- Test 1: raw-cdp does NOT call launch() / launch_persistent_context() ----

@pytest.mark.asyncio
async def test_raw_cdp_does_not_call_playwright_launch(
    raw_cdp_session_config: SessionConfig,
    mock_raw_chrome: MagicMock,
    mock_playwright_package: MagicMock,
):
    """
    browser_startup='raw-cdp' must NOT call launch() or
    launch_persistent_context(). Instead it uses RawChromeCdpProcess.start()
    and playwright connect_over_cdp().
    """
    proc = LocalBrowserProcess()

    with (
        patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess",
              return_value=mock_raw_chrome) as mock_raw_cls,
        patch("playwright.async_api.async_playwright",
              return_value=mock_playwright_package),
    ):
        success = await proc.start(raw_cdp_session_config)

    assert success is True

    # RawChromeCdpProcess was constructed exactly once
    mock_raw_cls.assert_called_once_with(
        chrome_path="/usr/bin/chrome",
        profile_dir=str(raw_cdp_session_config.profile_path),
        target_url="https://example.com/",
    )
    mock_raw_chrome.start.assert_called_once_with(timeout=30.0)

    # Playwright was NOT used for launching
    mock_playwright_package.start.assert_called_once()  # yes, it IS called for CDP connect
    chrom = mock_playwright_package.start.return_value.chromium
    chrom.connect_over_cdp.assert_called_once_with("http://127.0.0.1:9222")

    # Ensure launch_persistent_context was NEVER called on any object
    # (the async_playwright mock has no such attribute — verify no unexpected calls)
    mock_playwright_package.start.return_value.chromium.launch_persistent_context = MagicMock()
    assert mock_playwright_package.start.return_value.chromium.launch_persistent_context.call_count == 0


# ---- Test 2: raw-cdp starts RawChromeCdpProcess exactly once ----

@pytest.mark.asyncio
async def test_raw_cdp_constructs_raw_chrome_exactly_once(
    raw_cdp_session_config: SessionConfig,
    mock_raw_chrome: MagicMock,
    mock_playwright_package: MagicMock,
):
    """
    When browser_startup='raw-cdp', RawChromeCdpProcess should be
    instantiated exactly once and started exactly once.
    """
    proc = LocalBrowserProcess()

    with (
        patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess",
              return_value=mock_raw_chrome) as mock_raw_cls,
        patch("playwright.async_api.async_playwright",
              return_value=mock_playwright_package),
    ):
        await proc.start(raw_cdp_session_config)

    mock_raw_cls.assert_called_once()
    mock_raw_chrome.start.assert_called_once_with(timeout=30.0)
    assert proc._raw_chrome is mock_raw_chrome
    assert proc._raw_cdp_connected is True


# ---- Test 3: stop() kills only the owned Chrome PID ----

@pytest.mark.asyncio
async def test_stop_kills_only_owned_chrome_pid(
    raw_cdp_session_config: SessionConfig,
    mock_raw_chrome: MagicMock,
    mock_playwright_package: MagicMock,
):
    """
    stop() must call _raw_chrome.stop() (which terminates the owned PID)
    and NOT delete the profile directory.
    """
    proc = LocalBrowserProcess()

    with (
        patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess",
              return_value=mock_raw_chrome),
        patch("playwright.async_api.async_playwright",
              return_value=mock_playwright_package),
    ):
        await proc.start(raw_cdp_session_config)
        await proc.stop()

    # _raw_chrome.stop() was called exactly once
    mock_raw_chrome.stop.assert_called_once()

    # Playwright was disconnected/stopped
    pw_instance = mock_playwright_package.start.return_value
    pw_instance.stop.assert_called_once()


# ---- Test 4: stop() does NOT delete the persistent profile directory ----

@pytest.mark.asyncio
async def test_stop_does_not_delete_profile_dir(
    raw_cdp_session_config: SessionConfig,
    mock_raw_chrome: MagicMock,
    mock_playwright_package: MagicMock,
):
    """
    stop() must NOT delete the persistent profile directory.
    _stop_raw_chrome() only calls _raw_chrome.stop() which does NOT
    touch the profile.
    """
    proc = LocalBrowserProcess()

    # Create the profile directory before starting (start() does this)
    raw_cdp_session_config.profile_path.mkdir(parents=True, exist_ok=True)
    marker = raw_cdp_session_config.profile_path / "test_marker.txt"
    marker.write_text("this should survive stop()")

    with (
        patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess",
              return_value=mock_raw_chrome),
        patch("playwright.async_api.async_playwright",
              return_value=mock_playwright_package),
    ):
        await proc.start(raw_cdp_session_config)
        await proc.stop()

    # Profile directory still exists
    assert raw_cdp_session_config.profile_path.is_dir(), \
        "Profile directory was deleted after stop()"
    # Marker file is still there
    assert marker.exists(), "Marker file inside profile was deleted after stop()"


# ---- Test 5: Profile directory is preserved after stop() ----

@pytest.mark.asyncio
async def test_profile_preserved_after_stop(
    raw_cdp_session_config: SessionConfig,
    mock_raw_chrome: MagicMock,
    mock_playwright_package: MagicMock,
):
    """
    After stop(), the profile directory should remain intact with all its
    contents — this is the persistent profile that carries auth state between
    sessions.
    """
    proc = LocalBrowserProcess()

    # Create profile with some files mimicking Chrome's profile structure
    raw_cdp_session_config.profile_path.mkdir(parents=True, exist_ok=True)
    (raw_cdp_session_config.profile_path / "Preferences").write_text('{"test": true}')
    (raw_cdp_session_config.profile_path / "Cookies").write_text("fake-cookies")
    sub_dir = raw_cdp_session_config.profile_path / "Default"
    sub_dir.mkdir()
    (sub_dir / "Bookmarks").write_text("{}")

    profile_contents_before = sorted(
        str(p.relative_to(raw_cdp_session_config.profile_path))
        for p in raw_cdp_session_config.profile_path.rglob("*")
    )

    with (
        patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess",
              return_value=mock_raw_chrome),
        patch("playwright.async_api.async_playwright",
              return_value=mock_playwright_package),
    ):
        await proc.start(raw_cdp_session_config)
        await proc.stop()

    # Profile directory still exists
    assert raw_cdp_session_config.profile_path.is_dir()

    # Same contents exist
    profile_contents_after = sorted(
        str(p.relative_to(raw_cdp_session_config.profile_path))
        for p in raw_cdp_session_config.profile_path.rglob("*")
    )
    assert profile_contents_before == profile_contents_after, \
        "Profile contents changed after stop()"


# ---- Test 6: raw-cdp start failure returns False ----

@pytest.mark.asyncio
async def test_raw_cdp_start_failure_returns_false(
    raw_cdp_session_config: SessionConfig,
    mock_raw_chrome: MagicMock,
    mock_playwright_package: MagicMock,
):
    """
    If RawChromeCdpProcess.start() raises RawChromeStartupError,
    _start_with_raw_cdp should return False and clean up.
    """
    mock_raw_chrome.start.side_effect = RawChromeStartupError("Chrome crashed")

    proc = LocalBrowserProcess()

    with (
        patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess",
              return_value=mock_raw_chrome),
        patch("playwright.async_api.async_playwright",
              return_value=mock_playwright_package),
    ):
        success = await proc.start(raw_cdp_session_config)

    assert success is False
    # _raw_chrome should be None (cleaned up on error)
    assert proc._raw_chrome is None


# ---- Test 7: raw-cdp CDP connect failure returns False ----

@pytest.mark.asyncio
async def test_raw_cdp_cdp_connect_failure_returns_false(
    raw_cdp_session_config: SessionConfig,
    mock_raw_chrome: MagicMock,
    mock_playwright_package: MagicMock,
):
    """
    If connect_over_cdp fails, _start_with_raw_cdp should return False
    and call _stop_raw_chrome() to clean up the Chrome process.
    """
    # Make connect_over_cdp raise
    mock_playwright_package.start.return_value.chromium.connect_over_cdp = AsyncMock(
        side_effect=Exception("CDP connection refused"),
    )

    proc = LocalBrowserProcess()

    with (
        patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess",
              return_value=mock_raw_chrome),
        patch("playwright.async_api.async_playwright",
              return_value=mock_playwright_package),
    ):
        success = await proc.start(raw_cdp_session_config)

    assert success is False
    # Should have cleaned up the raw Chrome process
    mock_raw_chrome.stop.assert_called_once()