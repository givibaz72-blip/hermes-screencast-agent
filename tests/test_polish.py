from pathlib import Path

import pytest

import hermes_screencast.polish as polish_module
from hermes_screencast.polish import _fit_fades, polish_hermes_project


def test_polish_runs_complete_workflow_in_order(tmp_path, monkeypatch) -> None:
    calls = []
    root = tmp_path / "demo.hermes"
    output = tmp_path / "final.mp4"

    monkeypatch.setattr(polish_module, "apply_framing_preset", lambda path, **kwargs: calls.append(("framing", kwargs)))
    monkeypatch.setattr(polish_module, "apply_auto_zoom", lambda path: calls.append(("zoom", {})) or {"segments": [1, 2]})
    monkeypatch.setattr(polish_module, "apply_cursor_motion", lambda path: calls.append(("cursor", {})) or {"segments": [1]})
    monkeypatch.setattr(polish_module, "apply_auto_edit", lambda path: calls.append(("edit", {})) or {"segments": [1, 2, 3], "summary": {"estimated_duration_seconds": 8.0}})
    monkeypatch.setattr(polish_module, "write_project_preview", lambda path, target: calls.append(("preview", {"target": target})) or target)
    monkeypatch.setattr(polish_module, "render_hermes_project", lambda path, target, **kwargs: calls.append(("render", kwargs)) or Path(target))

    result = polish_hermes_project(root, output)

    assert [name for name, _ in calls] == ["framing", "zoom", "cursor", "edit", "preview", "render"]
    assert calls[0][1]["preset"] == "studio"
    assert calls[-1][1]["quality_profile"] == "high"
    assert calls[-1][1]["normalize_audio"] is True
    assert result.preview == output.with_suffix(".preview.html").resolve()
    assert (result.zoom_segments, result.cursor_segments, result.edit_segments) == (2, 1, 3)


def test_polish_scales_fades_for_very_short_output() -> None:
    fade_in, fade_out = _fit_fades(0.2, 0.3, 0.25)
    assert fade_in + fade_out == pytest.approx(0.2)
    assert fade_in == pytest.approx(0.08)
    assert fade_out == pytest.approx(0.12)


def test_polish_rejects_negative_fade() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _fit_fades(-0.1, 0.2, 4)
