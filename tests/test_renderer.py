from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import hermes_screencast.renderer as renderer_module
from hermes_screencast.annotations import add_project_annotation
from hermes_screencast.auto_edit import apply_auto_edit
from hermes_screencast.auto_zoom import apply_auto_zoom
from hermes_screencast.cursor_motion import apply_cursor_motion
from hermes_screencast.framing import apply_framing_preset
from hermes_screencast.project import create_hermes_project
from hermes_screencast.renderer import (
    UnsupportedRenderTracksError,
    build_render_plan,
    render_hermes_project,
)


def create_project(tmp_path):
    root = tmp_path / "demo.hermes"
    video = tmp_path / "demo.mp4"
    events = tmp_path / "demo.events.json"
    script = tmp_path / "demo.json"
    video.write_bytes(b"fake mp4")
    events.write_text(json.dumps({
        "schema": "hermes.recording.events.v1",
        "metadata": {"width": 1920, "height": 1080},
        "events": [
            {"sequence": 0, "time_seconds": 0, "type": "recording_started"},
            {"sequence": 1, "time_seconds": 0.5, "type": "step_started", "action": "click", "step_index": 0},
            {"sequence": 2, "time_seconds": 0.8, "type": "step_completed", "action": "click", "step_index": 0,
             "data": {"cursor": {"x": 1460, "y": 630},
                      "target": {"x": 1400, "y": 600, "width": 120, "height": 60}}},
            {"sequence": 3, "time_seconds": 6.0, "type": "step_started", "action": "click", "step_index": 1},
            {"sequence": 4, "time_seconds": 6.3, "type": "step_completed", "action": "click", "step_index": 1,
             "data": {"cursor": {"x": 420, "y": 320},
                      "target": {"x": 380, "y": 290, "width": 80, "height": 60}}},
            {"sequence": 5, "time_seconds": 8.0, "type": "recording_finished"},
        ],
    }), encoding="utf-8")
    script.write_text(json.dumps({
        "title": "Demo", "steps": [
            {"action": "goto", "url": "https://example.com"},
            {"action": "click", "selector": "#one"},
        ],
    }), encoding="utf-8")
    create_hermes_project(
        root, title="Demo", video_file=video, events_file=events,
        script_file=script, video_verifier=lambda path: path,
    )
    return root


def test_render_plan_applies_time_edits_and_studio_composition(tmp_path) -> None:
    root = create_project(tmp_path)
    apply_auto_edit(root)
    apply_framing_preset(root, preset="studio")
    plan = build_render_plan(root, tmp_path / "output.mp4")

    graph = plan.filter_complex
    assert "trim=start=" in graph
    assert "concat=n=" in graph
    assert "gradients=s=1920x1080" in graph
    assert "scale=1728:888" in graph
    assert "geq=r='r(X,Y)'" in graph
    assert "gblur=sigma=16.000" in graph
    assert "overlay=96:96" in graph
    assert plan.command[0] == "ffmpeg"
    assert plan.command[-1] == str((tmp_path / "output.mp4").resolve())
    assert plan.estimated_duration_seconds < 8


def test_render_plan_supports_solid_source_composition(tmp_path) -> None:
    root = create_project(tmp_path)
    plan = build_render_plan(root, tmp_path / "output.mp4")
    assert "color=c=#111827:s=1920x1080" in plan.filter_complex
    assert "setpts=PTS-STARTPTS[timed]" in plan.filter_complex
    assert "gradients=" not in plan.filter_complex


def test_render_applies_camera_zoom_before_time_edits(tmp_path) -> None:
    root = create_project(tmp_path)
    apply_auto_zoom(root)
    apply_auto_edit(root)
    plan = build_render_plan(root, tmp_path / "output.mp4")

    graph = plan.filter_complex
    assert "fps=30,zoompan=z='if(between(on," in graph
    assert ":d=1:s=1920x1080:fps=30[camera]" in graph
    assert "[camera]trim=start=" in graph
    assert graph.index("zoompan=") < graph.index("trim=start=")
    assert plan.unsupported_tracks == ()


def test_render_applies_cursor_before_camera_and_time_edits(tmp_path) -> None:
    root = create_project(tmp_path)
    apply_cursor_motion(root)
    apply_auto_zoom(root)
    apply_auto_edit(root)
    plan = build_render_plan(
        root,
        tmp_path / "output.mp4",
        filter_probe=lambda executable: frozenset({"drawvg"}),
    )

    graph = plan.filter_complex
    assert plan.vector_backend == "drawvg"
    assert "[cursor_sprite]" in graph
    assert "geq=r='if(between(Y,5,28)" in graph
    assert "[0:v]drawvg=script='if (between(t,0.800000,1.150000))" in graph
    assert "circle 1460.000000 630.000000" in graph
    assert "setrgba 1 1 1 (0.8*(1-" in graph
    assert "[cursor_clicks][cursor_sprite]overlay=x='if(lt(t," in graph
    assert "[cursor]fps=30,zoompan=" in graph
    assert "[camera]trim=start=" in graph
    assert graph.index("[cursor_sprite]") < graph.index("zoompan=")
    assert graph.index("zoompan=") < graph.index("trim=start=")
    assert plan.unsupported_tracks == ()


def test_render_applies_all_annotation_kinds_after_composition(tmp_path) -> None:
    root = create_project(tmp_path)
    add_project_annotation(
        root,
        kind="box",
        start_seconds=1,
        end_seconds=2,
        x=100,
        y=100,
        width=300,
        height=200,
    )
    add_project_annotation(
        root, kind="highlight", start_seconds=2, end_seconds=3,
        x=500, y=120, width=240, height=100,
    )
    add_project_annotation(
        root, kind="arrow", start_seconds=3, end_seconds=4,
        x=80, y=80, to_x=420, to_y=320,
    )
    add_project_annotation(
        root, kind="text", start_seconds=1, end_seconds=4,
        x=120, y=60, text="Important: action",
    )
    plan = build_render_plan(
        root,
        tmp_path / "output.mp4",
        filter_probe=lambda executable: frozenset({"drawvg"}),
    )

    graph = plan.filter_complex
    assert plan.vector_backend == "drawvg"
    assert "format=rgba[composed]" in graph
    assert "drawvg=script='if (between(t,1,2))" in graph
    assert "setlinejoin round stroke" in graph
    assert "setlinecap round" in graph
    assert "drawtext=text='Important\\: action'" in graph
    assert "enable='between(t,1,4)'" in graph
    assert graph.index("[composed]") < graph.index("drawvg=")
    assert graph.index("drawvg=") < graph.index("drawtext=")
    assert plan.unsupported_tracks == ()



def test_render_uses_portable_click_feedback_without_drawvg(tmp_path) -> None:
    root = create_project(tmp_path)
    apply_cursor_motion(root)
    apply_auto_zoom(root)
    apply_auto_edit(root)

    plan = build_render_plan(
        root,
        tmp_path / "output.mp4",
        filter_probe=lambda executable: frozenset(
            {"drawbox", "drawtext", "geq", "overlay"}
        ),
    )

    graph = plan.filter_complex
    assert plan.vector_backend == "portable"
    assert "drawvg=" not in graph
    assert "cursor_click_layer_0" in graph
    assert "between(T,0.800000,1.150000)" in graph
    assert "hypot(X-1460.000000,Y-630.000000)" in graph
    assert "[cursor_clicks_1][cursor_sprite]overlay=" in graph
    assert graph.index("cursor_click_layer_0") < graph.index("zoompan=")


def test_render_uses_portable_annotations_without_drawvg(tmp_path) -> None:
    root = create_project(tmp_path)
    add_project_annotation(
        root,
        kind="box",
        start_seconds=1,
        end_seconds=2,
        x=100,
        y=100,
        width=300,
        height=200,
    )
    add_project_annotation(
        root,
        kind="highlight",
        start_seconds=2,
        end_seconds=3,
        x=500,
        y=120,
        width=240,
        height=100,
    )
    add_project_annotation(
        root,
        kind="arrow",
        start_seconds=3,
        end_seconds=4,
        x=80,
        y=80,
        to_x=420,
        to_y=320,
    )
    add_project_annotation(
        root,
        kind="text",
        start_seconds=1,
        end_seconds=4,
        x=120,
        y=60,
        text="Important: action",
    )

    plan = build_render_plan(
        root,
        tmp_path / "output.mp4",
        filter_probe=lambda executable: frozenset(
            {"drawbox", "drawtext", "geq", "overlay"}
        ),
    )

    graph = plan.filter_complex
    assert plan.vector_backend == "portable"
    assert "drawvg=" not in graph
    assert "drawbox=x=100.000000:y=100.000000" in graph
    assert "t=4.000000:enable='between(t,1.000000,2.000000)'" in graph
    assert "t=fill:enable='between(t,2.000000,3.000000)'" in graph
    assert "annotation_arrow_layer_2" in graph
    assert "between(T,3.000000,4.000000)" in graph
    assert "drawtext=text='Important\\: action'" in graph
    assert graph.index("annotation_arrow_layer_2") < graph.index("drawtext=")

def test_render_keeps_audio_synchronized_with_time_edits(tmp_path) -> None:
    root = create_project(tmp_path)
    apply_auto_edit(root)
    plan = build_render_plan(
        root, tmp_path / "output.mp4", audio_probe=lambda path: True
    )

    assert "[0:a]atrim=start=" in plan.filter_complex
    assert "atempo=4.000000" in plan.filter_complex
    assert "concat=n=" in plan.filter_complex
    assert "[outa]" in plan.command
    assert "aac" in plan.command
    assert plan.has_audio is True


def test_render_auto_selects_first_available_hardware_encoder(tmp_path) -> None:
    root = create_project(tmp_path)
    checked = []

    def probe(encoder):
        checked.append(encoder)
        return encoder == "h264_qsv"

    plan = build_render_plan(
        root, tmp_path / "output.mp4", video_encoder="auto",
        encoder_probe=probe,
    )
    assert checked == ["h264_nvenc", "h264_qsv"]
    assert plan.video_encoder == "h264_qsv"
    assert "-global_quality" in plan.command


def test_render_auto_falls_back_to_software_encoder(tmp_path) -> None:
    root = create_project(tmp_path)
    plan = build_render_plan(
        root, tmp_path / "output.mp4", video_encoder="auto",
        encoder_probe=lambda encoder: False,
    )
    assert plan.video_encoder == "libx264"
    assert "-crf" in plan.command


def test_render_auto_benchmark_requires_meaningful_speedup(
    tmp_path, monkeypatch
) -> None:
    root = create_project(tmp_path)
    scores = {
        "libx264": 1.0, "h264_nvenc": 0.95,
        "h264_qsv": 0.7, "h264_amf": float("inf"),
    }
    monkeypatch.setattr(
        renderer_module, "_encoder_benchmark", lambda encoder: scores[encoder]
    )
    plan = build_render_plan(
        root, tmp_path / "output.mp4", video_encoder="auto"
    )
    assert plan.video_encoder == "h264_qsv"


def test_render_applies_synchronized_video_and_audio_fades(tmp_path) -> None:
    root = create_project(tmp_path)
    plan = build_render_plan(root, tmp_path / "output.mp4", audio_probe=lambda path: True, fade_in_seconds=0.25, fade_out_seconds=0.5)
    assert "[outv]fade=t=in:st=0:d=0.250000,fade=t=out:st=7.500000:d=0.500000[fadedv]" in plan.filter_complex
    assert "[outa]afade=t=in:st=0:d=0.250000,afade=t=out:st=7.500000:d=0.500000[fadeda]" in plan.filter_complex
    assert "[fadedv]" in plan.command and "[fadeda]" in plan.command


def test_render_rejects_fades_longer_than_output(tmp_path) -> None:
    root = create_project(tmp_path)
    with pytest.raises(ValueError, match="fit within"):
        build_render_plan(root, tmp_path / "output.mp4", fade_in_seconds=5, fade_out_seconds=4)


def test_render_normalizes_audio_before_final_fades(tmp_path) -> None:
    root = create_project(tmp_path)
    plan = build_render_plan(root, tmp_path / "output.mp4", audio_probe=lambda path: True, normalize_audio=True, fade_out_seconds=0.5)
    graph = plan.filter_complex
    assert "[outa]loudnorm=I=-16:LRA=11:TP=-1.5,aresample=48000[audionorm]" in graph
    assert "[audionorm]afade=t=out:st=7.500000:d=0.500000[fadeda]" in graph
    assert graph.index("loudnorm=") < graph.index("afade=")
    assert plan.normalize_audio is True


@pytest.mark.parametrize(("profile", "preset", "quality"), [
    ("draft", "veryfast", "28"),
    ("balanced", "fast", "22"),
    ("high", "medium", "18"),
    ("archive", "slow", "14"),
])
def test_render_software_quality_profiles(tmp_path, profile, preset, quality) -> None:
    root = create_project(tmp_path)
    plan = build_render_plan(root, tmp_path / "output.mp4", quality_profile=profile)
    assert plan.quality_profile == profile
    assert plan.command[plan.command.index("-preset") + 1] == preset
    assert plan.command[plan.command.index("-crf") + 1] == quality


def test_render_executes_ffmpeg_and_verifies_output(tmp_path) -> None:
    root = create_project(tmp_path)
    output = tmp_path / "output.mp4"
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        output.write_bytes(b"rendered")
        return SimpleNamespace(returncode=0, stderr="")

    verified = []
    result = render_hermes_project(
        root, output, runner=fake_runner, verifier=lambda path: verified.append(path) or path,
    )
    assert result == output.resolve()
    assert calls[0][0][0] == "ffmpeg"
    assert verified == [output.resolve()]


def test_render_reports_ffmpeg_failure(tmp_path) -> None:
    root = create_project(tmp_path)
    with pytest.raises(RuntimeError, match="encoder failed"):
        render_hermes_project(
            root, tmp_path / "output.mp4",
            runner=lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="encoder failed"),
        )


def test_render_rejects_unsafe_output_choices(tmp_path) -> None:
    root = create_project(tmp_path)
    with pytest.raises(ValueError, match=".mp4"):
        build_render_plan(root, tmp_path / "output.mov")
    with pytest.raises(ValueError, match="source MP4"):
        build_render_plan(root, root / "assets" / "source.mp4")
