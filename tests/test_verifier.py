from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import hermes_screencast.verifier as verifier
from hermes_screencast.verifier import (
    VerificationError,
    verify_mp4,
)


def completed_probe(
    payload: dict,
    *,
    returncode: int = 0,
    stderr: str = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ffprobe"],
        returncode=returncode,
        stdout=json.dumps(payload),
        stderr=stderr,
    )


def test_missing_mp4_fails(tmp_path: Path) -> None:
    with pytest.raises(
        VerificationError,
        match="MP4 not found",
    ):
        verify_mp4(tmp_path / "missing.mp4")


def test_explicit_minimum_size_is_respected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "small.mp4"
    path.write_bytes(b"1234")

    with pytest.raises(
        VerificationError,
        match="MP4 too small",
    ):
        verify_mp4(path, min_size=5)


def test_valid_small_static_mp4_passes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "static-demo.mp4"
    path.write_bytes(b"valid-small-video")

    def fake_run(command, **kwargs):
        return completed_probe(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                        "duration": "7.066667",
                    }
                ],
                "format": {
                    "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                    "duration": "7.066667",
                },
            }
        )

    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        fake_run,
    )

    assert verify_mp4(path) == path.resolve()


def test_mp4_without_video_stream_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "audio-only.mp4"
    path.write_bytes(b"audio-only")

    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda command, **kwargs: completed_probe(
            {
                "streams": [],
                "format": {
                    "duration": "5.0",
                },
            }
        ),
    )

    with pytest.raises(
        VerificationError,
        match="contains no video stream",
    ):
        verify_mp4(path)


def test_unreadable_mp4_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "broken.mp4"
    path.write_bytes(b"not-an-mp4")

    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda command, **kwargs: completed_probe(
            {},
            returncode=1,
            stderr="Invalid data found",
        ),
    )

    with pytest.raises(
        VerificationError,
        match="MP4 cannot be read",
    ):
        verify_mp4(path)
