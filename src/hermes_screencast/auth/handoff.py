from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from ..browser.session_manager import SessionManager
from ..recording import VirtualDisplay
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..browser.runtime import BrowserRuntime, BrowserRuntimeConfig


@dataclass(frozen=True)
class LoopbackConfig:
    """Loopback-only network configuration for security."""
    host: str = "127.0.0.1"
    port: int = 0  # 0 = auto-assign

    def __post_init__(self) -> None:
        # Validate host is exactly 127.0.0.1
        if self.host != "127.0.0.1":
            raise ValueError("Host must be 127.0.0.1")


@dataclass(frozen=True)
class AuthSuccessConfig:
    """Configuration for detecting successful authentication."""
    success_url_prefix: str = ""
    success_selector: str = ""
    no_auto_detect: bool = False

    def is_configured(self) -> bool:
        return bool(self.success_url_prefix) or bool(self.success_selector)

    def check_url(self, url: str) -> bool:
        """Check if URL matches success criteria."""
        if self.success_url_prefix:
            return url.startswith(self.success_url_prefix)
        return False


@dataclass
class HandoffResult:
    """Result of the assisted login handoff."""
    status: str  # authenticated | cancelled | timeout | failed
    profile: str
    profile_path: str
    target_url: str
    final_url: str
    handoff_closed: bool = True

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, indent=2)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def generate_token() -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_urlsafe(32)


def validate_loopback_host(host: str) -> bool:
    """Validate that a host is a loopback address."""
    """Validate that a host is a loopback address."""
    if not host:
        return False
    # Only allow 127.0.0.1 (IPv4 loopback)
    return host == "127.0.0.1"


class AssistedLoginHandoff:
    """
    Manages the visual handoff for assisted login via VNC over WebSocket.

    Architecture:
    - Xvfb (virtual display) -> Chromium -> x11vnc -> websockify -> noVNC web client
    - All bound to loopback only (127.0.0.1)
    - One-time random token for access control
    - No credential logging, no screenshot during secret entry
    """

    def __init__(
        self,
        loopback: LoopbackConfig,
        token: str,
        display: str = ":99",
        width: int = 1920,
        height: int = 1080,
        success_config: Optional[AuthSuccessConfig] = None,
        timeout: float = 300.0,
        profile: str = "default",
        target_url: str = "",
    ) -> None:
        self.loopback = loopback
        self.token = token
        self.display = display
        self.width = width
        self.height = height
        self.success_config = success_config or AuthSuccessConfig()
        self.timeout = timeout
        self.profile = profile
        self.target_url = target_url

        self._vdisplay: Optional[VirtualDisplay] = None
        self._x11vnc_proc: Optional[subprocess.Popen] = None
        self._websockify_proc: Optional[subprocess.Popen] = None
        self._browser_runtime: Optional["BrowserRuntime"] = None
        self._handoff_url: str = ""
        self._result: Optional[HandoffResult] = None
        self._cancelled = threading.Event()
        self._authenticated = threading.Event()
        self._lock = threading.Lock()
        self._vnc_port: int = 0
        self._ws_port: int = 0
        self._token_file: Optional[str] = None
        self._owns_display: bool = False

    def _allocate_port(self) -> int:
        """Find a free port on loopback."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((self.loopback.host, 0))
            return s.getsockname()[1]

    def _build_handoff_url(self, port: int) -> str:
        """Build the handoff URL with token."""
        return f"http://{self.loopback.host}:{port}/vnc.html?token={self.token}&autoconnect=1&resize=scale"

    def _start_virtual_display(self) -> None:
        """Start VirtualDisplay with proper cleanup on failure."""
        self._vdisplay = VirtualDisplay(
            display=self.display,
            width=self.width,
            height=self.height,
        )
        try:
            self._vdisplay.start()
            self._owns_display = getattr(self._vdisplay, '_owns_display', True)
        except Exception as e:
            self._vdisplay = None
            self._owns_display = False
            raise RuntimeError(f"Failed to start virtual display {self.display}: {e}") from e

    def _start_x11vnc(self, vnc_port: int) -> None:
        """Start x11vnc bound to loopback."""
        # x11vnc is intentionally passwordless only on an ephemeral loopback listener; access through the noVNC path is protected by the websockify token.
        self._x11vnc_proc = subprocess.Popen(
            [
                "x11vnc",
                "-display", self.display,
                "-rfbport", str(vnc_port),
                "-nopw",  # No password: we rely on websockify token for authentication
                "-forever",
                "-shared",
                "-noxdamage",
                "-noxfixes",
                "-quiet",
                "-listen", self.loopback.host,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Give x11vnc time to start
        time.sleep(0.5)
        if self._x11vnc_proc.poll() is not None:
            raise RuntimeError("x11vnc failed to start")

    def _create_token_file(self) -> str:
        """Create a token file for websockify authentication.

        Format expected by websockify TokenFile plugin:
        token: target_host:target_port
        """
        token_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.token')
        # TokenFile expects format: token: target_host:target_port
        token_file.write(f"{self.token}: {self.loopback.host}:{self._vnc_port}\n")
        token_file.close()
        os.chmod(token_file.name, 0o600)
        return token_file.name

    def _start_browser(self) -> None:
        """Start browser runtime with persistent profile."""
        # Import here to avoid circular imports
        from ..browser.runtime import BrowserRuntime, BrowserRuntimeConfig

        # Get profile path using SessionManager
        session_manager = SessionManager()
        profile_path = session_manager.ensure_profile(self.profile)

        config = BrowserRuntimeConfig(
            profile=self.profile,
            headless=False,
            viewport_width=self.width,
            viewport_height=self.height,
            display=self.display,
        )
        self._browser_runtime = BrowserRuntime(config=config)
        self._browser_runtime.__enter__()

        # Navigate to target URL
        if self.target_url:
            self._browser_runtime.goto(self.target_url, wait_until="domcontentloaded", timeout=30000)

    def _monitor_authentication(self) -> None:
        """Monitor for authentication completion."""
        start_time = time.time()
        check_interval = 1.0

        while not self._cancelled.is_set() and not self._authenticated.is_set():
            if time.time() - start_time > self.timeout:
                with self._lock:
                    if self._result is None:
                        self._result = HandoffResult(
                            status="timeout",
                            profile=self.profile,
                            profile_path=str(SessionManager().profile_path(self.profile)),
                            target_url=self.target_url,
                            final_url=self.target_url,
                            handoff_closed=True,
                        )
                return

            try:
                if self._browser_runtime and self._browser_runtime.page:
                    current_url = self._browser_runtime.page.url

                    # Check success URL prefix
                    if self.success_config.check_url(current_url):
                        with self._lock:
                            self._result = HandoffResult(
                                status="authenticated",
                                profile=self.profile,
                                profile_path=str(SessionManager().profile_path(self.profile)),
                                target_url=self.target_url,
                                final_url=current_url,
                                handoff_closed=True,
                            )
                        self._authenticated.set()
                        return

                    # Check success selector if configured
                    if self.success_config.success_selector:
                        try:
                            element = self._browser_runtime.page.locator(self.success_config.success_selector)
                            if element.count() > 0 and element.first.is_visible():
                                with self._lock:
                                    self._result = HandoffResult(
                                        status="authenticated",
                                        profile=self.profile,
                                        profile_path=str(SessionManager().profile_path(self.profile)),
                                        target_url=self.target_url,
                                        final_url=current_url,
                                        handoff_closed=True,
                                    )
                                self._authenticated.set()
                                return
                        except Exception:
                            pass  # Selector not found, continue monitoring
            except Exception:
                pass  # Page might not be ready yet

            time.sleep(check_interval)

    def start(self) -> HandoffResult:
        """Start the handoff and return connection info."""
        # Allocate ports
        self._vnc_port = self._allocate_port()
        self._ws_port = self.loopback.port or self._allocate_port()

        # Start virtual display
        self._start_virtual_display()

        # Start VNC server
        self._start_x11vnc(self._vnc_port)

        # Start websockify with noVNC
        self._start_websockify(self._vnc_port, self._ws_port)

        # Build handoff URL
        self._handoff_url = self._build_handoff_url(self._ws_port)

        # Start browser
        self._start_browser()

        # Start monitoring thread
        monitor_thread = threading.Thread(target=self._monitor_authentication, daemon=True)
        monitor_thread.start()

        # Return connection info immediately
        return HandoffResult(
            status="pending",
            profile=self.profile,
            profile_path=str(SessionManager().profile_path(self.profile)),
            target_url=self.target_url,
            final_url=self.target_url,
            handoff_closed=False,
        )

    def wait_for_completion(self, timeout: Optional[float] = None) -> HandoffResult:
        """Wait for authentication to complete."""
        if self._result and self._result.status in ("authenticated", "timeout", "failed", "cancelled"):
            return self._result

        wait_time = timeout or self.timeout
        start = time.time()

        while time.time() - start < wait_time:
            if self._authenticated.is_set() and self._result:
                return self._result
            if self._cancelled.is_set():
                with self._lock:
                    self._result = HandoffResult(
                        status="cancelled",
                        profile=self.profile,
                        profile_path=str(SessionManager().profile_path(self.profile)),
                        target_url=self.target_url,
                        final_url=self.target_url,
                        handoff_closed=True,
                    )
                return self._result
            time.sleep(0.5)

        # Timeout
        with self._lock:
            if self._result is None:
                self._result = HandoffResult(
                    status="timeout",
                    profile=self.profile,
                    profile_path=str(SessionManager().profile_path(self.profile)),
                    target_url=self.target_url,
                    final_url=self.target_url,
                    handoff_closed=True,
                )
        return self._result

    def cancel(self) -> None:
        """Cancel the handoff."""
        self._cancelled.set()
        self._authenticated.set()

    def _start_websockify(self, vnc_port: int, ws_port: int) -> None:
        """Start websockify (WebSocket to VNC proxy) bound to loopback with token auth."""
        # Use novnc package for web files
        try:
            import novnc
            novnc_path = os.path.dirname(novnc.__file__)
            web_path = os.path.join(novnc_path, "resources", "novnc_server")
            # The zip file is extracted to a subdirectory
            import zipfile
            import tempfile
            extract_dir = os.path.join(tempfile.gettempdir(), "novnc_web")
            if not os.path.exists(web_path):
                # Extract the zip file
                zip_path = os.path.join(novnc_path, "resources", "novnc_server.zip")
                if os.path.exists(zip_path):
                    os.makedirs(extract_dir, exist_ok=True)
                    with zipfile.ZipFile(zip_path, 'r') as z:
                        z.extractall(extract_dir)
                web_path = extract_dir
            elif os.path.exists(os.path.join(web_path, "vnc.html")):
                # Already extracted or available as directory
                pass
            else:
                # Try to find extracted version
                if os.path.exists(extract_dir) and os.path.exists(os.path.join(extract_dir, "vnc.html")):
                    web_path = extract_dir
        except ImportError:
            # Fallback if novnc not installed
            web_path = os.path.join(os.path.dirname(__file__), "novnc_web")

        # Create token file for websockify
        self._token_file = self._create_token_file()

        self._websockify_proc = subprocess.Popen(
            [
                "websockify",
                "--token-plugin", "websockify.token_plugins.TokenFile",
                "--token-source", self._token_file,
                "--heartbeat", "30",
                "--web", web_path,
                f"{self.loopback.host}:{ws_port}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        # Give websockify time to start
        time.sleep(0.5)
        if self._websockify_proc.poll() is not None:
            stderr = self._websockify_proc.stderr.read().decode() if self._websockify_proc.stderr else "unknown error"
            raise RuntimeError(f"websockify failed to start: {stderr}")
    def stop(self) -> None:
        """Stop all processes and clean up."""
        self._cancelled.set()
        self._authenticated.set()

        # Stop browser
        if self._browser_runtime:
            try:
                self._browser_runtime.__exit__(None, None, None)
            except Exception:
                pass
            self._browser_runtime = None

        # Stop websockify
        if self._websockify_proc is not None:
            try:
                self._websockify_proc.terminate()
                self._websockify_proc.wait(timeout=2)
            except Exception:
                try:
                    self._websockify_proc.kill()
                except Exception:
                    pass
            self._websockify_proc = None

        # Stop x11vnc
        if self._x11vnc_proc is not None:
            try:
                self._x11vnc_proc.terminate()
                self._x11vnc_proc.wait(timeout=2)
            except Exception:
                try:
                    self._x11vnc_proc.kill()
                except Exception:
                    pass
            self._x11vnc_proc = None

        # Stop virtual display (only if we own it)
        if self._vdisplay is not None:
            try:
                # Only close if we own the display
                if self._owns_display:
                    self._vdisplay.close()
                else:
                    # Just clean up cursor hider
                    if hasattr(self._vdisplay, 'cursor_hider') and self._vdisplay.cursor_hider:
                        self._vdisplay.cursor_hider.terminate()
            except Exception:
                pass
            self._vdisplay = None
            self._owns_display = False

        # Clean up any leftover token file
        if self._token_file:
            try:
                os.unlink(self._token_file)
            except Exception:
                pass
            self._token_file = None

        # Clean up any leftover password file

    def get_handoff_url(self) -> str:
        """Get the handoff URL for the user."""
        return self._handoff_url


def create_handoff(
    target_url: str,
    profile: str = "default",
    host: str = "127.0.0.1",
    port: int = 0,
    timeout: float = 300.0,
    success_url_prefix: str = "",
    success_selector: str = "",
    no_auto_detect: bool = False,
    display: str = ":99",
    width: int = 1920,
    height: int = 1080,
) -> AssistedLoginHandoff:
    """Create an AssistedLoginHandoff instance with validated config."""
    if not validate_loopback_host(host):
        raise ValueError(f"Host must be 127.0.0.1, got: {host}")

    loopback = LoopbackConfig(host=host, port=port)
    token = generate_token()

    success_config = AuthSuccessConfig(
        success_url_prefix=success_url_prefix,
        success_selector=success_selector,
        no_auto_detect=no_auto_detect,
    )

    return AssistedLoginHandoff(
        loopback=loopback,
        token=token,
        display=display,
        width=width,
        height=height,
        success_config=success_config,
        timeout=timeout,
        profile=profile,
        target_url=target_url,
    )
