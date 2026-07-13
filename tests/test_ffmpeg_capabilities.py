from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_screencast.renderer import (
    MissingFFmpegFiltersError,
    ensure_ffmpeg_filter_capabilities,
    probe_ffmpeg_filters,
    required_ffmpeg_filters,
)


def test_probe_ffmpeg_filters_parses_filter_listing() -> None:
    def runner(command, **kwargs):
        assert command == ["custom-ffmpeg", "-hide_banner", "-filters"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        assert kwargs["timeout"] == 8
        return SimpleNamespace(
            returncode=0,
            stdout=(
                " T. drawbox V->V Draw a colored box\n"
                " .. drawvg V->V Draw vector graphics\n"
                " TS overlay VV->V Overlay video\n"
            ),
            stderr="",
        )

    assert probe_ffmpeg_filters(
        "custom-ffmpeg",
        runner=runner,
    ) == frozenset({"drawbox", "drawvg", "overlay"})


def test_probe_ffmpeg_filters_reports_missing_executable() -> None:
    def runner(command, **kwargs):
        raise FileNotFoundError(command[0])

    with pytest.raises(
        RuntimeError,
        match="custom-ffmpeg.*required to inspect filters",
    ):
        probe_ffmpeg_filters("custom-ffmpeg", runner=runner)


def test_required_ffmpeg_filters_detects_drawvg() -> None:
    assert required_ffmpeg_filters(
        "[0:v]drawvg=script='circle 1 1 1'[outv]"
    ) == ("drawvg",)
    assert required_ffmpeg_filters(
        "[0:v]drawtext=text='hello'[outv]"
    ) == ()


def test_missing_required_filter_raises_typed_error() -> None:
    with pytest.raises(MissingFFmpegFiltersError) as captured:
        ensure_ffmpeg_filter_capabilities(
            "[0:v]drawvg=script='circle 1 1 1'[outv]",
            ffmpeg="custom-ffmpeg",
            probe=lambda executable: frozenset({"drawbox", "drawtext"}),
        )

    assert captured.value.ffmpeg == "custom-ffmpeg"
    assert captured.value.missing_filters == ("drawvg",)
    assert "missing required filters: drawvg" in str(captured.value)


def test_capability_check_does_not_probe_standard_graph() -> None:
    def unexpected_probe(executable: str) -> frozenset[str]:
        raise AssertionError("probe must not run")

    ensure_ffmpeg_filter_capabilities(
        "[0:v]drawtext=text='hello'[outv]",
        probe=unexpected_probe,
    )
