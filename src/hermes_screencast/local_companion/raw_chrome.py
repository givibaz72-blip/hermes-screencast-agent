"""Raw Chrome CDP process manager for Windows-local E2E workflow.

Launches Chrome via subprocess with CDP enabled on loopback only,
reads DevToolsActivePort for CDP endpoint, and manages process lifecycle.

Security properties:
    - Chrome is launched via subprocess.Popen with argv array (no shell=True)
    - CDP binds to 127.0.0.1 only (not 0.0.0.0)
    - CDP port is random (--remote-debugging-port=0)
    - No stealth patches, no navigator.webdriver spoofing
    - Persistent profile is NOT deleted on cleanup
    - Only owned PID is terminated (no taskkill by name, no pkill/killall)
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RawChromeStartupError(Exception):
    """Raised when raw Chrome process fails to start or become ready."""


class RawChromeCdpProcess:
    """Manages a raw Chrome process with loopback-only CDP.

    Launches Chrome directly via subprocess (no Playwright launch),
    waits for DevToolsActivePort, and provides the CDP endpoint
    for Playwright connect_over_cdp.
    """

    REASONABLE_MAX_PORT = 65535

    def __init__(
        self,
        chrome_path: str,
        profile_dir: str | Path,
        target_url: str = "",
    ) -> None:
        self._chrome_path = str(chrome_path)
        self._profile_dir = Path(profile_dir)
        self._target_url = target_url
        self._process: Optional[subprocess.Popen] = None
        self._cdp_port: Optional[int] = None
        self._cdp_ws_path: Optional[str] = None
        self._started = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def cdp_host(self) -> str:
        """CDP host is always loopback."""
        return "127.0.0.1"

    @property
    def cdp_port(self) -> Optional[int]:
        """CDP port read from DevToolsActivePort, or None before start()."""
        return self._cdp_port

    @property
    def cdp_endpoint(self) -> Optional[str]:
        """Full CDP WebSocket endpoint (http://127.0.0.1:<port>).

        Returns None before readiness.
        """
        if self._cdp_port is None:
            return None
        return f"http://127.0.0.1:{self._cdp_port}"

    @property
    def pid(self) -> Optional[int]:
        """PID of the owned Chrome process, or None."""
        if self._process is not None and self._process.poll() is None:
            return self._process.pid
        return None

    @property
    def is_running(self) -> bool:
        """True if the owned Chrome process is still alive."""
        return self._process is not None and self._process.poll() is None

    @property
    def is_ready(self) -> bool:
        """True if CDP endpoint has been resolved and process is alive."""
        return self._cdp_port is not None and self.is_running

    def start(self, timeout: float = 30.0) -> None:
        """Launch Chrome and wait for CDP readiness.

        Args:
            timeout: Max seconds to wait for DevToolsActivePort.
                     Raises RawChromeStartupError on timeout.

        Raises:
            RawChromeStartupError: If Chrome fails to start, exits early,
                                   or DevToolsActivePort is not ready within
                                   the timeout.
        """
        if self._started:
            raise RawChromeStartupError("RawChromeCdpProcess already started")

        self._started = True

        # Remove stale DevToolsActivePort (the file, not the entire profile)
        devtools_port_path = self._profile_dir / "DevToolsActivePort"
        if devtools_port_path.exists():
            logger.debug("Removing stale DevToolsActivePort")
            devtools_port_path.unlink()

        # Build argv array - NO shell=True
        argv = [
            self._chrome_path,
            f"--user-data-dir={self._profile_dir}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if self._target_url:
            argv.append(self._target_url)

        logger.debug(
            "Launching Chrome: %s … (args truncated, %d total)",
            self._chrome_path,
            len(argv),
        )

        try:
            self._process = subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            raise RawChromeStartupError(
                f"Chrome executable not found: {self._chrome_path}"
            )
        except OSError as e:
            raise RawChromeStartupError(f"Failed to launch Chrome: {e}")

        # Wait for DevToolsActivePort
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Check if process exited early
            rc = self._process.poll()
            if rc is not None:
                stderr_output = self._read_stderr_safe()
                raise RawChromeStartupError(
                    f"Chrome exited early (rc={rc}): {stderr_output}"
                )

            if devtools_port_path.exists():
                try:
                    self._parse_devtools_active_port(devtools_port_path)
                    logger.info(
                        "Raw Chrome ready: cdp_host=%s cdp_port=%d cdp_ready=yes",
                        "127.0.0.1",
                        self._cdp_port,
                    )
                    return
                except RawChromeStartupError:
                    raise
                except Exception as e:
                    raise RawChromeStartupError(
                        f"Failed to parse DevToolsActivePort: {e}"
                    )

            time.sleep(0.2)

        # Timeout - clean up owned Chrome
        self._cleanup_owned_process()
        raise RawChromeStartupError(
            f"Timeout waiting for DevToolsActivePort ({timeout}s)"
        )

    def stop(self) -> None:
        """Stop the owned Chrome process.

        Only terminates the specific PID this instance created.
        Does NOT use taskkill/pkill/killall by name.
        Does NOT delete the persistent profile.
        """
        if self._process is not None:
            self._cleanup_owned_process()
        self._process = None
        self._cdp_port = None
        self._cdp_ws_path = None

    def disconnect(self) -> None:
        """Disconnect Playwright without killing the Chrome process.

        Call this before stop() when you have a Playwright connection.
        After this, call stop() to terminate the owned process.
        """
        pass  # Playwright-side disconnect is handled by caller

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_devtools_active_port(self, path: Path) -> None:
        """Parse DevToolsActivePort file.

        Format:
            line 0: TCP port (integer)
            line 1: browser websocket path (string)

        Raises:
            RawChromeStartupError: If format is invalid or port is out of range.
        """
        text = path.read_text(encoding="utf-8").strip()
        lines = text.splitlines()

        if len(lines) < 2:
            raise RawChromeStartupError(
                f"Malformed DevToolsActivePort: expected 2 lines, got {len(lines)}"
            )

        try:
            port = int(lines[0].strip())
        except ValueError:
            raise RawChromeStartupError(
                f"Malformed DevToolsActivePort: port not an integer: {lines[0]!r}"
            )

        if port < 1 or port > self.REASONABLE_MAX_PORT:
            raise RawChromeStartupError(
                f"DevToolsActivePort port out of range 1..{self.REASONABLE_MAX_PORT}: {port}"
            )

        ws_path = lines[1].strip()

        self._cdp_port = port
        self._cdp_ws_path = ws_path

        # Do NOT log the full websocket path (contains temporary token)
        logger.debug(
            "DevToolsActivePort parsed: port=%d ws_path_len=%d",
            port,
            len(ws_path),
        )

    def _cleanup_owned_process(self) -> None:
        """Terminate only the owned Chrome process by PID.

        Does NOT use taskkill/pkill/killall by name.
        """
        if self._process is None:
            return

        try:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "Chrome PID %d did not terminate in 5s, killing",
                        self._process.pid,
                    )
                    self._process.kill()
                    self._process.wait(timeout=3)
        except Exception:
            logger.exception("Error during Chrome process cleanup")

    def _read_stderr_safe(self) -> str:
        """Read buffered stderr from the Chrome process safely."""
        try:
            if self._process and self._process.stderr:
                raw = self._process.stderr.read(4096)
                return raw.decode("utf-8", errors="replace").strip()
        except Exception:
            pass
        return ""