from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class VerificationError(RuntimeError):
    pass


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    return parsed if parsed > 0 else None


def verify_mp4(
    path: Path,
    min_size: int = 1,
) -> Path:
    """
    Verify that a file is a readable MP4 containing a valid video stream.

    File size alone is not a reliable quality check because short recordings
    with mostly static content can be very small while remaining fully valid.
    """
    video_path = path.expanduser().resolve()

    if not video_path.exists():
        raise VerificationError(f"MP4 not found: {video_path}")

    if not video_path.is_file():
        raise VerificationError(f"MP4 path is not a file: {video_path}")

    file_size = video_path.stat().st_size

    if file_size < min_size:
        raise VerificationError(
            f"MP4 too small: {video_path} ({file_size} bytes)"
        )

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        (
            "stream=codec_type,codec_name,width,height,duration:"
            "format=format_name,duration"
        ),
        "-of",
        "json",
        str(video_path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise VerificationError(
            "ffprobe is required to verify MP4 files"
        ) from exc

    if result.returncode != 0:
        error = result.stderr.strip() or "unknown ffprobe error"
        raise VerificationError(
            f"MP4 cannot be read: {video_path}: {error}"
        )

    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VerificationError(
            f"Invalid ffprobe response for MP4: {video_path}"
        ) from exc

    streams = metadata.get("streams")

    if not isinstance(streams, list) or not streams:
        raise VerificationError(
            f"MP4 contains no video stream: {video_path}"
        )

    video_stream = streams[0]

    try:
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
    except (TypeError, ValueError) as exc:
        raise VerificationError(
            f"MP4 has invalid video dimensions: {video_path}"
        ) from exc

    if width <= 0 or height <= 0:
        raise VerificationError(
            f"MP4 has invalid video dimensions: {video_path}"
        )

    format_metadata = metadata.get("format")
    format_duration = None

    if isinstance(format_metadata, dict):
        format_duration = _positive_float(
            format_metadata.get("duration")
        )

    stream_duration = _positive_float(
        video_stream.get("duration")
    )

    if format_duration is None and stream_duration is None:
        raise VerificationError(
            f"MP4 has no positive duration: {video_path}"
        )

    return video_path
