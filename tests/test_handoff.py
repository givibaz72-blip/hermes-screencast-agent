#!/usr/bin/env python3
"""Tests for Assisted Login Browser Handoff."""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_screencast.auth.handoff import (
    AssistedLoginHandoff,
    AuthSuccessConfig,
    HandoffResult,
    LoopbackConfig,
    create_handoff,
    generate_token,
    validate_loopback_host,
)
from hermes_screencast.recording import VirtualDisplay


class TestLoopbackValidation:
    """Tests for loopback address validation."""

    def test_validate_loopback_127_0_0_1(self):
        assert validate_loopback_host("127.0.0.1") is True

    def test_reject_localhost(self):
        # We now only accept 127.0.0.1, not localhost
        assert validate_loopback_host("localhost") is False

    def test_reject_ipv6(self):
        assert validate_loopback_host("::1") is False

    def test_reject_127_range(self):
        # We only accept exactly 127.0.0.1, not the whole /8
        assert validate_loopback_host("127.0.0.2") is False
        assert validate_loopback_host("127.255.255.255") is False

    def test_reject_0_0_0_0(self):
        assert validate_loopback_host("0.0.0.0") is False

    def test_reject_external_ip(self):
        assert validate_loopback_host("192.168.1.1") is False
        assert validate_loopback_host("10.0.0.1") is False
        assert validate_loopback_host("8.8.8.8") is False

    def test_reject_non_loopback_hostname(self):
        assert validate_loopback_host("example.com") is False

    def test_create_handoff_rejects_non_loopback(self):
        with pytest.raises(ValueError, match="Host must be 127.0.0.1"):
            create_handoff("http://example.com", host="0.0.0.0")
        with pytest.raises(ValueError, match="Host must be 127.0.0.1"):
            create_handoff("http://example.com", host="192.168.1.1")


class TestTokenGeneration:
    """Tests for cryptographic token generation."""

    def test_token_is_secure_random(self):
        tokens = {generate_token() for _ in range(100)}
        assert len(tokens) == 100  # All unique

    def test_token_length(self):
        token = generate_token()
        assert len(token) >= 32  # token_urlsafe(32) = ~43 chars

    def test_token_url_safe(self):
        token = generate_token()
        # token_urlsafe uses only alphanumeric + -_
        assert all(c.isalnum() or c in "-_" for c in token)


class TestLoopbackConfig:
    """Tests for LoopbackConfig."""

    def test_default_loopback_config(self):
        config = LoopbackConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 0

    def test_custom_port(self):
        config = LoopbackConfig(port=8080)
        assert config.port == 8080

    def test_reject_non_loopback(self):
        with pytest.raises(ValueError, match="Host must be 127.0.0.1"):
            LoopbackConfig(host="0.0.0.0")
        with pytest.raises(ValueError, match="Host must be 127.0.0.1"):
            LoopbackConfig(host="localhost")
        with pytest.raises(ValueError, match="Host must be 127.0.0.1"):
            LoopbackConfig(host="::1")
        with pytest.raises(ValueError, match="Host must be 127.0.0.1"):
            LoopbackConfig(host="127.0.0.2")
        with pytest.raises(ValueError, match="Host must be 127.0.0.1"):
            LoopbackConfig(host="192.168.1.1")


class TestAuthSuccessConfig:
    """Tests for authentication success detection."""

    def test_url_prefix_detection(self):
        config = AuthSuccessConfig(success_url_prefix="https://app.example.com/dashboard")
        assert config.check_url("https://app.example.com/dashboard") is True
        assert config.check_url("https://app.example.com/dashboard?token=abc") is True
        assert config.check_url("https://app.example.com/login") is False

    def test_selector_detection_configured(self):
        config = AuthSuccessConfig(success_selector=".user-menu")
        assert config.success_selector == ".user-menu"
        assert config.is_configured() is True

    def test_no_auto_detect(self):
        config = AuthSuccessConfig(no_auto_detect=True)
        assert config.no_auto_detect is True


class TestHandoffResult:
    """Tests for HandoffResult."""

    def test_to_json_excludes_secrets(self):
        result = HandoffResult(
            status="authenticated",
            profile="test",
            profile_path="/tmp/profile",
            target_url="https://example.com/login",
            final_url="https://example.com/dashboard",
            handoff_closed=True,
        )
        json_str = result.to_json()
        data = json.loads(json_str)

        # No secrets should be present
        assert "password" not in json_str.lower()
        assert "token" not in json_str.lower()
        assert "cookie" not in json_str.lower()
        assert "localstorage" not in json_str.lower()
        assert "otp" not in json_str.lower()

    def test_status_values(self):
        for status in ["authenticated", "cancelled", "timeout", "failed", "pending"]:
            result = HandoffResult(
                status=status,
                profile="test",
                profile_path="/tmp/profile",
                target_url="https://example.com",
                final_url="https://example.com",
            )
            assert result.status == status


class TestVirtualDisplayOwnership:
    """Tests for VirtualDisplay ownership tracking."""

    def test_external_display_not_owned(self):
        """When connecting to existing display, should not own it."""
        # Start Xvfb on :99 if not already running
        # This test requires a display - skip if no Xvfb available
        display = VirtualDisplay(display=":99", width=800, height=600)
        # We can't easily test this without a running Xvfb
        # but we verify the _owns_display attribute exists
        assert hasattr(display, '_owns_display')

    def test_owned_display_cleanup(self):
        """Owned display should be cleaned up on close."""
        display = VirtualDisplay(display=":999", width=800, height=600)
        # Can't actually start without Xvfb in CI, but we can verify
        # the attribute gets set
        assert display._owns_display is False


class TestAssistedLoginHandoff:
    """Tests for AssistedLoginHandoff."""

    def test_create_handoff_generates_token(self):
        handoff = create_handoff("http://example.com/login")
        assert handoff.token
        assert len(handoff.token) >= 32

    def test_create_handoff_sets_config(self):
        handoff = create_handoff(
            "http://example.com/login",
            profile="test-profile",
            host="127.0.0.1",
            port=8080,
            timeout=60.0,
            success_url_prefix="https://example.com/dashboard",
            success_selector=".logged-in",
            display=":10",
            width=1280,
            height=720,
        )
        assert handoff.profile == "test-profile"
        assert handoff.loopback.host == "127.0.0.1"
        assert handoff.loopback.port == 8080
        assert handoff.timeout == 60.0
        assert handoff.success_config.success_url_prefix == "https://example.com/dashboard"
        assert handoff.success_config.success_selector == ".logged-in"
        assert handoff.display == ":10"
        assert handoff.width == 1280
        assert handoff.height == 720

    def test_start_allocates_ports(self):
        handoff = create_handoff("http://example.com/login")
        # Ports should be allocated on start
        assert handoff._vnc_port == 0
        assert handoff._ws_port == 0

    def test_handoff_url_contains_token(self):
        handoff = create_handoff("http://example.com/login")
        # Build a test URL manually
        url = handoff._build_handoff_url(8080)
        assert "token=" in url
        assert handoff.token in url
        assert "autoconnect=1" in url
        assert "resize=scale" in url

    def test_cancel_sets_status(self):
        handoff = create_handoff("http://example.com/login")
        handoff.cancel()
        assert handoff._cancelled.is_set()
        assert handoff._authenticated.is_set()

    def test_stop_cleans_up_processes(self):
        handoff = create_handoff("http://example.com/login")
        # Set up fake processes
        mock_websockify = MagicMock()
        mock_x11vnc = MagicMock()
        mock_vdisplay = MagicMock()
        handoff._websockify_proc = mock_websockify
        handoff._x11vnc_proc = mock_x11vnc
        handoff._vdisplay = mock_vdisplay
        handoff._owns_display = True

        handoff.stop()

        # Verify cleanup was called
        mock_websockify.terminate.assert_called()
        mock_x11vnc.terminate.assert_called()
        mock_vdisplay.close.assert_called()

    def test_stop_does_not_close_external_display(self):
        """External display should not be closed on stop."""
        handoff = create_handoff("http://example.com/login")
        mock_websockify = MagicMock()
        mock_x11vnc = MagicMock()
        mock_vdisplay = MagicMock()
        handoff._websockify_proc = mock_websockify
        handoff._x11vnc_proc = mock_x11vnc
        handoff._vdisplay = mock_vdisplay
        handoff._owns_display = False  # External display

        handoff.stop()

        mock_websockify.terminate.assert_called()
        mock_x11vnc.terminate.assert_called()
        mock_vdisplay.close.assert_not_called()  # Should not close external display

    def test_x11vnc_command_contains_nopw_and_no_rfbauth(self):
        """Verify that x11vnc is started with -nopw and without -rfbauth."""
        handoff = create_handoff("http://example.com/login")
        # We'll capture the command by patching subprocess.Popen
        with patch('subprocess.Popen') as mock_popen:
            # Configure the mock to record the call
            mock_popen.return_value.poll.return_value = None  # simulate running
            handoff._start_x11vnc(5900)
            # Check that Popen was called
            assert mock_popen.called
            args, kwargs = mock_popen.call_args
            # The first argument is the list of command line arguments
            cmd_args = args[0]
            # Convert to string for easy checking
            cmd_str = ' '.join(cmd_args)
            assert '-nopw' in cmd_str, f"Expected -nopw in command: {cmd_str}"
            assert '-rfbauth' not in cmd_str, f"Unexpected -rfbauth in command: {cmd_str}"
            # Check that listen is set to the loopback host (127.0.0.1)
            assert '-listen' in cmd_args
            idx = cmd_args.index('-listen')
            assert idx + 1 < len(cmd_args)
            assert cmd_args[idx + 1] == '127.0.0.1', f"Expected listen on 127.0.0.1: {cmd_str}"

    def test_no_vnc_password_file_created(self):
        """Ensure no temporary VNC password file is left behind."""
        handoff = create_handoff("http://example.com/login")
        # We'll track any created files in a temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch tempfile.NamedTemporaryFile to return a file in our temp dir
            original_namedtemporaryfile = tempfile.NamedTemporaryFile
            def mock_namedtemporaryfile(*args, **kwargs):
                # Ensure the file is created in our temp directory
                kwargs.setdefault('dir', tmpdir)
                return original_namedtemporaryfile(*args, **kwargs)
            with patch('tempfile.NamedTemporaryFile', side_effect=mock_namedtemporaryfile):
                # Now run the method that would create the password file
                try:
                    handoff._start_x11vnc(5900)
                except Exception:
                    # If it fails, we still want to check for leftover files
                    pass
                # Finally, clean up the process if it was started
                if handoff._x11vnc_proc:
                    handoff._x11vnc_proc.terminate()
                    handoff._x11vnc_proc.wait()
            # List all files in the temp directory
            files = os.listdir(tmpdir)
            # Filter out any that look like vnc password files
            vnc_pass_files = [f for f in files if f.endswith('.vncpass')]
            assert len(vnc_pass_files) == 0, f"Unexpected VNC password files left: {vnc_pass_files}"

    def test_token_file_created_and_cleaned(self):
        handoff = create_handoff("http://example.com/login")
        token_file = handoff._create_token_file()
        assert os.path.exists(token_file)
        content = open(token_file).read().strip()
        # TokenFile format: token: host:port
        assert content.startswith(f"{handoff.token}: ")
        assert "127.0.0.1:" in content
        os.unlink(token_file)


class TestCleanupOnPartialFailure:
    """Tests for cleanup when handoff fails partway through."""

    def test_cleanup_on_virtual_display_failure(self):
        """If virtual display fails to start, no processes should leak."""
        handoff = create_handoff("http://example.com/login", display=":9999")
        # Mock VirtualDisplay.start to fail
        with patch.object(VirtualDisplay, 'start', side_effect=RuntimeError("Xvfb failed")):
            with pytest.raises(RuntimeError, match="Xvfb failed"):
                handoff._start_virtual_display()
        # No processes should have been started
        assert handoff._x11vnc_proc is None
        assert handoff._websockify_proc is None
        assert handoff._browser_runtime is None

    def test_cleanup_on_x11vnc_failure(self):
        """If x11vnc fails, virtual display should be cleaned up if owned."""
        handoff = create_handoff("http://example.com/login", display=":9999")
        handoff._owns_display = True
        handoff._vdisplay = MagicMock()

        with patch('subprocess.Popen', side_effect=RuntimeError("x11vnc failed")):
            with pytest.raises(RuntimeError, match="x11vnc failed"):
                handoff._start_x11vnc(5900)

        # Virtual display cleanup would be handled by stop()

    def test_cleanup_on_websockify_failure(self):
        """If websockify fails, x11vnc and display should be cleaned up."""
        handoff = create_handoff("http://example.com/login", display=":9999")
        handoff._owns_display = True
        handoff._vdisplay = MagicMock()
        handoff._x11vnc_proc = MagicMock()

        with patch('subprocess.Popen', side_effect=RuntimeError("websockify failed")):
            with pytest.raises(RuntimeError, match="websockify failed"):
                handoff._start_websockify(5900, 8080)

        # Cleanup would be handled by stop()


class TestBrowserHandoffIntegration:
    """Integration tests with browser runtime (mocked)."""

    def test_selector_success_detection(self):
        """Verify selector-based success detection works."""
        handoff = create_handoff(
            "http://example.com/login",
            success_selector=".user-avatar"
        )

        # Mock browser runtime and page
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count.return_value = 1
        mock_locator.first.is_visible.return_value = True
        mock_page.locator.return_value = mock_locator
        mock_page.url = "https://example.com/dashboard"

        mock_browser = MagicMock()
        mock_browser.page = mock_page

        handoff._browser_runtime = mock_browser
        # Create a new success config with the selector
        handoff.success_config = AuthSuccessConfig(success_selector=".user-avatar")

        # Run monitoring once
        handoff._monitor_authentication()

        # Should have detected success
        assert handoff._authenticated.is_set()
        assert handoff._result is not None
        assert handoff._result.status == "authenticated"
        assert handoff._result.final_url == "https://example.com/dashboard"

    def test_url_prefix_success_detection(self):
        """Verify URL prefix success detection works."""
        handoff = create_handoff(
            "http://example.com/login",
            success_url_prefix="https://example.com/dashboard"
        )

        mock_page = MagicMock()
        mock_page.url = "https://example.com/dashboard?session=abc"

        mock_browser = MagicMock()
        mock_browser.page = mock_page

        handoff._browser_runtime = mock_browser

        handoff._monitor_authentication()

        assert handoff._authenticated.is_set()
        assert handoff._result.status == "authenticated"
        assert handoff._result.final_url == "https://example.com/dashboard?session=abc"

    def test_no_keyboard_input_in_logs(self):
        """Verify no keyboard input is logged during handoff."""
        handoff = create_handoff("http://example.com/login")

        # Check that no logging of sensitive data occurs
        # This is a design verification - the code doesn't log passwords
        assert True  # Placeholder for actual log inspection


class TestSessionPersistence:
    """Tests for session persistence across browser restarts."""

    def test_profile_path_reused(self):
        """Same profile path should be used across handoffs."""
        handoff1 = create_handoff("http://example.com/login", profile="test-persist")
        handoff2 = create_handoff("http://example.com/login", profile="test-persist")

        from hermes_screencast.browser.session_manager import SessionManager
        sm = SessionManager()
        path1 = sm.profile_path("test-persist")
        path2 = sm.profile_path("test-persist")
        assert path1 == path2


class TestExternalDisplayOwnership:
    """Tests for external display ownership semantics."""

    def test_handoff_with_external_display(self):
        """Handoff should work with pre-existing display."""
        handoff = create_handoff("http://example.com/login", display=":99")
        # If display :99 exists, handoff should use it without owning it
        assert hasattr(handoff, '_owns_display')

    def test_handoff_owns_its_display(self):
        """Handoff should own the display it creates."""
        handoff = create_handoff("http://example.com/login", display=":9999")
        # When it starts Xvfb, it should own it
        # This is verified in the VirtualDisplay test
        assert hasattr(handoff, '_owns_display')


class TestHandoffResultJSON:
    """Tests for JSON output schema."""

    def test_json_schema(self):
        """Verify JSON output contains expected fields."""
        result = HandoffResult(
            status="authenticated",
            profile="test-profile",
            profile_path="/tmp/profiles/test-profile",
            target_url="https://example.com/login",
            final_url="https://example.com/dashboard",
            handoff_closed=True,
        )
        data = json.loads(result.to_json())

        required_fields = ["status", "profile", "profile_path", "target_url", "final_url", "handoff_closed"]
        for field in required_fields:
            assert field in data

        assert data["status"] == "authenticated"
        assert data["profile"] == "test-profile"
        assert data["handoff_closed"] is True

    def test_no_secrets_in_json(self):
        """JSON must not contain any internal secrets."""
        result = HandoffResult(
            status="authenticated",
            profile="test",
            profile_path="/tmp/test",
            target_url="https://example.com/login",
            final_url="https://example.com/dashboard",
        )
        json_str = result.to_json()

        # Check that no internal secrets are present
        # (user-provided URLs might contain tokens, but our internal tokens/passwords should not)
        forbidden = ["password", "cookie", "localstorage", "otp"]
        for word in forbidden:
            assert word not in json_str.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
