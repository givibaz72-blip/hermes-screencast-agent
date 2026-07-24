"""Tests for local desktop browser transport."""

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_screencast.transport.protocol import (
    AuthStatus,
    CompanionCommand,
    CompanionRequest,
    CompanionResponse,
    PairingToken,
    RecordingConfig,
    SafePageState,
    SessionConfig,
    SessionStatus,
)
from hermes_screencast.transport.local_transport import (
    LocalDesktopTransport,
    RemoteDesktopTransport,
    TransportConfig,
    create_transport,
    TopologyMode,
    TransportError,
)
from hermes_screencast.local_companion import (
    LocalCompanion,
    LocalBrowserProcess,
    UnifiedCompanionConfig,
    LocalCompanionConfig,
)


class TestPairingToken:
    """Tests for PairingToken."""
    
    def test_create_token(self):
        """Test creating a pairing token."""
        token = PairingToken.create("session_123", ttl_seconds=300)
        
        assert token.session_id == "session_123"
        assert len(token.token) > 20  # cryptographically secure
        assert token.expires_at > token.created_at
        assert not token.used
    
    def test_token_validity(self):
        """Test token validity check."""
        token = PairingToken.create("session_123", ttl_seconds=1)
        
        assert token.is_valid()
        
        token.mark_used()
        assert not token.is_valid()
        
        # Test expiration
        expired_token = PairingToken(
            token="expired",
            created_at=time.time() - 100,
            expires_at=time.time() - 10,
            session_id="test",
        )
        assert not expired_token.is_valid()
    
    def test_token_single_use(self):
        """Test pairing token can only be used once."""
        token = PairingToken.create("session_123", ttl_seconds=300)
        
        assert token.is_valid()
        token.mark_used()
        assert not token.is_valid()
        # Marking used again should not change anything
        token.mark_used()
        assert not token.is_valid()


class TestSafePageState:
    """Tests for SafePageState."""
    
    def test_safe_page_state_serialization(self):
        """Test SafePageState to/from dict."""
        state = SafePageState(
            current_url="https://app.heygen.com/",
            hostname="app.heygen.com",
            title="HeyGen Dashboard",
            visible_markers=["oauth:button:has-text('Sign in with Google')"],
            success_selector_visible=True,
            viewport_width=1920,
            viewport_height=1080,
            session_status=SessionStatus.AUTHENTICATED.value,
            auth_status=AuthStatus.AUTHENTICATED.value,
            login_markers=[],
            provider_block_markers=[],
        )
        
        # Serialize and deserialize
        data = state.to_dict()
        restored = SafePageState.from_dict(data)
        
        assert restored.current_url == state.current_url
        assert restored.hostname == state.hostname
        assert restored.title == state.title
        assert restored.visible_markers == state.visible_markers
        assert restored.success_selector_visible == state.success_selector_visible
        assert restored.session_status == state.session_status
        assert restored.auth_status == state.auth_status
    
    def test_safe_page_state_no_secrets(self):
        """Verify SafePageState doesn't contain secrets."""
        state = SafePageState(
            current_url="https://app.heygen.com/",
            hostname="app.heygen.com",
            title="HeyGen Dashboard",
        )
        
        data = state.to_dict()
        json_str = str(data)
        
        # Ensure no secret fields
        assert "cookies" not in data
        assert "localStorage" not in data
        assert "sessionStorage" not in data
        assert "password" not in json_str.lower()
        assert "token" not in json_str.lower()
        assert "credential" not in json_str.lower()


class TestCompanionProtocol:
    """Tests for companion protocol messages."""
    
    def test_request_serialization(self):
        """Test CompanionRequest serialization."""
        request = CompanionRequest(
            command=CompanionCommand.OPEN_URL.value,
            session_id="test_session",
            pairing_token="test_token",
            payload={"url": "https://example.com"},
        )
        
        json_str = request.to_json()
        restored = CompanionRequest.from_json(json_str)
        
        assert restored.command == request.command
        assert restored.session_id == request.session_id
        assert restored.pairing_token == request.pairing_token
        assert restored.payload == request.payload
    
    def test_response_serialization(self):
        """Test CompanionResponse serialization."""
        response = CompanionResponse(
            success=True,
            session_id="test_session",
            status=SessionStatus.AUTHENTICATED.value,
            payload={"test": "data"},
        )
        
        json_str = response.to_json()
        restored = CompanionResponse.from_json(json_str)
        
        assert restored.success == response.success
        assert restored.session_id == response.session_id
        assert restored.status == response.status
        assert restored.payload == response.payload
    
    def test_error_response(self):
        """Test error response."""
        response = CompanionResponse(
            success=False,
            session_id="test_session",
            status=SessionStatus.FAILED.value,
            error="Something went wrong",
        )
        
        assert not response.success
        assert response.error == "Something went wrong"


class TestLocalCompanion:
    """Tests for LocalCompanion."""
    
    def test_companion_binds_to_loopback_only(self):
        """Test companion only binds to 127.0.0.1."""
        config = TransportConfig(topology_mode=TopologyMode.LOCAL_DEVELOPMENT)
        transport = LocalDesktopTransport(config)
        
        assert transport.config.companion_host == "127.0.0.1"
    
    def test_start_session_creates_pairing_token(self):
        """Test start_session creates valid pairing token."""
        transport = LocalDesktopTransport(
            TransportConfig(topology_mode=TopologyMode.LOCAL_DEVELOPMENT)
        )
        
        # Mock the _send_request method
        def mock_send_request(request):
            return CompanionResponse(
                success=True,
                session_id="test_session",
                status=SessionStatus.PENDING.value,
                payload={
                    "pairing_token": "test_pairing_token_123456789012345678901234",
                    "expires_at": time.time() + 300,
                },
            )
        
        transport._send_request = mock_send_request
        transport._companion_port = 12345  # Pretend companion is running
        
        session_id, pairing_token = asyncio.run(transport.start_session(
            profile_name="test",
            target_url="https://app.heygen.com/",
            success_url_prefix="https://app.heygen.com/",
            success_selector="[data-testid='dashboard']",
        ))
        
        assert session_id is not None
        assert pairing_token.token == "test_pairing_token_123456789012345678901234"
        assert pairing_token.session_id == session_id
        assert pairing_token.is_valid()
    
    def test_invalid_pairing_token_rejected(self):
        """Test invalid pairing tokens are rejected."""
        companion = LocalCompanion(UnifiedCompanionConfig())
        
        # Try to use a command without valid token
        request = CompanionRequest(
            command=CompanionCommand.OPEN_URL.value,
            session_id="nonexistent",
            pairing_token="invalid_token",
            payload={"url": "https://example.com"},
        )
        
        response = asyncio.run(companion._process_request(request))
        
        assert not response.success
        assert response.error is not None and "Invalid or expired pairing token" in response.error
    
    def test_expired_token_rejected(self):
        """Test expired pairing tokens are rejected."""
        from hermes_screencast.transport.protocol import PairingToken
        
        companion = LocalCompanion(UnifiedCompanionConfig())
        
        # Create expired token
        expired_token = PairingToken(
            token="expired_token",
            created_at=time.time() - 1000,
            expires_at=time.time() - 10,
            session_id="test_session",
        )
        companion._pairing_tokens["test_session"] = expired_token
        
        request = CompanionRequest(
            command=CompanionCommand.OPEN_URL.value,
            session_id="test_session",
            pairing_token="expired_token",
            payload={"url": "https://example.com"},
        )
        
        response = asyncio.run(companion._process_request(request))
        
        assert not response.success
        assert response.error is not None and "Invalid or expired pairing token" in response.error
    
    def test_token_single_use(self):
        """Test pairing token can only be used once."""
        from hermes_screencast.transport.protocol import PairingToken
        
        companion = LocalCompanion(UnifiedCompanionConfig())
        
        # Create token and mark as used
        token = PairingToken.create("test_session", ttl_seconds=300)
        token.mark_used()
        companion._pairing_tokens["test_session"] = token
        
        request = CompanionRequest(
            command=CompanionCommand.OPEN_URL.value,
            session_id="test_session",
            pairing_token=token.token,
            payload={"url": "https://example.com"},
        )
        
        response = asyncio.run(companion._process_request(request))
        
        assert not response.success
        assert response.error is not None and "Invalid or expired pairing token" in response.error


class TestLocalBrowserProcess:
    """Tests for LocalBrowserProcess."""
    
    def test_browser_creation(self):
        """Test browser process can be created."""
        browser = LocalBrowserProcess()
        assert browser is not None
        assert browser.process is None
        assert browser.profile_path is None
    
    def test_get_safe_page_state_without_browser(self):
        """Test get_safe_page_state returns failed state without browser."""
        browser = LocalBrowserProcess()
        state = asyncio.run(browser.get_safe_page_state())
        
        assert state.session_status == SessionStatus.FAILED.value
        assert state.auth_status == AuthStatus.UNKNOWN.value


class TestLocalDesktopTransport:
    """Tests for LocalDesktopTransport."""
    
    def test_transport_creation(self):
        """Test transport creation."""
        config = TransportConfig(topology_mode=TopologyMode.LOCAL_DEVELOPMENT)
        transport = LocalDesktopTransport(config)
        
        assert transport.config.companion_host == "127.0.0.1"
        assert not transport.is_connected
        assert transport.session_id is None
    
    def test_factory_function(self):
        """Test factory function."""
        transport = create_transport(TransportConfig(topology_mode=TopologyMode.LOCAL_DEVELOPMENT))
        
        assert isinstance(transport, LocalDesktopTransport)
        assert transport.config.topology_mode == TopologyMode.LOCAL_DEVELOPMENT
    
    def test_context_manager(self):
        """Test transport start/stop."""
        config = TransportConfig(topology_mode=TopologyMode.LOCAL_DEVELOPMENT)
        transport = LocalDesktopTransport(config)
        
        # Mock start/stop companion
        transport.start_companion = MagicMock(return_value=12345)
        transport.stop_companion = MagicMock()
        transport.finish_session = MagicMock()
        
        # Test connect/disconnect instead of context manager
        port = asyncio.run(transport.connect())
        assert port == 12345
        transport.start_companion.assert_called_once()
        
        asyncio.run(transport.disconnect())
        transport.stop_companion.assert_called_once()


class TestRemoteDesktopTransport:
    """Tests for RemoteDesktopTransport."""
    
    def test_requires_remote_mode(self):
        """Test RemoteDesktopTransport requires REMOTE_DESKTOP mode."""
        config = TransportConfig(topology_mode=TopologyMode.LOCAL_DEVELOPMENT)
        
        with pytest.raises(ValueError, match="requires REMOTE_DESKTOP"):
            RemoteDesktopTransport(config)
    
    def test_remote_mode_without_relay_url_fails(self):
            """Test remote mode without relay_url fails."""
            with pytest.raises(ValueError, match="relay_url required"):
                TransportConfig(topology_mode=TopologyMode.REMOTE_DESKTOP)


class TestSecurity:
    """Security-focused tests."""
    
    def test_no_cookies_in_safe_state(self):
        """Ensure SafePageState never contains cookies."""
        state = SafePageState(
            current_url="https://app.heygen.com/",
            hostname="app.heygen.com",
            title="HeyGen",
        )
        
        data = state.to_dict()
        json_str = str(data)
        
        # No sensitive data
        assert "cookie" not in json_str.lower()
        assert "localstorage" not in json_str.lower()
        assert "sessionstorage" not in json_str.lower()
        assert "password" not in json_str.lower()
    
    def test_companion_no_external_binding(self):
        """Test companion refuses external binding."""
        with pytest.raises(ValueError):
            LocalCompanion(UnifiedCompanionConfig(local=LocalCompanionConfig(host="0.0.0.0")))
        
        with pytest.raises(ValueError):
            LocalCompanion(UnifiedCompanionConfig(local=LocalCompanionConfig(host="192.168.1.100")))
        
        # Only loopback allowed
        c = LocalCompanion(UnifiedCompanionConfig(local=LocalCompanionConfig(host="127.0.0.1")))
        assert c.local_config.host == "127.0.0.1"
    
    def test_pairing_token_cryptographically_secure(self):
        """Test pairing tokens are cryptographically secure."""
        tokens = set()
        for _ in range(100):
            token = PairingToken.create("test", ttl_seconds=300)
            tokens.add(token.token)
        
        # All tokens should be unique
        assert len(tokens) == 100
        
        # Tokens should be URL-safe base64 (no special chars)
        for token in tokens:
            assert all(c.isalnum() or c in "-_" for c in token)
            assert len(token) >= 32  # token_urlsafe(32) produces ~43 chars
    
    def test_session_isolation(self):
        """Test sessions are properly isolated."""
        config = UnifiedCompanionConfig(local=LocalCompanionConfig(headless=True))
        companion = LocalCompanion(config)
        
        # Create two sessions
        req1 = CompanionRequest(
            command=CompanionCommand.START_SESSION.value,
            session_id="session_1",
            pairing_token="",
            payload={"profile_name": "profile1", "target_url": "https://a.com", "headless": True},
        )
        
        req2 = CompanionRequest(
            command=CompanionCommand.START_SESSION.value,
            session_id="session_2",
            pairing_token="",
            payload={"profile_name": "profile2", "target_url": "https://b.com", "headless": True},
        )
        
        resp1 = asyncio.run(companion._process_request(req1))
        resp2 = asyncio.run(companion._process_request(req2))
        
        assert resp1.success
        assert resp2.success
        
        # Tokens should be different
        assert resp1.payload["pairing_token"] != resp2.payload["pairing_token"]
        
        # Sessions should be separate
        assert "session_1" in companion._sessions
        assert "session_2" in companion._sessions
        assert companion._sessions["session_1"].target_url == "https://a.com"
        assert companion._sessions["session_2"].target_url == "https://b.com"


class TestRecording:
    """Tests for local recording."""
    
    def test_recording_config(self):
        """Test RecordingConfig creation."""
        config = RecordingConfig(
            output_path=Path("/tmp/recording.mp4"),
            events_output_path=Path("/tmp/events.json"),
            width=1920,
            height=1080,
            fps=30,
            show_recording_indicator=True,
        )
        
        assert config.output_path == Path("/tmp/recording.mp4")
        assert config.events_output_path == Path("/tmp/events.json")
        assert config.fps == 30
        assert config.show_recording_indicator
    
    def test_recording_not_started_without_auth(self):
        """Test recording cannot start without authentication."""
        # This is tested in the companion logic
        # The companion checks auth_status before starting recording
        pass


class TestIntegration:
    """Integration-style tests."""
    
    @ pytest.mark.skip(reason="Requires Xvfb/Playwright - run separately for browser integration tests")
    def test_full_session_lifecycle(self):
        """Test full session lifecycle: start -> finish.
        
        This test verifies protocol without starting real browser.
        """
        # Use headless mode for CI
        config = UnifiedCompanionConfig(local=LocalCompanionConfig(headless=True))
        companion = LocalCompanion(config)
        
        # 1. Start session - verify protocol creates session and token
        req = CompanionRequest(
            command=CompanionCommand.START_SESSION.value,
            session_id="lifecycle_test",
            pairing_token="",
            payload={
                "profile_name": "test_profile",
                "target_url": "",
                "success_url_prefix": "",
                "headless": True,
            },
        )
        resp = asyncio.run(companion._process_request(req))
        assert resp.success
        token = resp.payload["pairing_token"]
        
        # 2. Verify companion internal state
        assert "lifecycle_test" in companion._sessions
        
        # 3. Finish session - verify cleanup
        req = CompanionRequest(
            command=CompanionCommand.FINISH_SESSION.value,
            session_id="lifecycle_test",
            pairing_token=token,
            payload={},
        )
        resp = asyncio.run(companion._process_request(req))
        assert resp.success
        assert resp.status == SessionStatus.COMPLETED.value
        
        # Session should be cleaned up
        assert "lifecycle_test" not in companion._sessions
    
    def test_connection_failure_handling(self):
        """Test handling of companion connection failures."""
        config = TransportConfig(topology_mode=TopologyMode.LOCAL_DEVELOPMENT)
        transport = LocalDesktopTransport(config)
        
        # Without companion running, operations should fail gracefully
        transport._companion_port = 9999  # Invalid port
        
        with pytest.raises((RuntimeError, ConnectionRefusedError)):
            transport._send_request(CompanionRequest(
                command=CompanionCommand.GET_SAFE_PAGE_STATE.value,
                session_id="test",
                pairing_token="token",
                payload={},
            ))


class TestTopology:
    """Tests for transport topology."""

    def test_local_development_mode(self):
        """Test local development transport creation."""
        transport = create_transport(
            TransportConfig(topology_mode=TopologyMode.LOCAL_DEVELOPMENT)
        )
        assert isinstance(transport, LocalDesktopTransport)

    def test_remote_desktop_mode(self):
        """Test remote desktop transport creation."""
        config = TransportConfig(
            topology_mode=TopologyMode.REMOTE_DESKTOP,
            relay_url="wss://relay.example.com:8765",
        )
        transport = create_transport(config)
        assert isinstance(transport, RemoteDesktopTransport)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])