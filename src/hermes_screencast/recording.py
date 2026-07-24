from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_DISPLAY = ":99"
DEFAULT_FPS = 30
DEFAULT_CRF = 18
PROCESS_STOP_TIMEOUT = 5.0


def focus_display_point(
    x: int,
    y: int,
    display: str = DEFAULT_DISPLAY,
) -> None:
    """Move focus from browser chrome to the recorded page."""
    environment = {
        **os.environ,
        "DISPLAY": display,
    }

    subprocess.run(
        [
            "xdotool",
            "mousemove",
            str(x),
            str(y),
            "click",
            "1",
        ],
        env=environment,
        capture_output=True,
        check=True,
    )


def terminate_process(
    process: subprocess.Popen | None,
    timeout: float = PROCESS_STOP_TIMEOUT,
) -> None:
    """Terminate a child process and kill it if graceful shutdown times out."""
    if process is None or process.poll() is not None:
        return

    process.terminate()

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


@dataclass
class VirtualDisplay:
    """Manage the Xvfb display used by the visible Chromium browser.

    Tracks whether this instance owns the Xvfb process so it doesn't
    terminate an externally managed display on close.
    """

    display: str = DEFAULT_DISPLAY
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    startup_delay: float = 1.0

    process: subprocess.Popen | None = field(default=None, init=False)
    cursor_hider: subprocess.Popen | None = field(default=None, init=False)
    _owns_display: bool = field(default=False, init=False)

    def start(self) -> "VirtualDisplay":
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("Virtual display is already running")

        # Check if display is already available (e.g., Xvfb started externally)
        env = {**os.environ, "DISPLAY": self.display}
        try:
            subprocess.run(
                ["xdpyinfo"],
                env=env,
                capture_output=True,
                check=True,
                timeout=2,
            )
            # Display already exists, don't start Xvfb
            os.environ["DISPLAY"] = self.display
            self.cursor_hider = subprocess.Popen(
                [
                    "unclutter",
                    "-display",
                    self.display,
                    "-idle",
                    "0",
                    "-root",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._owns_display = False
            return self
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            # Display not available, start Xvfb
            pass

        self.process = subprocess.Popen(
            [
                "Xvfb",
                self.display,
                "-screen",
                "0",
                f"{self.width}x{self.height}x24",
                "-ac",
                "-nocursor",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            time.sleep(self.startup_delay)

            if self.process.poll() is not None:
                stderr = self.process.stderr.read().decode() if self.process.stderr else ""
                stdout = self.process.stdout.read().decode() if self.process.stdout else ""
                raise RuntimeError(
                    f"Xvfb exited before display {self.display} became ready\n"
                    f"stdout: {stdout}\nstderr: {stderr}"
                )

            os.environ["DISPLAY"] = self.display
            self._owns_display = True

            self.cursor_hider = subprocess.Popen(
                [
                    "unclutter",
                    "-display",
                    self.display,
                    "-idle",
                    "0",
                    "-root",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            subprocess.run(
                ["xdotool", "mousemove", "9999", "9999"],
                env={**os.environ, "DISPLAY": self.display},
                capture_output=True,
                check=False,
            )
        except BaseException:
            self.close()
            raise

        return self

    def close(self) -> None:
        terminate_process(self.cursor_hider)
        self.cursor_hider = None

        # Only terminate Xvfb if we own it
        if self._owns_display:
            terminate_process(self.process)
        self.process = None
        self._owns_display = False

    def __enter__(self) -> "VirtualDisplay":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


@dataclass
class ScreenRecorder:
    """Record an X11 display into an MP4 file using FFmpeg."""

    output_file: str | Path
    display: str = DEFAULT_DISPLAY
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    offset_x: int = 0
    offset_y: int = 0
    fps: int = DEFAULT_FPS
    crf: int = DEFAULT_CRF
    startup_delay: float = 0.5

    process: subprocess.Popen | None = field(default=None, init=False)

    @property
    def output_path(self) -> Path:
        return Path(self.output_file).expanduser().resolve()

    def start(self) -> "ScreenRecorder":
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("Screen recording is already running")

        output_path = self.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.process = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-loglevel",
                "error",
                "-f",
                "x11grab",
                "-framerate",
                str(self.fps),
                "-video_size",
                f"{self.width}x{self.height}",
                "-i",
                (
                    f"{self.display}.0+"
                    f"{self.offset_x},{self.offset_y}"
                ),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                str(self.crf),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        time.sleep(self.startup_delay)

        if self.process.poll() is not None:
            self.process = None
            raise RuntimeError("FFmpeg exited before screen recording started")

        return self

    def close(self) -> None:
        terminate_process(self.process)
        self.process = None

    def __enter__(self) -> "ScreenRecorder":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def start_xvfb(
    display: str = DEFAULT_DISPLAY,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> subprocess.Popen:
    """Legacy-compatible helper. Prefer VirtualDisplay for new code."""
    session = VirtualDisplay(
        display=display,
        width=width,
        height=height,
    ).start()

    if session.process is None:
        raise RuntimeError("Xvfb failed to start")

    return session.process


def start_recording(
    output_file: str | Path,
    display: str = DEFAULT_DISPLAY,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> subprocess.Popen:
    """Legacy-compatible helper. Prefer ScreenRecorder for new code."""
    recorder = ScreenRecorder(
        output_file=output_file,
        display=display,
        width=width,
        height=height,
    ).start()

    if recorder.process is None:
        raise RuntimeError("FFmpeg failed to start")

    return recorder.process
