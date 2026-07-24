from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlsplit, urlunsplit

from ..transport.protocol import (
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

logger = logging.getLogger(__name__)


class TopologyMode(str, Enum):
    """Transport topology modes."""
    LOCAL_DEVELOPMENT = "local_development"  # Companion on same machine as backend
    REMOTE_DESKTOP = "remote_desktop"  # Companion on Windows/Desktop, connects via relay


class TransportError(Exception):
    """Transport-related errors."""
    pass


@dataclass
class TransportConfig:
    """Configuration for transport."""
    topology_mode: TopologyMode = TopologyMode.LOCAL_DEVELOPMENT

    # Local development mode
    companion_host: str = "127.0.0.1"
    companion_port: int = 0
    companion_executable: str = ""
    companion_module: str = "hermes_screencast.local_companion.cli"
    pairing_ttl_seconds: float = 300
    connection_timeout: float = 10.0
    request_timeout: float = 30.0

    # Remote desktop mode - full relay URL
    relay_url: str = ""
    allow_insecure_local_test: bool = False

    def __post_init__(self):
        """Parse and validate relay URL."""
        if self.topology_mode == TopologyMode.REMOTE_DESKTOP:
            if not self.relay_url:
                raise ValueError("relay_url required for REMOTE_DESKTOP mode")
            self._parse_relay_url()

    def _parse_relay_url(self) -> None:
        """Parse and validate relay URL using urllib.parse."""
        if not self.relay_url:
            raise ValueError("relay_url required for REMOTE_DESKTOP mode")

        parsed = urlsplit(self.relay_url)

        # Validate scheme
        if parsed.scheme not in ("ws", "wss"):
            raise ValueError(f"Unsupported scheme: {parsed.scheme}. Use ws:// or wss://")

        # Validate no userinfo
        if parsed.username or parsed.password:
            raise ValueError("URL must not contain userinfo (username:password)")

        # Validate no fragment
        if parsed.fragment:
            raise ValueError("URL must not contain fragment")

        # Validate hostname
        if not parsed.hostname:
            raise ValueError("URL must contain a hostname")

        # Check for IPv6 loopback
        is_ipv6_loopback = parsed.hostname in ("::1", "ip6-loopback")

        # Check for IPv4 loopback
        is_ipv4_loopback = parsed.hostname in ("127.0.0.1", "localhost", "localhost.localdomain")

        is_loopback = is_ipv4_loopback or is_ipv6_loopback

        # Validate scheme matches allow_insecure_local_test
        if parsed.scheme == "ws":
            if not self.allow_insecure_local_test:
                raise ValueError("ws:// requires --allow-insecure-local-test (only for loopback testing)")
            if not is_loopback:
                raise ValueError("ws:// only allowed for loopback addresses (127.0.0.1, ::1, localhost)")
        elif parsed.scheme == "wss":
            # wss is always allowed
            pass

        # Reconstruct URL to ensure consistency (handles default ports, etc.)
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "wss" else 80

        # Rebuild URL with normalized components
        netloc = f"{parsed.hostname}:{port}"
        self.relay_url = urlunsplit((
            parsed.scheme,
            netloc,
            parsed.path or "/",
            parsed.query,
            ""  # no fragment
        ))


class BaseTransport:
    """Abstract base transport."""

    def __init__(self, config: TransportConfig):
        self.config = config
        self._session_id: Optional[str] = None
        self._pairing_token: Optional[PairingToken] = None
        self._session_config: Optional[SessionConfig] = None
        self._connected = False

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def pairing_token(self) -> Optional[PairingToken]:
        return self._pairing_token

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> int:
        raise NotImplementedError

    async def disconnect(self) -> None:
        raise NotImplementedError

    async def start_session(
        self,
        profile_name: str = "default",
        profile_path: Optional[Path] = None,
        target_url: str = "",
        success_url_prefix: str = "",
        success_selector: str = "",
        width: int = 1920,
        height: int = 1080,
        headless: bool = False,
        chrome_path: Optional[str] = None,
        chrome_args: Optional[list[str]] = None,
        browser_startup: str = "playwright",
        auth_wait_seconds: int = 300,
    ) -> tuple[str, PairingToken]:
        raise NotImplementedError

    async def open_url(self, session_id: str, url: str) -> CompanionResponse:
        raise NotImplementedError

    async def get_safe_page_state(self, session_id: str) -> SafePageState:
        raise NotImplementedError

    async def confirm_authentication(self, session_id: str) -> tuple[bool, SafePageState]:
        raise NotImplementedError

    async def start_recording(
        self,
        session_id: str,
        output_path: Path,
        events_output_path: Optional[Path] = None,
        fps: int = 30,
        show_recording_indicator: bool = True,
    ) -> CompanionResponse:
        raise NotImplementedError

    async def stop_recording(self, session_id: str) -> CompanionResponse:
        raise NotImplementedError

    async def finish_session(self, session_id: str) -> CompanionResponse:
        raise NotImplementedError


class LocalDesktopTransport(BaseTransport):
    """Transport for local development - companion runs on same machine."""

    def __init__(self, config: Optional[TransportConfig] = None):
        config = config or TransportConfig(topology_mode=TopologyMode.LOCAL_DEVELOPMENT)
        if config.topology_mode != TopologyMode.LOCAL_DEVELOPMENT:
            raise ValueError("LocalDesktopTransport requires LOCAL_DEVELOPMENT topology mode")
        super().__init__(config)

        self._companion_process: Optional[subprocess.Popen] = None
        self._companion_port: int = 0

    def start_companion(self) -> int:
        """Start the local companion process. Returns the port it's listening on.

        Uses the canonical CLI entry point (hermes_screencast.local_companion.cli)
        with named arguments. Detects readiness via COMPANION_PORT marker using
        a daemon reader thread for Windows-safe non-blocking stdout reading.
        If child exits before marker, returns RuntimeError with stderr and exit code.
        """
        if self._companion_process and self._companion_process.poll() is None:
            logger.warning("Companion already running")
            return self._companion_port

        # Use sys.executable by default, fall back to config value
        executable = self.config.companion_executable or sys.executable

        # Build array-based command with named arguments
        cmd = [
            executable,
            "-m", self.config.companion_module,
            "--host", "127.0.0.1",
            "--port", str(self.config.companion_port),
        ]

        logger.info(f"Starting local companion: {executable} -m {self.config.companion_module}")

        self._companion_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        # Wait for companion to announce its port using daemon reader thread
        port = self._wait_for_companion_port(self._companion_process,
                                              self.config.connection_timeout)
        if port is not None:
            self._companion_port = port
            logger.info(f"Local companion started on port {self._companion_port}")
            return self._companion_port

        raise RuntimeError("Companion failed to start within timeout")

    def _wait_for_companion_port(
        self,
        process: subprocess.Popen,
        timeout: float,
    ) -> Optional[int]:
        """Wait for COMPANION_PORT marker using daemon reader thread.

        Uses a daemon thread + queue.Queue for non-blocking stdout reading.
        Regularly checks process.poll() to detect early exit.
        """
        result_queue: queue.Queue = queue.Queue()
        stderr_lines: list[str] = []

        def reader_thread(proc: subprocess.Popen, q: queue.Queue) -> None:
            """Read stdout lines from companion process."""
            try:
                for raw_line in proc.stdout or []:
                    line = raw_line.rstrip("\r\n")
                    if line.startswith("COMPANION_PORT:"):
                        try:
                            port = int(line.split(":", 1)[1].strip())
                            q.put(("port", port))
                            return
                        except (ValueError, IndexError):
                            q.put(("error", f"Invalid COMPANION_PORT line: {line}"))
                            return
                    # Log other lines but don't queue them
                    logger.debug(f"Companion stdout: {line}")
                # EOF reached without finding marker
                q.put(("eof", None))
            except Exception as e:
                q.put(("error", str(e)))

        thread = threading.Thread(target=reader_thread, args=(process, result_queue), daemon=True)
        thread.start()

        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check if child exited
            rc = process.poll()
            if rc is not None:
                # Read limited stderr
                try:
                    if process.stderr:
                        stderr_data = process.stderr.read()
                        if isinstance(stderr_data, str):
                            stderr_lines = stderr_data.split('\n')[:50]
                except Exception:
                    pass
                error_msg = (
                    f"Companion process exited before readiness:\n"
                    f"  return_code={rc}\n"
                    f"  stderr={chr(10).join(stderr_lines[-5:]) if stderr_lines else 'none'}"
                )
                raise RuntimeError(error_msg)

            # Check queue non-blocking
            try:
                result = result_queue.get_nowait()
                if result[0] == "port":
                    return result[1]
                elif result[0] == "error":
                    raise RuntimeError(f"Companion stdout error: {result[1]}")
                elif result[0] == "eof":
                    # stdout ended without marker
                    pass
            except queue.Empty:
                pass

            time.sleep(0.05)

        # Timeout reached
        raise RuntimeError(
            f"Companion readiness timeout after {timeout} seconds"
        )

    def stop_companion(self) -> None:
        """Stop the local companion process."""
        if self._companion_process:
            try:
                self._companion_process.terminate()
                self._companion_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._companion_process.kill()
                self._companion_process.wait()
            self._companion_process = None
            self._companion_port = 0

    def _send_request(self, request: CompanionRequest) -> CompanionResponse:
        """Send request to companion and get response."""
        if self._companion_port == 0:
            raise RuntimeError("Companion not started")

        # Create socket connection
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.config.request_timeout)

        try:
            sock.connect((self.config.companion_host, self._companion_port))
            sock.sendall(request.to_json().encode())

            # Read response
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                # Check if we have complete JSON
                try:
                    json.loads(data.decode())
                    break
                except json.JSONDecodeError:
                    continue

            return CompanionResponse.from_json(data.decode())
        finally:
            sock.close()

    async def connect(self) -> int:
        """Connect to local companion (async)."""
        loop = asyncio.get_event_loop()
        port = await loop.run_in_executor(None, self.start_companion)
        self._connected = True
        return port

    async def disconnect(self) -> None:
        """Disconnect from companion."""
        loop = asyncio.get_event_loop()
        if self._session_id:
            try:
                await loop.run_in_executor(None, self.finish_session, self._session_id)
            except Exception:
                pass
        await loop.run_in_executor(None, self.stop_companion)
        self._connected = False

    async def start_session(
        self,
        profile_name: str = "default",
        profile_path: Optional[Path] = None,
        target_url: str = "",
        success_url_prefix: str = "",
        success_selector: str = "",
        width: int = 1920,
        height: int = 1080,
        headless: bool = False,
        chrome_path: Optional[str] = None,
        chrome_args: Optional[list[str]] = None,
        browser_startup: str = "playwright",
        auth_wait_seconds: int = 300,
        cdp_endpoint: Optional[str] = None,
        cdp_host: str = "127.0.0.1",
        cdp_port: int = 9222,
    ) -> tuple[str, PairingToken]:
        """Start a new session with the local companion."""
        import secrets
        import tempfile

        # Generate session ID
        self._session_id = secrets.token_urlsafe(16)

        # Prepare payload
        payload = {
            "profile_name": profile_name,
            "profile_path": str(profile_path) if profile_path else tempfile.gettempdir(),
            "target_url": target_url,
            "success_url_prefix": success_url_prefix,
            "success_selector": success_selector,
            "width": width,
            "height": height,
            "headless": headless,
            "chrome_path": chrome_path,
            "chrome_args": chrome_args or [],
            "browser_startup": browser_startup,
            "auth_wait_seconds": auth_wait_seconds,
            "cdp_endpoint": cdp_endpoint,
            "cdp_host": cdp_host,
            "cdp_port": cdp_port,
        }

        request = CompanionRequest(
            command=CompanionCommand.START_SESSION.value,
            session_id=self._session_id,
            pairing_token="",  # Not needed for start_session
            payload=payload,
        )

        response = self._send_request(request)

        if not response.success:
            raise RuntimeError(f"Failed to start session: {response.error}")

        # Create pairing token from response
        self._pairing_token = PairingToken(
            token=response.payload["pairing_token"],
            created_at=time.time(),
            expires_at=response.payload["expires_at"],
            session_id=self._session_id,
        )

        # Store session config
        if profile_path is None:
            profile_path = Path(tempfile.gettempdir()) / "hermes_profiles" / profile_name

        self._session_config = SessionConfig(
            session_id=self._session_id,
            profile_name=profile_name,
            profile_path=profile_path,
            target_url=target_url,
            success_url_prefix=success_url_prefix,
            success_selector=success_selector,
            width=width,
            height=height,
            headless=headless,
            chrome_path=chrome_path,
            chrome_args=chrome_args or [],
            browser_startup=browser_startup,
            auth_wait_seconds=auth_wait_seconds,
            cdp_endpoint=cdp_endpoint,
            cdp_host=cdp_host,
            cdp_port=cdp_port,
        )

        self._connected = True
        return self._session_id, self._pairing_token

    async def open_url(self, session_id: str, url: str) -> CompanionResponse:
        """Open a URL in the local browser (async)."""
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.OPEN_URL.value,
            session_id=self._session_id,
            pairing_token=self._pairing_token.token,
            payload={"url": url},
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self._send_request, request)

        if response.success and self._session_config:
            self._session_config.target_url = url

        return response

    async def get_safe_page_state(self, session_id: str) -> SafePageState:
        """Get safe page state from local browser (no secrets) - async."""
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.GET_SAFE_PAGE_STATE.value,
            session_id=self._session_id,
            pairing_token=self._pairing_token.token,
            payload={},
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self._send_request, request)

        if not response.success:
            raise RuntimeError(f"Failed to get page state: {response.error}")

        return SafePageState.from_dict(response.payload)

    async def confirm_authentication(self, session_id: str) -> tuple[bool, SafePageState]:
        """
        Confirm authentication - triggers auth check.

        Returns:
            (authenticated: bool, state: SafePageState)
        """
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.CONFIRM_AUTHENTICATION.value,
            session_id=self._session_id,
            pairing_token=self._pairing_token.token,
            payload={},
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self._send_request, request)

        state = SafePageState.from_dict(response.payload)
        return response.success, state

    async def start_recording(
        self,
        session_id: str,
        output_path: Path,
        events_output_path: Optional[Path] = None,
        fps: int = 30,
        show_recording_indicator: bool = True,
    ) -> CompanionResponse:
        """Start local recording (async)."""
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.START_RECORDING.value,
            session_id=self._session_id,
            pairing_token=self._pairing_token.token,
            payload={
                "output_path": str(output_path),
                "events_output_path": str(events_output_path) if events_output_path else None,
                "fps": fps,
                "show_recording_indicator": show_recording_indicator,
            },
        )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_request, request)

    async def stop_recording(self, session_id: str) -> CompanionResponse:
        """Stop local recording (async)."""
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.STOP_RECORDING.value,
            session_id=self._session_id,
            pairing_token=self._pairing_token.token,
            payload={},
        )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_request, request)

    async def finish_session(self, session_id: str) -> CompanionResponse:
        """Finish session and cleanup (async)."""
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.FINISH_SESSION.value,
            session_id=self._session_id,
            pairing_token=self._pairing_token.token,
            payload={},
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self._send_request, request)

        # Clean up local state
        self._session_id = None
        self._pairing_token = None
        self._session_config = None
        self._connected = False

        return response


@dataclass
class PairingResult:
    """Result of pairing with companion."""
    success: bool
    companion_id: Optional[str] = None
    capability_fingerprint: Optional[str] = None
    error: Optional[str] = None


class RemoteDesktopTransport(BaseTransport):
    """Transport for remote desktop mode - companion runs on Windows/Desktop."""

    def __init__(self, config: TransportConfig):
        if config.topology_mode != TopologyMode.REMOTE_DESKTOP:
            raise ValueError("RemoteDesktopTransport requires REMOTE_DESKTOP topology mode")
        super().__init__(config)

        self._relay_websocket: Optional[Any] = None
        self._companion_id: Optional[str] = None
        self._connected = False
        self._response_futures: Dict[str, asyncio.Future] = {}
        self._message_handler_task: Optional[asyncio.Task] = None

        # Validate required config for remote mode
        if not config.relay_url:
            raise ValueError("relay_url required for REMOTE_DESKTOP mode")

    async def connect(self) -> int:
        """Connect to backend relay server."""
        try:
            import websockets
            import ssl

            ssl_context = None
            if self.config.relay_url.startswith("wss://"):
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            self._relay_websocket = await websockets.connect(
                self.config.relay_url,
                ssl=ssl_context,
                ping_interval=20,
                ping_timeout=10,
            )
            self._connected = True

            # Start message handler
            self._message_handler_task = asyncio.create_task(self._message_handler())

            logger.info(f"Connected to relay at {self.config.relay_url}")
            return 0  # No local port in remote mode
        except Exception as e:
            logger.error(f"Failed to connect to relay: {e}")
            raise TransportError(f"Cannot connect to relay: {e}")

    async def disconnect(self) -> None:
        """Disconnect from relay."""
        if self._message_handler_task:
            self._message_handler_task.cancel()
            try:
                await self._message_handler_task
            except asyncio.CancelledError:
                pass

        if self._relay_websocket:
            await self._relay_websocket.close()
            self._relay_websocket = None

        self._connected = False

    async def pair(self, pairing_code: str, companion_id: Optional[str] = None) -> PairingResult:
        """Pair with companion via relay using pairing code."""
        if not self._relay_websocket or not self._connected:
            return PairingResult(success=False, error="Not connected to relay")

        # Send pair command to relay
        message = {
            "type": "pair",
            "pairing_code": pairing_code,
            "backend_id": "demo_backend",
        }

        try:
            await self._relay_websocket.send(json.dumps(message))

            # Wait for companion_registered or error
            # This would be handled by message handler - we need to wait for response
            # For now, we'll wait for the message handler to set _companion_id
            # In a real implementation, we'd use a future to wait for the response
            await asyncio.sleep(0.5)  # Brief wait for response

            if self._companion_id:
                # Compute capability fingerprint
                # Note: capability token is stored internally, not exposed
                fingerprint = self._compute_capability_fingerprint()
                return PairingResult(
                    success=True,
                    companion_id=self._companion_id,
                    capability_fingerprint=fingerprint,
                )
            else:
                return PairingResult(success=False, error="Pairing timeout or failed")

        except Exception as e:
            logger.error(f"Pairing failed: {e}")
            return PairingResult(success=False, error=str(e))

    async def wait_for_companion(self, timeout: float = 30.0) -> bool:
        """Wait for companion to register."""
        start = asyncio.get_event_loop().time()
        while not self._companion_id:
            if asyncio.get_event_loop().time() - start > timeout:
                return False
            await asyncio.sleep(0.5)
        return True

    def _compute_capability_fingerprint(self) -> Optional[str]:
        """Compute secure fingerprint of capability token."""
        if not hasattr(self, '_capability_token') or not self._capability_token:
            return None
        import hashlib
        return hashlib.sha256(self._capability_token.encode()).hexdigest()[:12]

    async def disconnect(self) -> None:
        """Disconnect from relay."""
        if self._message_handler_task:
            self._message_handler_task.cancel()
            try:
                await self._message_handler_task
            except asyncio.CancelledError:
                pass

        if self._relay_websocket:
            await self._relay_websocket.close()
            self._relay_websocket = None

        self._connected = False

    async def _message_handler(self) -> None:
        """Handle incoming messages from relay."""
        try:
            import websockets
            async for message in self._relay_websocket:
                data = json.loads(message)
                await self._process_relay_message(data)
        except Exception as e:
            logger.error(f"Relay message handler error: {e}")
            self._connected = False

    async def _process_relay_message(self, data: Dict[str, Any]) -> None:
        """Process message from relay."""
        msg_type = data.get("type")

        if msg_type == "response":
            request_id = data.get("request_id")
            if request_id in self._response_futures:
                future = self._response_futures.pop(request_id)
                if not future.done():
                    future.set_result(data)
        elif msg_type == "companion_registered":
            self._companion_id = data.get("companion_id")
            self._capability_token = data.get("capability_token")
            logger.info(f"Companion registered: {self._companion_id}")
        elif msg_type == "error":
            logger.error(f"Relay error: {data.get('error')}")

    async def _send_and_wait(self, request: CompanionRequest) -> CompanionResponse:
        """Send request via relay and wait for response."""
        if not self._relay_websocket or not self._connected:
            raise RuntimeError("Not connected to relay")

        request_id = request.payload.get("request_id", str(uuid.uuid4()))
        if "request_id" not in request.payload:
            request.payload["request_id"] = request_id

        # Create future for response
        future = asyncio.get_event_loop().create_future()
        self._response_futures[request_id] = future

        try:
            # Send via relay
            message = {
                "type": "command",
                "request_id": request_id,
                "command": request.command,
                "session_id": request.session_id,
                "pairing_token": request.pairing_token,
                "payload": request.payload,
            }
            await self._relay_websocket.send(json.dumps(message))

            # Wait for response with timeout
            response_data = await asyncio.wait_for(future, timeout=self.config.request_timeout)
            return CompanionResponse(
                success=response_data.get("success", False),
                session_id=response_data.get("session_id", ""),
                status=response_data.get("status", ""),
                payload=response_data.get("payload", {}),
                error=response_data.get("error"),
            )
        except asyncio.TimeoutError:
            raise TransportError("Command timeout")
        except Exception as e:
            raise TransportError(f"Command failed: {e}")
        finally:
            self._response_futures.pop(request_id, None)

    async def start_session(
        self,
        profile_name: str = "default",
        profile_path: Optional[Path] = None,
        target_url: str = "",
        success_url_prefix: str = "",
        success_selector: str = "",
        width: int = 1920,
        height: int = 1080,
        headless: bool = False,
        chrome_path: Optional[str] = None,
        chrome_args: Optional[list[str]] = None,
        browser_startup: str = "playwright",
        auth_wait_seconds: int = 300,
    ) -> tuple[str, PairingToken]:
        """Start a new session via relay."""
        import secrets

        self._session_id = secrets.token_urlsafe(16)

        request = CompanionRequest(
            command=CompanionCommand.START_SESSION.value,
            session_id=self._session_id,
            pairing_token="",
            payload={
                "profile_name": profile_name,
                "target_url": target_url,
                "success_url_prefix": success_url_prefix,
                "success_selector": success_selector,
                "width": width,
                "height": height,
                "headless": headless,
                "chrome_path": chrome_path,
                "chrome_args": chrome_args or [],
                "browser_startup": browser_startup,
                "auth_wait_seconds": auth_wait_seconds,
            },
        )

        response = await self._send_and_wait(request)

        if not response.success:
            raise RuntimeError(f"Failed to start session: {response.error}")

        self._pairing_token = PairingToken(
            token=response.payload["pairing_token"],
            created_at=time.time(),
            expires_at=response.payload["expires_at"],
            session_id=self._session_id,
        )

        self._connected = True
        return self._session_id, self._pairing_token

    async def open_url(self, session_id: str, url: str) -> CompanionResponse:
        """Open a URL in the remote browser."""
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.OPEN_URL.value,
            session_id=session_id,
            pairing_token=self._pairing_token.token,
            payload={"url": url},
        )

        return await self._send_and_wait(request)

    async def get_safe_page_state(self, session_id: str) -> SafePageState:
        """Get safe page state from remote browser."""
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.GET_SAFE_PAGE_STATE.value,
            session_id=session_id,
            pairing_token=self._pairing_token.token,
            payload={},
        )

        response = await self._send_and_wait(request)

        if not response.success:
            raise RuntimeError(f"Failed to get page state: {response.error}")

        return SafePageState.from_dict(response.payload)

    async def confirm_authentication(self, session_id: str) -> tuple[bool, SafePageState]:
        """Confirm authentication on remote companion with proper checks."""
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.CONFIRM_AUTHENTICATION.value,
            session_id=session_id,
            pairing_token=self._pairing_token.token,
            payload={},
        )

        response = await self._send_and_wait(request)
        state = SafePageState.from_dict(response.payload)

        # Additional auth validation
        authenticated = response.success
        if authenticated:
            # Check for login markers
            if state.login_markers:
                authenticated = False
            # Check for provider block markers
            if state.provider_block_markers:
                authenticated = False
            # Check for auth.heygen.com hostname
            if "auth.heygen.com" in state.hostname:
                authenticated = False
            # Check title for login page
            title_lower = state.title.lower()
            if any(p in title_lower for p in ("login", "sign in", "sign-in", "signin")):
                authenticated = False

        return authenticated, state

    async def start_recording(
        self,
        session_id: str,
        output_path: Path,
        events_output_path: Optional[Path] = None,
        fps: int = 30,
        show_recording_indicator: bool = True,
    ) -> CompanionResponse:
        """Start remote recording."""
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.START_RECORDING.value,
            session_id=session_id,
            pairing_token=self._pairing_token.token,
            payload={
                "output_name": output_path.name,
                "events_output_path": str(events_output_path) if events_output_path else None,
                "fps": fps,
                "show_recording_indicator": show_recording_indicator,
            },
        )

        return await self._send_and_wait(request)

    async def stop_recording(self, session_id: str) -> CompanionResponse:
        """Stop remote recording."""
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.STOP_RECORDING.value,
            session_id=session_id,
            pairing_token=self._pairing_token.token,
            payload={},
        )

        return await self._send_and_wait(request)

    async def finish_session(self, session_id: str) -> CompanionResponse:
        """Finish session and cleanup."""
        if not self._session_id or not self._pairing_token:
            raise RuntimeError("No active session")

        request = CompanionRequest(
            command=CompanionCommand.FINISH_SESSION.value,
            session_id=session_id,
            pairing_token=self._pairing_token.token,
            payload={},
        )

        response = await self._send_and_wait(request)

        # Clean up local state
        self._session_id = None
        self._pairing_token = None
        self._session_config = None
        self._connected = False

        return response


def create_transport(config: Optional[TransportConfig] = None) -> BaseTransport:
    """Factory function to create transport based on topology mode."""
    if config is None:
        # Auto-detect from environment
        mode_str = os.environ.get("HERMES_TRANSPORT_MODE", "local_development")
        try:
            topology_mode = TopologyMode(mode_str)
        except ValueError:
            logger.warning(f"Unknown topology mode '{mode_str}', defaulting to local_development")
            topology_mode = TopologyMode.LOCAL_DEVELOPMENT
        config = TransportConfig(topology_mode=topology_mode)

    if config.topology_mode == TopologyMode.LOCAL_DEVELOPMENT:
        return LocalDesktopTransport(config)
    elif config.topology_mode == TopologyMode.REMOTE_DESKTOP:
        return RemoteDesktopTransport(config)
    else:
        raise ValueError(f"Unknown topology mode: {config.topology_mode}")