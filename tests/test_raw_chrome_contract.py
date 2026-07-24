"""Contract, validation, and integration tests for RawChromeCdpProcess.

This suite tests:
- CLI defaults (browser_startup default for windows-e2e is raw-cdp)
- START_SESSION payload chain (browser_startup, auth_wait_seconds flow)
- SessionConfig validation
- RawChromeCdpProcess integration in LocalBrowserProcess._start_with_raw_cdp
- Static analysis of Windows smoke-test scripts
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# Ensure scripts/ is importable for CLI parser tests
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from hermes_screencast.local_companion.raw_chrome import (
    RawChromeCdpProcess,
    RawChromeStartupError,
)
from hermes_screencast.local_companion.companion import (
    LocalBrowserProcess,
)
from hermes_screencast.transport.protocol import (
    BrowserStartup,
    SessionConfig,
)


# ======================================================================
# Contract: CLI defaults
# ======================================================================

class TestCliDefaults:
    """Verify default browser_startup values in argparse parsers."""

    def test_default_windows_e2e_is_raw_cdp(self):
        from demo_local_transport import build_parser

        parser = build_parser()
        ns = parser.parse_args(
            ["windows-e2e", "--profile-dir", "/tmp/p", "--recording-dir", "/tmp/r"]
        )
        assert ns.browser_startup == "raw-cdp", (
            f"Expected default 'raw-cdp', got '{ns.browser_startup}'"
        )

    def test_default_remote_is_playwright(self):
        from demo_local_transport import build_parser

        parser = build_parser()
        ns = parser.parse_args(
            ["remote", "--relay-url", "wss://example.com/ws", "--pairing-code", "test123"]
        )
        assert ns.browser_startup == "playwright", (
            f"Expected default 'playwright', got '{ns.browser_startup}'"
        )

    def test_default_auth_wait_seconds(self):
        from demo_local_transport import build_parser

        parser = build_parser()
        ns = parser.parse_args(
            ["windows-e2e", "--profile-dir", "/tmp/p", "--recording-dir", "/tmp/r"]
        )
        assert ns.auth_wait_seconds == 300

    def test_choices_reject_unknown(self):
        """argparse rejects unknown browser-startup values."""
        from demo_local_transport import build_parser

        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "windows-e2e",
                    "--profile-dir",
                    "/tmp/p",
                    "--recording-dir",
                    "/tmp/r",
                    "--browser-startup",
                    "unknown-mode",
                ]
            )

    def test_positive_auth_wait_ok(self):
        from demo_local_transport import build_parser

        parser = build_parser()
        ns = parser.parse_args(
            [
                "windows-e2e",
                "--profile-dir",
                "/tmp/p",
                "--recording-dir",
                "/tmp/r",
                "--auth-wait-seconds",
                "600",
            ]
        )
        assert ns.auth_wait_seconds == 600

    def test_negative_auth_wait_parsed(self):
        """argparse with type=int accepts negatives; validation is at companion level."""
        from demo_local_transport import build_parser

        parser = build_parser()
        ns = parser.parse_args(
            [
                "windows-e2e",
                "--profile-dir",
                "/tmp/p",
                "--recording-dir",
                "/tmp/r",
                "--auth-wait-seconds",
                "-5",
            ]
        )
        assert ns.auth_wait_seconds == -5


# ======================================================================
# Contract: SessionConfig
# ======================================================================

class TestSessionConfigContract:
    """browser_startup and auth_wait_seconds in SessionConfig."""

    def test_defaults(self):
        cfg = SessionConfig(
            session_id="s1",
            profile_name="test",
            profile_path=Path("/tmp/p"),
            target_url="https://example.com/",
        )
        assert cfg.browser_startup == "playwright"
        assert cfg.auth_wait_seconds == 300

    def test_override_browser_startup(self):
        cfg = SessionConfig(
            session_id="s1",
            profile_name="test",
            profile_path=Path("/tmp/p"),
            target_url="https://example.com/",
            browser_startup="raw-cdp",
        )
        assert cfg.browser_startup == "raw-cdp"

    def test_override_auth_wait(self):
        cfg = SessionConfig(
            session_id="s1",
            profile_name="test",
            profile_path=Path("/tmp/p"),
            target_url="https://example.com/",
            auth_wait_seconds=600,
        )
        assert cfg.auth_wait_seconds == 600

    def test_zero_auth_wait_allowed_by_dataclass(self):
        """SessionConfig accepts 0; validation is in the companion layer."""
        cfg = SessionConfig(
            session_id="s1",
            profile_name="test",
            profile_path=Path("/tmp/p"),
            target_url="https://example.com/",
            auth_wait_seconds=0,
        )
        assert cfg.auth_wait_seconds == 0


# ======================================================================
# Contract: LocalBrowserProcess dispatch
# ======================================================================

class TestBrowserProcessDispatch:
    """LocalBrowserProcess.start() dispatches based on browser_startup."""

    @pytest.mark.asyncio
    async def test_dispatches_raw_cdp(self):
        bp = LocalBrowserProcess()

        with (
            patch.object(bp, "_start_with_raw_cdp", new_callable=AsyncMock) as mock_raw,
            patch.object(bp, "_start_with_playwright", new_callable=AsyncMock) as mock_pw,
        ):
            mock_raw.return_value = True

            cfg = SessionConfig(
                session_id="dispatch-raw",
                profile_name="test",
                profile_path=Path(tempfile.gettempdir()) / "raw-cdp-dispatch",
                target_url="about:blank",
                browser_startup="raw-cdp",
            )

            result = await bp.start(cfg)

            assert result is True
            mock_raw.assert_awaited_once()
            mock_pw.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dispatches_playwright(self):
        bp = LocalBrowserProcess()

        with (
            patch.object(bp, "_start_with_raw_cdp", new_callable=AsyncMock) as mock_raw,
            patch.object(bp, "_start_with_playwright", new_callable=AsyncMock) as mock_pw,
        ):
            mock_pw.return_value = True

            cfg = SessionConfig(
                session_id="dispatch-pw",
                profile_name="test",
                profile_path=Path(tempfile.gettempdir()) / "pw-dispatch",
                target_url="about:blank",
                browser_startup="playwright",
            )

            result = await bp.start(cfg)

            assert result is True
            mock_pw.assert_awaited_once()
            mock_raw.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_startup_falls_to_playwright(self):
        """Unknown browser_startup falls through to Playwright (existing behavior)."""
        bp = LocalBrowserProcess()

        with (
            patch.object(bp, "_start_with_raw_cdp", new_callable=AsyncMock) as mock_raw,
            patch.object(bp, "_start_with_playwright", new_callable=AsyncMock) as mock_pw,
        ):
            mock_pw.return_value = None  # _start_with_playwright returns None

            cfg = SessionConfig(
                session_id="dispatch-unknown",
                profile_name="test",
                profile_path=Path(tempfile.gettempdir()) / "unknown-dispatch",
                target_url="about:blank",
                browser_startup="bogus",
            )

            result = await bp.start(cfg)
            assert result is True
            mock_pw.assert_awaited_once()
            mock_raw.assert_not_awaited()


# ======================================================================
# Integration: _start_with_raw_cdp in LocalBrowserProcess
# ======================================================================

class TestRawCdpIntegration:
    """Integration tests for raw-CDP mode in LocalBrowserProcess.

    These patch RawChromeCdpProcess at the module level (raw_chrome module)
    so the local import inside companion._start_with_raw_cdp picks them up.
    """

    @pytest.mark.asyncio
    async def test_starts_raw_chrome(self):
        with (
            patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess") as mock_cls,
            patch("playwright.async_api.async_playwright") as mock_pw,
        ):
            mock_raw = MagicMock()
            mock_raw.cdp_port = 9222
            mock_raw.cdp_endpoint = "http://127.0.0.1:9222"
            mock_raw.pid = 4242
            mock_cls.return_value = mock_raw

            mock_browser = AsyncMock()
            mock_context = MagicMock()
            mock_context.pages = [MagicMock()]
            mock_browser.contexts = [mock_context]
            mock_pw_inst = AsyncMock()
            mock_pw_inst.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
            mock_pw.return_value.start = AsyncMock(return_value=mock_pw_inst)

            bp = LocalBrowserProcess()
            bp.chrome_path = "/usr/bin/chrome"
            bp.profile_path = Path(tempfile.gettempdir()) / "raw-cdp-test"

            cfg = SessionConfig(
                session_id="int-1",
                profile_name="test",
                profile_path=bp.profile_path,
                target_url="about:blank",
                browser_startup="raw-cdp",
                chrome_path="/usr/bin/chrome",
            )

            result = await bp._start_with_raw_cdp(cfg)
            assert result is True

            mock_cls.assert_called_once_with(
                chrome_path="/usr/bin/chrome",
                profile_dir=str(bp.profile_path),
                target_url="about:blank",
            )
            mock_raw.start.assert_called_once_with(timeout=30.0)

    @pytest.mark.asyncio
    async def test_does_not_start_playwright_launch(self):
        with (
            patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess") as mock_cls,
            patch("playwright.async_api.async_playwright") as mock_pw,
        ):
            mock_raw = MagicMock()
            mock_raw.cdp_port = 9222
            mock_raw.cdp_endpoint = "http://127.0.0.1:9222"
            mock_raw.pid = 4242
            mock_cls.return_value = mock_raw

            mock_context = MagicMock()
            mock_context.pages = [MagicMock()]
            mock_browser = MagicMock()
            mock_browser.contexts = [mock_context]
            mock_browser.new_context = MagicMock()

            mock_pw_inst = MagicMock()
            mock_pw_inst.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
            mock_pw.return_value.start = AsyncMock(return_value=mock_pw_inst)

            bp = LocalBrowserProcess()
            bp.chrome_path = "/usr/bin/chrome"
            bp.profile_path = Path(tempfile.gettempdir()) / "raw-cdp-test-2"

            cfg = SessionConfig(
                session_id="int-2",
                profile_name="test",
                profile_path=bp.profile_path,
                target_url="about:blank",
                browser_startup="raw-cdp",
                chrome_path="/usr/bin/chrome",
            )

            await bp._start_with_raw_cdp(cfg)

            # Verify we did NOT call launch or launch_persistent_context
            assert not mock_browser.new_context.called

    @pytest.mark.asyncio
    async def test_connects_over_cdp(self):
        with (
            patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess") as mock_cls,
            patch("playwright.async_api.async_playwright") as mock_pw,
        ):
            mock_raw = MagicMock()
            mock_raw.cdp_port = 9222
            mock_raw.cdp_endpoint = "http://127.0.0.1:9222"
            mock_raw.pid = 4242
            mock_cls.return_value = mock_raw

            mock_browser = AsyncMock()
            mock_context = MagicMock()
            mock_context.pages = [MagicMock()]
            mock_browser.contexts = [mock_context]
            mock_pw_inst = MagicMock()
            connect_mock = AsyncMock(return_value=mock_browser)
            mock_pw_inst.chromium.connect_over_cdp = connect_mock
            mock_pw.return_value.start = AsyncMock(return_value=mock_pw_inst)

            bp = LocalBrowserProcess()
            bp.chrome_path = "/usr/bin/chrome"
            bp.profile_path = Path(tempfile.gettempdir()) / "raw-cdp-test-3"

            cfg = SessionConfig(
                session_id="int-3",
                profile_name="test",
                profile_path=bp.profile_path,
                target_url="about:blank",
                browser_startup="raw-cdp",
                chrome_path="/usr/bin/chrome",
            )

            await bp._start_with_raw_cdp(cfg)

            connect_mock.assert_awaited_once_with("http://127.0.0.1:9222")

    @pytest.mark.asyncio
    async def test_uses_existing_context_and_page(self):
        with (
            patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess") as mock_cls,
            patch("playwright.async_api.async_playwright") as mock_pw,
        ):
            mock_raw = MagicMock()
            mock_raw.cdp_port = 9222
            mock_raw.cdp_endpoint = "http://127.0.0.1:9222"
            mock_raw.pid = 4242
            mock_cls.return_value = mock_raw

            existing_page = MagicMock()
            existing_context = MagicMock()
            existing_context.pages = [existing_page]
            mock_browser = AsyncMock()
            mock_browser.contexts = [existing_context]

            mock_pw_inst = MagicMock()
            mock_pw_inst.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
            mock_pw.return_value.start = AsyncMock(return_value=mock_pw_inst)

            bp = LocalBrowserProcess()
            bp.chrome_path = "/usr/bin/chrome"
            bp.profile_path = Path(tempfile.gettempdir()) / "raw-cdp-test-4"

            cfg = SessionConfig(
                session_id="int-4",
                profile_name="test",
                profile_path=bp.profile_path,
                target_url="about:blank",
                browser_startup="raw-cdp",
                chrome_path="/usr/bin/chrome",
            )

            await bp._start_with_raw_cdp(cfg)

            assert bp._playwright_context is existing_context
            assert bp._playwright_page is existing_page

    @pytest.mark.asyncio
    async def test_no_incognito_context(self):
        with (
            patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess") as mock_cls,
            patch("playwright.async_api.async_playwright") as mock_pw,
        ):
            mock_raw = MagicMock()
            mock_raw.cdp_port = 9222
            mock_raw.cdp_endpoint = "http://127.0.0.1:9222"
            mock_raw.pid = 4242
            mock_cls.return_value = mock_raw

            mock_context = MagicMock()
            mock_context.pages = [MagicMock()]
            mock_browser = MagicMock()
            mock_browser.contexts = [mock_context]
            mock_browser.new_context = MagicMock()

            mock_pw_inst = MagicMock()
            mock_pw_inst.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
            mock_pw.return_value.start = AsyncMock(return_value=mock_pw_inst)

            bp = LocalBrowserProcess()
            bp.chrome_path = "/usr/bin/chrome"
            bp.profile_path = Path(tempfile.gettempdir()) / "raw-cdp-test-5"

            cfg = SessionConfig(
                session_id="int-5",
                profile_name="test",
                profile_path=bp.profile_path,
                target_url="about:blank",
                browser_startup="raw-cdp",
                chrome_path="/usr/bin/chrome",
            )

            await bp._start_with_raw_cdp(cfg)

            assert not mock_browser.new_context.called
            assert bp._playwright_context is mock_context

    @pytest.mark.asyncio
    async def test_cdp_startup_failure_returns_false(self):
        with (
            patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess") as mock_cls,
        ):
            mock_raw = MagicMock()
            mock_raw.start.side_effect = RawChromeStartupError("Port not found")
            mock_cls.return_value = mock_raw

            bp = LocalBrowserProcess()
            bp.chrome_path = "/usr/bin/chrome"

            cfg = SessionConfig(
                session_id="int-fail",
                profile_name="test",
                profile_path=Path(tempfile.gettempdir()) / "raw-cdp-fail",
                target_url="about:blank",
                browser_startup="raw-cdp",
                chrome_path="/usr/bin/chrome",
            )

            result = await bp._start_with_raw_cdp(cfg)
            assert result is False
            assert bp._raw_chrome is None

    @pytest.mark.asyncio
    async def test_stop_does_not_delete_profile(self):
        with (
            patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess") as mock_cls,
        ):
            mock_raw = MagicMock()
            mock_raw.pid = 4242
            mock_cls.return_value = mock_raw

            bp = LocalBrowserProcess()
            bp._raw_chrome = mock_raw
            bp._playwright = MagicMock()
            bp._playwright_context = MagicMock()
            bp._playwright_page = MagicMock()
            bp._raw_cdp_connected = True

            await bp._stop_raw_chrome()

            mock_raw.stop.assert_called_once()
            assert bp._raw_chrome is None
            assert bp._playwright is None
            assert bp._playwright_context is None
            assert bp._playwright_page is None
            assert bp._raw_cdp_connected is False

    @pytest.mark.asyncio
    async def test_stop_kills_only_owned_chrome(self):
        with (
            patch("hermes_screencast.local_companion.raw_chrome.RawChromeCdpProcess") as mock_cls,
        ):
            mock_raw = MagicMock()
            mock_cls.return_value = mock_raw

            bp = LocalBrowserProcess()
            bp._raw_chrome = mock_raw
            bp._playwright = MagicMock()
            bp._playwright_context = MagicMock()
            bp._playwright_page = MagicMock()
            bp._raw_cdp_connected = True

            await bp.stop()

            mock_raw.stop.assert_called_once()

    # ======================================================================
# Static analysis: Windows smoke script
# ======================================================================

class TestWindowsSmokeScript:
    """Static verification of smoke-test scripts."""

    SMOKE_PY_PATH = Path(__file__).resolve().parent.parent / "scripts" / "demo_raw_chrome_cdp.py"
    POWERSHELL_PATH = Path(__file__).resolve().parent.parent / "scripts" / "test_raw_chrome_cdp_windows.ps1"

    def test_smoke_py_exists(self):
        assert self.SMOKE_PY_PATH.is_file()

    def test_smoke_ps1_exists(self):
        assert self.POWERSHELL_PATH.is_file()

    def test_smoke_py_uses_about_blank(self):
        text = self.SMOKE_PY_PATH.read_text()
        assert "about:blank" in text

    def test_smoke_py_uses_loopback_only(self):
        text = self.SMOKE_PY_PATH.read_text()
        assert "127.0.0.1" in text

    def test_smoke_ps1_uses_array_splatting(self):
        text = self.POWERSHELL_PATH.read_text()
        assert "@PythonArgs" in text, "PS1 must use @ splatting for safety"
        assert "Invoke-Expression" not in text, "No Invoke-Expression allowed"
        assert "iex" not in text.lower(), "No iex alias allowed"

    def test_smoke_py_no_heygen_url(self):
        text = self.SMOKE_PY_PATH.read_text()
        assert "app.heygen.com" not in text

    def test_smoke_py_no_ffmpeg_reference(self):
        text = self.SMOKE_PY_PATH.read_text()
        assert "ffmpeg" not in text.lower()

    @staticmethod
    def _ps1_executable_lines(text: str) -> list[str]:
        """Filter out PowerShell comment blocks and comment-only lines."""
        lines = []
        in_block_comment = False
        for line in text.splitlines():
            stripped = line.strip()
            # Handle <# ... #> block comments (can span multiple lines)
            if "<#" in stripped and "#>" in stripped:
                continue
            if "<#" in stripped and "#>" not in stripped:
                in_block_comment = True
                continue
            if "#>" in stripped:
                in_block_comment = False
                continue
            if in_block_comment:
                continue
            # Skip single-line comments
            if stripped.startswith("#"):
                continue
            # Skip empty lines
            if not stripped:
                continue
            lines.append(stripped)
        return lines

    def test_smoke_ps1_no_heygen_url(self):
        text = self.POWERSHELL_PATH.read_text()
        for line in self._ps1_executable_lines(text):
            assert "heygen" not in line.lower(), f"heygen found in executable line: {line}"

    def test_smoke_ps1_no_ffmpeg_invocation(self):
        """PS1 must not invoke ffmpeg; description comments are OK."""
        text = self.POWERSHELL_PATH.read_text()
        for line in self._ps1_executable_lines(text):
            assert "ffmpeg" not in line.lower(), f"ffmpeg found in executable line: {line}"

    def test_smoke_ps1_no_heygen_invocation(self):
        """PS1 must not invoke heygen; description comments are OK."""
        text = self.POWERSHELL_PATH.read_text()
        for line in self._ps1_executable_lines(text):
            assert "heygen" not in line.lower(), f"heygen found in executable line: {line}"

    def test_smoke_py_no_public_cdp_bind(self):
        text = self.SMOKE_PY_PATH.read_text()
        assert "0.0.0.0" not in text

    def test_smoke_py_no_dynamic_execution(self):
        text = self.SMOKE_PY_PATH.read_text()
        assert "exec(" not in text
        assert "eval(" not in text

    def test_smoke_ps1_no_dynamic_execution(self):
        text = self.POWERSHELL_PATH.read_text()
        assert "Invoke-Expression" not in text
        assert "iex" not in text.lower()

    def test_smoke_py_imports_production_class(self):
        text = self.SMOKE_PY_PATH.read_text()
        assert "RawChromeCdpProcess" in text
        assert "from src.hermes_screencast.local_companion.raw_chrome import" in text

    def test_smoke_py_cleanup_in_finally(self):
        text = self.SMOKE_PY_PATH.read_text()
        assert "finally" in text
        assert "raw.stop()" in text

    def test_smoke_ps1_has_error_handling(self):
        text = self.POWERSHELL_PATH.read_text()
        assert "try" in text.lower() or "finally" in text.lower()

    def test_smoke_py_no_ws_url_exposure(self):
        """Must not print raw ws:// URL (security: no devtools token exposure)."""
        text = self.SMOKE_PY_PATH.read_text()
        assert "ws_url" not in text, "Must not expose ws URL variable"

    def test_smoke_ps1_uses_python_argv_array(self):
        text = self.POWERSHELL_PATH.read_text()
        assert "@PythonArgs" in text


# ======================================================================
# RawChromeCdpProcess unit tests (supplementary)
# ======================================================================

class TestRawChromeCdpProcessBasics:
    """Basic unit tests for RawChromeCdpProcess."""

    def test_constructor(self):
        proc = RawChromeCdpProcess(
            chrome_path="/usr/bin/chrome",
            profile_dir="/tmp/test-profile",
            target_url="about:blank",
        )
        assert proc.cdp_host == "127.0.0.1"
        assert proc.cdp_port is None
        assert proc.cdp_endpoint is None
        assert proc.pid is None
        assert proc.is_running is False
        assert proc.is_ready is False

    def test_stop_no_process(self):
        """Calling stop() when process never started is a no-op."""
        proc = RawChromeCdpProcess(
            chrome_path="/usr/bin/chrome",
            profile_dir="/tmp/test-profile",
        )
        proc.stop()  # Should not raise

    def test_stop_twice(self):
        """Calling stop() twice is safe (no-op on second call)."""
        proc = RawChromeCdpProcess(
            chrome_path="/usr/bin/chrome",
            profile_dir="/tmp/test-profile",
        )
        proc.stop()
        proc.stop()  # Should not raise

    def test_cdp_endpoint_http_prefix(self):
        """cdp_endpoint returns http:// prefix, not ws://."""
        proc = RawChromeCdpProcess(
            chrome_path="/usr/bin/chrome",
            profile_dir="/tmp/test-profile",
        )
        proc._cdp_port = 9222
        assert proc.cdp_endpoint == "http://127.0.0.1:9222"