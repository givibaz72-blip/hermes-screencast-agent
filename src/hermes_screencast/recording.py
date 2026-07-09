import os
import subprocess
import time
from pathlib import Path


DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_DISPLAY = ":99"


def start_xvfb(
    display: str = DEFAULT_DISPLAY,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> subprocess.Popen:
    proc = subprocess.Popen([
        "Xvfb",
        display,
        "-screen",
        "0",
        f"{width}x{height}x24",
        "-ac",
        "-nocursor",
    ])

    time.sleep(1)

    os.environ["DISPLAY"] = display

    subprocess.Popen([
        "unclutter",
        "-display",
        display,
        "-idle",
        "0",
        "-root",
    ])

    time.sleep(0.3)

    subprocess.run(
        ["xdotool", "mousemove", "9999", "9999"],
        env={**os.environ, "DISPLAY": display},
        capture_output=True,
        check=False,
    )

    return proc


def start_recording(
    output_file: str | Path,
    display: str = DEFAULT_DISPLAY,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> subprocess.Popen:
    proc = subprocess.Popen([
        "ffmpeg",
        "-y",
        "-f",
        "x11grab",
        "-r",
        "30",
        "-s",
        f"{width}x{height}",
        "-i",
        f"{display}.0",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        str(output_file),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    time.sleep(2)

    return proc
