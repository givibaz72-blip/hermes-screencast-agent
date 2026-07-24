from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shlex
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import websockets

from ..transport.protocol import (
    AuthStatus,
    BrowserStartup,
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


class CompanionMode(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


@dataclass
class LocalCompanionConfig:
    """Configuration for local companion mode."""
    host: str = "127.0.0.1"
    port: int = 0
    headless: bool = True
    chrome_path: Optional[str] = None
    browser_startup: str = "playwright"
    cdp_endpoint: Optional[str] = None
    cdp_host: str = "127.0.0.1"
    cdp_port: int = 9222
    auth_wait_seconds: int = 300


@dataclass
class RemoteCompanionConfig:
    """Configuration for remote companion mode (outbound to relay)."""
    relay_url: str  # wss://host:port
    pairing_code: str
    companion_id: Optional[str] = None
    platform: str = "windows"
    version: str = "1.0.0"
    max_reconnect_attempts: int = 5
    reconnect_interval: float = 5.0
    auto_reconnect: bool = True
    profile_dir: Optional[str] = None
    recording_dir: str = ""
    chrome_path: Optional[str] = None


@dataclass
class UnifiedCompanionConfig:
    """Unified configuration for companion."""
    mode: CompanionMode = CompanionMode.LOCAL
    local: LocalCompanionConfig = field(default_factory=LocalCompanionConfig)
    remote: Optional[RemoteCompanionConfig] = None


# ---------------------------------------------------------------------------
# Helper: auto-discover CDP endpoint on localhost
# ---------------------------------------------------------------------------
def _discover_cdp_endpoint(host: str = "127.0.0.1", port: int = 9222) -> str:
    """Probe *host:port*/json/version and return the HTTP endpoint URL.

    Raises RuntimeError if the endpoint is unreachable or doesn't return valid
    CDP metadata (meaning Chrome is not listening with ``--remote-debugging-port``).
    """
    url = f"http://{host}:{port}/json/version"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            if not data.get("webSocketDebuggerUrl"):
                raise RuntimeError(
                    f"Reached {url} but got no 'webSocketDebuggerUrl' "
                    f"— is Chrome running with --remote-debugging-port?"
                )
            return f"http://{host}:{port}"
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot connect to Chrome CDP at {url}. "
            f"Ensure Chrome is running with --remote-debugging-port={port}. "
            f"Details: {e}"
        ) from e


class LocalBrowserProcess:
    """Manages a local browser process using Playwright async API or raw CDP."""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.profile_path: Optional[Path] = None
        self.chrome_path: str = "chrome"
        self.width: int = 1920
        self.height: int = 1080
        self.headless: bool = False
        self._playwright = None
        self._playwright_context = None
        self._playwright_page = None
        self._recording_proc: Optional[subprocess.Popen] = None
        # Raw CDP
        self._raw_chrome: Optional[Any] = None
        self._raw_cdp_connected = False
        self._browser_startup: str = "playwright"

    async def start(self, config: SessionConfig) -> bool:
        """Start local browser with persistent profile."""
        try:
            self.profile_path = config.profile_path
            self.profile_path.mkdir(parents=True, exist_ok=True)
            self.chrome_path = config.chrome_path or "chrome"
            self._browser_startup = config.browser_startup

            if config.browser_startup == BrowserStartup.RAW_CDP.value:
                return await self._start_with_raw_cdp(config)
            elif config.browser_startup == BrowserStartup.EXISTING_CDP.value:
                return await self._start_with_existing_cdp(config)
            else:
                await self._start_with_playwright(config)
                return True
        except Exception as e:
            logger.error(f"Failed to start local browser: {e}")
            return False

    async def _start_with_playwright(self, config: SessionConfig) -> None:
        """Start browser using Playwright async API."""
        from playwright.async_api import async_playwright
        
        self._playwright = await async_playwright().start()
        
        self._playwright_context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_path),
            headless=config.headless,
            viewport={"width": config.width, "height": config.height},
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions-except",
                "--disable-plugins-discovery",
            ] + config.chrome_args,
            executable_path=config.chrome_path if config.chrome_path else None,
        )
        
        self._playwright_page = await self._playwright_context.new_page()
        self._playwright_page.set_default_timeout(30000)

        # Don't navigate at startup - let the OPEN_URL command handle navigation
        # This avoids DNS resolution issues in test environments

    async def _start_with_raw_cdp(self, config: SessionConfig) -> bool:
        """Start browser via raw Chrome subprocess + CDP connect.

        No Playwright launch() or launch_persistent_context().
        """
        from .raw_chrome import RawChromeCdpProcess, RawChromeStartupError

        self._raw_chrome = RawChromeCdpProcess(
            chrome_path=self.chrome_path,
            profile_dir=str(self.profile_path),
            target_url=config.target_url,
        )

        try:
            self._raw_chrome.start(timeout=30.0)
        except RawChromeStartupError as e:
            logger.error(f"Raw Chrome startup failed: {e}")
            self._raw_chrome = None
            return False

        # Connect Playwright via CDP
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            cdp_url = self._raw_chrome.cdp_endpoint
            if not cdp_url:
                logger.error("Raw Chrome CDP endpoint not ready")
                await self._raw_chrome.stop()
                self._raw_chrome = None
                return False

            browser = await self._playwright.chromium.connect_over_cdp(cdp_url)

            # Get existing context (not launch_persistent_context)
            contexts = browser.contexts
            if contexts:
                self._playwright_context = contexts[0]
            else:
                self._playwright_context = browser.contexts[0] if browser.contexts else None

            # Get the first page (existing, not new)
            if self._playwright_context:
                pages = self._playwright_context.pages
                if pages:
                    self._playwright_page = pages[0]
                else:
                    # No existing page; create one
                    self._playwright_page = await self._playwright_context.new_page()

            self._raw_cdp_connected = True
            logger.info(
                "Raw CDP connected: cdp_host=127.0.0.1 cdp_port=%d cdp_ready=yes",
                self._raw_chrome.cdp_port,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to connect Playwright to raw Chrome CDP: {e}")
            if self._raw_chrome:
                await self._stop_raw_chrome()
            return False

    async def _stop_raw_chrome(self) -> None:
        """Cleanup raw Chrome process and Playwright connection."""
        # Disconnect Playwright first
        try:
            if self._playwright_context:
                # Do NOT close browser via browser.close() from CDP
                pass
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._playwright = None
        self._playwright_context = None
        self._playwright_page = None
        self._raw_cdp_connected = False

        # Then stop the owned Chrome process
        if self._raw_chrome:
            self._raw_chrome.stop()
            self._raw_chrome = None

    async def _start_with_existing_cdp(self, config: SessionConfig) -> bool:
        """Connect to an already-running Chrome instance via CDP.

        Does NOT launch Chrome. Only connects to existing CDP endpoint.
        If cdp_endpoint not provided, auto-discovers from cdp_host:cdp_port.
        """
        from playwright.async_api import async_playwright

        # Auto-discover or build CDP endpoint
        cdp_endpoint = config.cdp_endpoint
        if not cdp_endpoint:
            try:
                cdp_endpoint = _discover_cdp_endpoint(config.cdp_host, config.cdp_port)
                logger.info(f"Auto-discovered CDP endpoint: {cdp_endpoint}")
            except Exception as e:
                logger.error(f"CDP discovery failed: {e}")
                return False

        logger.info(f"Connecting to existing Chrome via CDP: {cdp_endpoint}")

        # Validate CDP endpoint is reachable
        try:
            req = urllib.request.Request(f"{cdp_endpoint}/json/version")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status != 200:
                    logger.error(f"CDP endpoint not reachable: {cdp_endpoint} (status={resp.status})")
                    return False
                version_info = json.loads(resp.read().decode("utf-8"))
                logger.info(f"CDP version: {version_info.get('Browser', 'unknown')}")
        except Exception as e:
            logger.error(f"Failed to reach CDP endpoint {cdp_endpoint}: {e}")
            return False

        try:
            self._playwright = await async_playwright().start()
            browser = await self._playwright.chromium.connect_over_cdp(cdp_endpoint)

            # Get existing context
            contexts = browser.contexts
            if contexts:
                self._playwright_context = contexts[0]
            else:
                self._playwright_context = await browser.new_context()

            # Get first page from existing context
            if self._playwright_context:
                pages = self._playwright_context.pages
                if pages:
                    self._playwright_page = pages[0]
                else:
                    self._playwright_page = await self._playwright_context.new_page()

            if not self._playwright_page:
                logger.error("Failed to get or create page from existing Chrome")
                await self._playwright.stop()
                self._playwright = None
                return False

            self._playwright_page.set_default_timeout(30000)
            logger.info("Successfully connected to existing Chrome via CDP")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to existing Chrome via CDP: {e}")
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            return False

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000) -> bool:
        """Navigate to URL."""
        try:
            if self._playwright_page:
                await self._playwright_page.goto(url, wait_until=wait_until, timeout=timeout)
                return True
        except Exception as e:
            logger.error(f"Navigation failed: {e}")
        return False

    async def get_safe_page_state(
        self,
        success_url_prefix: str = "",
        success_selector: str = "",
    ) -> SafePageState:
        """Get safe page state without secrets."""
        if not self._playwright_page:
            return SafePageState(
                current_url="",
                hostname="",
                title="",
                session_status=SessionStatus.FAILED.value,
                auth_status=AuthStatus.UNKNOWN.value,
            )

        try:
            page = self._playwright_page
            current_url = page.url
            title = await page.title()
            
            from urllib.parse import urlparse
            parsed = urlparse(current_url)
            hostname = parsed.hostname or ""
            
            success_selector_visible = False
            if success_selector:
                try:
                    element = page.locator(success_selector)
                    count = await element.count()
                    success_selector_visible = count > 0 and await element.first.is_visible()
                except Exception:
                    pass
            
            url_matched = False
            if success_url_prefix:
                url_matched = current_url.startswith(success_url_prefix)
            
            login_markers = []
            oauth_selectors = [
                "button:has-text('Sign in with Google')",
                "button:has-text('Sign in with Apple')",
                "button:has-text('Use email')",
                "button:has-text('Use SSO')",
                "a:has-text('Sign in with Google')",
                "a:has-text('Sign in with Apple')",
                "a:has-text('Use email')",
                "a:has-text('Use SSO')",
            ]
            for selector in oauth_selectors:
                try:
                    element = page.locator(selector)
                    if await element.count() > 0 and await element.first.is_visible():
                        login_markers.append(f"oauth:{selector}")
                except Exception:
                    pass
            
            login_form_selectors = [
                "form:has(input[type='email'])",
                "form:has(input[type='password'])",
                "button:has-text('Continue with email')",
                "button:has-text('Send magic link')",
                "button:has-text('Sign in')",
                "input[type='submit'][value*='Sign in']",
                "input[type='submit'][value*='Login']",
                "button[type='submit']:has-text('Sign in')",
            ]
            for selector in login_form_selectors:
                try:
                    element = page.locator(selector)
                    if await element.count() > 0 and await element.first.is_visible():
                        login_markers.append(f"login_form:{selector}")
                except Exception:
                    pass
            
            auth_heygen = "auth.heygen.com" in hostname
            if auth_heygen:
                login_markers.append("hostname:auth.heygen.com")
            
            title_lower = title.lower()
            if any(pattern in title_lower for pattern in ("login", "sign in", "sign-in", "signin")):
                login_markers.append(f"title:{title}")
            
            provider_block_markers = []
            
            unsafe_selectors = [
                "div[aria-label*='unsafe']",
                "div[aria-label*='not secure']",
                "div:has-text('browser or app may not be secure')",
                "div:has-text('This browser or app may not be secure')",
            ]
            for selector in unsafe_selectors:
                try:
                    element = page.locator(selector)
                    if await element.count() > 0 and await element.first.is_visible():
                        provider_block_markers.append(f"google_unsafe:{selector}")
                except Exception:
                    pass
            
            cf_selectors = [
                "#challenge-running",
                ".cf-challenge-running",
                "div.ray-id",
                "div:has-text('Verification failed')",
                "div:has-text('verify you are human')",
                "div:has-text('Challenge failed')",
                "iframe[src*='challenges.cloudflare.com']",
            ]
            for selector in cf_selectors:
                try:
                    element = page.locator(selector)
                    if await element.count() > 0 and await element.first.is_visible():
                        provider_block_markers.append(f"cloudflare:{selector}")
                except Exception:
                    pass
            
            auth_status = AuthStatus.UNKNOWN.value
            if provider_block_markers:
                auth_status = AuthStatus.PROVIDER_BLOCKED.value
            elif login_markers or auth_heygen:
                auth_status = AuthStatus.LOGIN_REQUIRED.value
            elif url_matched or success_selector_visible:
                auth_status = AuthStatus.AUTHENTICATED.value
            
            session_status = SessionStatus.RUNNING.value
            if auth_status == AuthStatus.AUTHENTICATED.value:
                session_status = SessionStatus.AUTHENTICATED.value
            elif auth_status == AuthStatus.LOGIN_REQUIRED.value:
                session_status = SessionStatus.AUTHENTICATING.value
            elif auth_status == AuthStatus.PROVIDER_BLOCKED.value:
                session_status = SessionStatus.FAILED.value
            
            viewport = page.viewport_size or {"width": self.width, "height": self.height}
            
            return SafePageState(
                current_url=current_url,
                hostname=hostname,
                title=title,
                visible_markers=login_markers + provider_block_markers,
                success_selector_visible=success_selector_visible,
                viewport_width=viewport["width"],
                viewport_height=viewport["height"],
                session_status=session_status,
                auth_status=auth_status,
                login_markers=login_markers,
                provider_block_markers=provider_block_markers,
            )
        except Exception as e:
            logger.error(f"Failed to get safe page state: {e}")
            return SafePageState(
                current_url="",
                hostname="",
                title="",
                session_status=SessionStatus.FAILED.value,
                auth_status=AuthStatus.UNKNOWN.value,
            )

    async def start_recording(self, config: RecordingConfig, output_name: str = "") -> bool:
        """Start local screen recording.
        
        Args:
            config: Recording configuration
            output_name: Safe filename (no paths) for the output file
        """
        try:
            # Validate output_name
            if not output_name:
                logger.error("output_name is required")
                return False
            
            if not self._is_safe_filename(output_name):
                logger.error(f"Invalid output filename: {output_name}")
                return False
            
            # Determine output path
            if config.recording_dir:
                output_path = config.recording_dir / output_name
            else:
                output_path = config.output_path
            
            # Ensure the output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Verify the resolved path is within recording_dir (if specified)
            if config.recording_dir:
                try:
                    output_path.resolve().relative_to(config.recording_dir.resolve())
                except ValueError:
                    logger.error(f"Output path escapes recording directory: {output_path}")
                    return False
            
            import platform
            system = platform.system().lower()
            
            if system == "windows":
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "gdigrab",
                    "-framerate", str(config.fps),
                    "-video_size", f"{config.width}x{config.height}",
                    "-i", "desktop",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "23",
                    "-pix_fmt", "yuv420p",
                    str(output_path),
                ]
            else:
                display = os.environ.get("DISPLAY", ":0")
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "x11grab",
                    "-framerate", str(config.fps),
                    "-video_size", f"{config.width}x{config.height}",
                    "-i", display,
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "23",
                    "-pix_fmt", "yuv420p",
                    str(output_path),
                ]
            
            self._recording_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            
            time.sleep(1)
            
            if self._recording_proc.poll() is not None:
                logger.error("Recording process failed to start")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            return False
    
    def _is_safe_filename(self, filename: str) -> bool:
        r"""Validate that a filename is safe for recording output.

        Rules:
        - Not empty
        - Not '.' or '..'
        - No path separators (/, \)
        - No drive letters (C:)
        - No UNC paths (\\server\share)
        - No '..' sequences
        - No alternate data streams (:)
        - Must end with .mp4
        - No Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
        """
        if not filename or filename in ('.', '..'):
            return False
        
        # Check for path separators
        if '/' in filename or '\\' in filename:
            return False
        
        # Check for drive letters (C:, D:, etc.)
        if len(filename) >= 2 and filename[1] == ':' and filename[0].isalpha():
            return False
        
        # Check for UNC paths
        if filename.startswith('\\\\') or filename.startswith('//'):
            return False
        
        # Check for .. sequences
        if '..' in filename:
            return False
        
        # Check for alternate data streams
        if ':' in filename:
            return False
        
        # Check extension
        if not filename.lower().endswith('.mp4'):
            return False
        
        # Check Windows reserved names
        base_name = filename[:-4].upper()  # Remove .mp4
        reserved_names = {
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        }
        if base_name in reserved_names:
            return False
        
        # Check for reserved names with extensions (e.g., CON.mp4, CON.txt)
        if base_name.split('.')[0] in reserved_names:
            return False
        
        return True

    async def stop_recording(self) -> bool:
        """Stop local screen recording."""
        try:
            if self._recording_proc:
                self._recording_proc.terminate()
                try:
                    self._recording_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._recording_proc.kill()
                self._recording_proc = None
                return True
        except Exception as e:
            logger.error(f"Failed to stop recording: {e}")
        return False

    async def stop(self) -> None:
        """Stop browser and cleanup."""
        if self._raw_chrome:
            await self._stop_raw_chrome()
        else:
            try:
                if self._playwright_context:
                    await self._playwright_context.close()
                if self._playwright:
                    await self._playwright.stop()
            except Exception:
                pass

        await self.stop_recording()


class LocalCompanion:
    """
    Unified companion supporting both local and remote modes.
    
    LOCAL MODE: Listens on 127.0.0.1 for local backend
    REMOTE MODE: Initiates outbound TLS WebSocket to relay server
    """

    def __init__(self, config: UnifiedCompanionConfig):
        if config.local.host != "127.0.0.1":
            raise ValueError("Local companion must bind to 127.0.0.1 only")
        
        self.config = config
        self.mode = config.mode
        self.local_config = config.local
        self.remote_config = config.remote
        
        self._lock = asyncio.Lock()
        self._browsers: Dict[str, LocalBrowserProcess] = {}
        self._sessions: Dict[str, SessionConfig] = {}
        self._pairing_tokens: Dict[str, PairingToken] = {}
        
        # Local mode
        self._local_server: Optional[asyncio.Server] = None
        self._local_port: int = 0
        
        # Remote mode
        self._ws: Optional[Any] = None
        self._companion_id: Optional[str] = None
        self._running = False
        self._message_handler_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._ws: Optional[Any] = None
        self._companion_id: Optional[str] = None
        self._capability_token: Optional[str] = None
        self._remote_config: Optional[RemoteCompanionConfig] = None

    @property
    def local_port(self) -> int:
        """Get the port the local companion is listening on."""
        return self._local_port

    async def start(self) -> None:
        """Start companion in configured mode."""
        if self.mode == CompanionMode.LOCAL:
            await self._start_local()
        elif self.mode == CompanionMode.REMOTE:
            success = await self._start_remote()
            if not success:
                raise RuntimeError("Failed to start remote companion")

    async def stop(self) -> None:
        """Stop companion in any mode."""
        if self.mode == CompanionMode.LOCAL:
            await self._stop_local()
        elif self.mode == CompanionMode.REMOTE:
            await self._stop_remote()
        
        async with self._lock:
            for browser in self._browsers.values():
                browser.stop()
            self._browsers.clear()
            self._sessions.clear()
            self._pairing_tokens.clear()

    # ========================================================================
    # Local Mode
    # ========================================================================
    
    async def _start_local(self) -> None:
        """Start local TCP server for local backend."""
        if self.local_config.port == 0:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((self.local_config.host, 0))
                self._local_port = s.getsockname()[1]
        else:
            self._local_port = self.local_config.port
        
        self._local_server = await asyncio.start_server(
            self._handle_local_client,
            self.local_config.host,
            self._local_port,
        )
        logger.info(f"Local companion listening on {self.local_config.host}:{self._local_port}")
        # NOTE: CLI protocol marker (COMPANION_PORT) is printed by the CLI entry point,
        # not by core LocalCompanion. This keeps the core reusable across different runners.
    
    async def _stop_local(self) -> None:
        if self._local_server:
            self._local_server.close()
            await self._local_server.wait_closed()
            self._local_server = None

    async def _handle_local_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await reader.read(8192)
            if not data:
                return
            
            request = CompanionRequest.from_json(data.decode())
            response = await self._process_request(request)
            
            writer.write(response.to_json().encode())
            await writer.drain()
        except Exception as e:
            logger.error(f"Error handling local client: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    # ========================================================================
    # Remote Mode
    # ========================================================================
    
    async def _start_remote(self) -> bool:
        """Connect to relay server via outbound TLS WebSocket."""
        if not self.remote_config:
            logger.error("Remote config not set")
            return False
        
        try:
            self._ws = await websockets.connect(
                self.remote_config.relay_url,
                ssl=ssl.create_default_context(),
                ping_interval=20,
                ping_timeout=10,
            )
            
            # Register with relay
            companion_id = self.remote_config.companion_id or str(uuid.uuid4())
            self._companion_id = companion_id
            
            await self._ws.send(json.dumps({
                "type": "register",
                "pairing_code": self.remote_config.pairing_code,
                "companion_id": self.remote_config.companion_id or str(uuid.uuid4()),
                "platform": self.remote_config.platform,
                "version": self.remote_config.version,
            }))
            
            # Wait for registration confirmation
            response = await self._ws.recv()
            data = json.loads(response)
            
            if data.get("type") == "register" and data.get("success"):
                logger.info(f"Registered with relay as {self.remote_config.companion_id or str(uuid.uuid4())}")
                
                # Start message handler
                self._running = True
                self._message_handler_task = asyncio.create_task(self._message_handler())
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                return True
            else:
                logger.error(f"Registration failed: {data.get('error')}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to relay: {e}")
            return False

    async def _stop_remote(self) -> None:
        self._running = False
        
        if self._message_handler_task:
            self._message_handler_task.cancel()
            try:
                await self._message_handler_task
            except asyncio.CancelledError:
                pass
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def _message_handler(self) -> None:
        """Handle messages from relay."""
        try:
            async for message in self._ws:
                data = json.loads(message)
                await self._process_relay_message(data)
        except Exception as e:
            logger.error(f"Relay message handler error: {e}")
            if self.remote_config and self.remote_config.auto_reconnect:
                await self._reconnect()

    async def _process_relay_message(self, data: Dict[str, Any]) -> None:
        msg_type = data.get("type")
        
        if msg_type == "forward_command":
            await self._handle_forwarded_command(data)
        elif msg_type == "pong":
            pass
        elif msg_type == "error":
            logger.error(f"Relay error: {data.get('error')}")
    
    async def _handle_forwarded_command(self, data: Dict[str, Any]) -> None:
        request_id = data.get("request_id")
        command = data.get("command")
        payload = data.get("payload", {})
        
        if not request_id:
            return
        
        # Create local request
        request = CompanionRequest(
            command=command,
            session_id=payload.get("session_id", ""),
            pairing_token=payload.get("pairing_token", ""),
            payload=payload,
        )
        
        # Process locally
        response = await self._process_request(request)
        
        # Send response back through relay
        await self._ws.send(json.dumps({
            "type": "response",
            "request_id": request_id,
            "success": response.success,
            "session_id": response.session_id,
            "status": response.status,
            "payload": response.payload,
            "error": response.error,
        }))

    async def _heartbeat_loop(self) -> None:
        while self._running:
            if self._ws:
                try:
                    await self._ws.send(json.dumps({
                        "type": "heartbeat",
                        "companion_id": self._companion_id,
                    }))
                except Exception:
                    break
            await asyncio.sleep(20)

    async def _reconnect(self) -> None:
        for attempt in range(self.remote_config.max_reconnect_attempts):
            logger.info(f"Reconnection attempt {attempt + 1}")
            if await self._start_remote():
                return
            await asyncio.sleep(self.remote_config.reconnect_interval)
        
        logger.error("Max reconnection attempts reached")

    # ========================================================================
    # Common Request Processing
    # ========================================================================
    
    async def _process_request(self, request: CompanionRequest) -> CompanionResponse:
        """Process a companion request (shared logic)."""
        async with self._lock:
            # Verify pairing token
            if request.command != CompanionCommand.START_SESSION.value:
                token = self._pairing_tokens.get(request.session_id)
                if not token or token.token != request.pairing_token or not token.is_valid():
                    return CompanionResponse(
                        success=False,
                        session_id=request.session_id,
                        status=SessionStatus.FAILED.value,
                        error="Invalid or expired pairing token",
                    )
            
            try:
                if request.command == CompanionCommand.START_SESSION.value:
                    return await self._handle_start_session(request)
                elif request.command == CompanionCommand.OPEN_URL.value:
                    return await self._handle_open_url(request)
                elif request.command == CompanionCommand.GET_SAFE_PAGE_STATE.value:
                    return await self._handle_get_safe_page_state(request)
                elif request.command == CompanionCommand.CONFIRM_AUTHENTICATION.value:
                    return await self._handle_confirm_authentication(request)
                elif request.command == CompanionCommand.START_RECORDING.value:
                    return await self._handle_start_recording(request)
                elif request.command == CompanionCommand.STOP_RECORDING.value:
                    return await self._handle_stop_recording(request)
                elif request.command == CompanionCommand.FINISH_SESSION.value:
                    return await self._handle_finish_session(request)
                else:
                    return CompanionResponse(
                        success=False,
                        session_id=request.session_id,
                        status=SessionStatus.FAILED.value,
                        error=f"Unknown command: {request.command}",
                    )
            except Exception as e:
                logger.error(f"Error processing {request.command}: {e}")
                return CompanionResponse(
                    success=False,
                    session_id=request.session_id,
                    status=SessionStatus.FAILED.value,
                    error=str(e),
                )
    
    async def _handle_start_session(self, request: CompanionRequest) -> CompanionResponse:
        payload = request.payload
        session_id = request.session_id
        
        token = PairingToken.create(session_id)
        self._pairing_tokens[session_id] = token
        
        profile_path = Path(payload.get("profile_path", tempfile.gettempdir())) / "hermes_profiles" / payload.get("profile_name", "default")
        profile_path.mkdir(parents=True, exist_ok=True)
        
        config = SessionConfig(
            session_id=session_id,
            profile_name=payload.get("profile_name", "default"),
            profile_path=profile_path,
            target_url=payload.get("target_url", ""),
            success_url_prefix=payload.get("success_url_prefix", ""),
            success_selector=payload.get("success_selector", ""),
            width=payload.get("width", 1920),
            height=payload.get("height", 1080),
            headless=payload.get("headless", False),
            chrome_path=payload.get("chrome_path"),
            chrome_args=payload.get("chrome_args", []),
            browser_startup=payload.get("browser_startup", self.local_config.browser_startup),
            auth_wait_seconds=payload.get("auth_wait_seconds", self.local_config.auth_wait_seconds),
            cdp_endpoint=payload.get("cdp_endpoint"),
            cdp_host=payload.get("cdp_host", "127.0.0.1"),
            cdp_port=payload.get("cdp_port", 9222),
        )
        
        self._sessions[session_id] = config
        
        # Check if this is a test mode (no real browser launch)
        if payload.get("test_mode", False):
            return CompanionResponse(
                success=True,
                session_id=session_id,
                status=SessionStatus.PENDING.value,
                payload={
                    "pairing_token": token.token,
                    "expires_at": token.expires_at,
                },
            )
        
        browser = LocalBrowserProcess()
        success = await browser.start(config)
        
        if not success:
            return CompanionResponse(
                success=False,
                session_id=session_id,
                status=SessionStatus.FAILED.value,
                error="Failed to start browser",
            )
        
        self._browsers[session_id] = browser
        
        return CompanionResponse(
            success=True,
            session_id=session_id,
            status=SessionStatus.PENDING.value,
            payload={
                "pairing_token": token.token,
                "expires_at": token.expires_at,
            },
        )
    
    async def _handle_open_url(self, request: CompanionRequest) -> CompanionResponse:
        session_id = request.session_id
        url = request.payload.get("url", "")
        
        browser = self._browsers.get(session_id)
        if not browser:
            return CompanionResponse(
                success=False,
                session_id=session_id,
                status=SessionStatus.FAILED.value,
                error="Browser not found",
            )
        
        config = self._sessions.get(session_id)
        if config:
            config.target_url = url
        
        success = await browser.goto(url)
        
        return CompanionResponse(
            success=success,
            session_id=session_id,
            status=SessionStatus.RUNNING.value if success else SessionStatus.FAILED.value,
        )
    
    async def _handle_get_safe_page_state(self, request: CompanionRequest) -> CompanionResponse:
        session_id = request.session_id
        
        browser = self._browsers.get(session_id)
        config = self._sessions.get(session_id)
        
        if not browser or not config:
            return CompanionResponse(
                success=False,
                session_id=session_id,
                status=SessionStatus.FAILED.value,
                error="Session not found",
            )
        
        state = await browser.get_safe_page_state(
            success_url_prefix=config.success_url_prefix,
            success_selector=config.success_selector,
        )
        
        return CompanionResponse(
            success=True,
            session_id=session_id,
            status=state.session_status,
            payload=state.to_dict(),
        )
    
    async def _handle_confirm_authentication(self, request: CompanionRequest) -> CompanionResponse:
        session_id = request.session_id
        
        browser = self._browsers.get(session_id)
        config = self._sessions.get(session_id)
        
        if not browser or not config:
            return CompanionResponse(
                success=False,
                session_id=session_id,
                status=SessionStatus.FAILED.value,
                error="Session not found",
            )
        
        state = await browser.get_safe_page_state(
            success_url_prefix=config.success_url_prefix,
            success_selector=config.success_selector,
        )
        
        authenticated = state.auth_status == AuthStatus.AUTHENTICATED.value
        
        return CompanionResponse(
            success=authenticated,
            session_id=session_id,
            status=SessionStatus.AUTHENTICATED.value if authenticated else SessionStatus.AUTHENTICATING.value,
            payload=state.to_dict(),
        )
    
    async def _handle_start_recording(self, request: CompanionRequest) -> CompanionResponse:
        session_id = request.session_id
        
        browser = self._browsers.get(session_id)
        config = self._sessions.get(session_id)
        
        if not browser or not config:
            return CompanionResponse(
                success=False,
                session_id=session_id,
                status=SessionStatus.FAILED.value,
                error="Session not found",
            )
        
        state = await browser.get_safe_page_state(
            success_url_prefix=config.success_url_prefix,
            success_selector=config.success_selector,
        )
        
        if state.auth_status != AuthStatus.AUTHENTICATED.value:
            return CompanionResponse(
                success=False,
                session_id=session_id,
                status=SessionStatus.AUTHENTICATING.value,
                error="Not authenticated - cannot start recording",
                payload=state.to_dict(),
            )
        
        # Get output filename from backend (only filename, not path)
        output_name = request.payload.get("output_name", "")
        events_path = request.payload.get("events_output_path")
        
        # Validate filename
        if not output_name:
            return CompanionResponse(
                success=False,
                session_id=session_id,
                status=SessionStatus.FAILED.value,
                error="output_name is required",
            )
        
        # Validate safe filename
        if not self._is_safe_filename(output_name):
            return CompanionResponse(
                success=False,
                session_id=session_id,
                status=SessionStatus.FAILED.value,
                error=f"Invalid output filename: {output_name}",
            )
        
        # Get recording directory from remote config
        recording_dir = None
        if self.remote_config and self.remote_config.recording_dir:
            recording_dir = Path(self.remote_config.recording_dir)
        
        recording_config = RecordingConfig(
            output_path=Path(""),  # Will be set by browser using recording_dir
            events_output_path=Path(events_path) if events_path else None,
            recording_dir=recording_dir,
            width=config.width,
            height=config.height,
            fps=request.payload.get("fps", 30),
            show_recording_indicator=request.payload.get("show_recording_indicator", True),
        )
        
        success = await browser.start_recording(recording_config, output_name)
        
        return CompanionResponse(
            success=success,
            session_id=session_id,
            status=SessionStatus.RECORDING.value if success else SessionStatus.FAILED.value,
        )

    def _is_safe_filename(self, filename: str) -> bool:
        """Validate that a filename is safe for recording output.
        
        Rules:
        - Must end with .mp4
        - No absolute paths
        - No UNC paths
        - No drive-qualified paths
        - No '..' components
        - No '/' or '\' characters
        - Not empty
        - Not '.' or '..'
        - Not Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
        - No alternate data streams (colon)
        """
        if not filename:
            return False
        
        # Check extension
        if not filename.lower().endswith('.mp4'):
            return False
        
        # Check for path separators
        if '/' in filename or '\\' in filename:
            return False
        
        # Check for parent directory traversal
        if '..' in filename:
            return False
        
        # Check for alternate data streams
        if ':' in filename:
            return False
        
        # Check for empty or special names
        if filename in ('.', '..'):
            return False
        
        # Check for Windows reserved names
        base_name = filename[:-4]  # Remove .mp4
        reserved_names = {
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        }
        if base_name.upper() in reserved_names:
            return False
        
        # Check for absolute paths
        if os.path.isabs(filename):
            return False
        
        # Check for drive-qualified paths (Windows)
        if len(filename) >= 2 and filename[1] == ':':
            return False
        
        # Check for UNC paths
        if filename.startswith('\\\\') or filename.startswith('//'):
            return False
        
        return True
    
    async def _handle_stop_recording(self, request: CompanionRequest) -> CompanionResponse:
        session_id = request.session_id
        
        browser = self._browsers.get(session_id)
        if not browser:
            return CompanionResponse(
                success=False,
                session_id=session_id,
                status=SessionStatus.FAILED.value,
                error="Browser not found",
            )
        
        success = await browser.stop_recording()
        
        return CompanionResponse(
            success=success,
            session_id=session_id,
            status=SessionStatus.COMPLETED.value if success else SessionStatus.FAILED.value,
        )
    
    async def _handle_finish_session(self, request: CompanionRequest) -> CompanionResponse:
        session_id = request.session_id
        
        async with self._lock:
            browser = self._browsers.pop(session_id, None)
            config = self._sessions.pop(session_id, None)
            token = self._pairing_tokens.pop(session_id, None)
        
        if browser:
            await browser.stop()
        
        if token:
            token.mark_used()
        
        return CompanionResponse(
            success=True,
            session_id=session_id,
            status=SessionStatus.COMPLETED.value,
        )