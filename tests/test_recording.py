from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import hermes_screencast.recording as recording


class FakeProcess:
    def __init__(self, *, timeout_on_first_wait: bool = False):
        self.return_code: int | None = None
        self.timeout_on_first_wait = timeout_on_first_wait
        self.wait_calls = 0
        self.terminate_called = False
        self.kill_called = False

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.terminate_called = True

    def kill(self) -> None:
        self.kill_called = True

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1

        if (
            self.timeout_on_first_wait
            and self.wait_calls == 1
            and not self.kill_called
        ):
            raise subprocess.TimeoutExpired("fake-process", timeout)

        self.return_code = 0
        return 0


def test_terminate_process_stops_running_process() -> None:
    process = FakeProcess()

    recording.terminate_process(process, timeout=1)

    assert process.terminate_called is True
    assert process.kill_called is False
    assert process.wait_calls == 1


def test_terminate_process_kills_process_after_timeout() -> None:
    process = FakeProcess(timeout_on_first_wait=True)

    recording.terminate_process(process, timeout=1)

    assert process.terminate_called is True
    assert process.kill_called is True
    assert process.wait_calls == 2


def test_virtual_display_starts_and_stops_processes(monkeypatch) -> None:
    created_processes: list[tuple[list[str], FakeProcess]] = []
    run_calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(command, **kwargs):
        process = FakeProcess()
        created_processes.append((command, process))
        return process

    def fake_run(command, **kwargs):
            run_calls.append((command, kwargs))
            # xdpyinfo check should raise CalledProcessError (display not in use)
            # xdotool should return success
            if command[0] == "xdpyinfo":
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(recording.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(recording.subprocess, "run", fake_run)
    monkeypatch.setattr(recording.time, "sleep", lambda _: None)
    monkeypatch.setenv("DISPLAY", ":old")

    display = recording.VirtualDisplay(
        display=":99",
        width=1920,
        height=1080,
    )

    with display:
        assert recording.os.environ["DISPLAY"] == ":99"

    # Xvfb should be started first (display not in use)
    assert created_processes[0][0] == [
        "Xvfb",
        ":99",
        "-screen",
        "0",
        "1920x1080x24",
        "-ac",
        "-nocursor",
    ]
    # unclutter should be started second
    assert created_processes[1][0][0] == "unclutter"
    # xdotool mousemove should be called
    assert run_calls[1][0] == ["xdotool", "mousemove", "9999", "9999"]

    assert created_processes[0][1].terminate_called is True
    assert created_processes[1][1].terminate_called is True


def test_screen_recorder_builds_professional_mp4_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []
    process = FakeProcess()

    def fake_popen(command, **kwargs):
        commands.append(command)
        return process

    monkeypatch.setattr(recording.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(recording.time, "sleep", lambda _: None)

    output = tmp_path / "videos" / "demo.mp4"

    with recording.ScreenRecorder(
        output_file=output,
        offset_x=12,
        offset_y=84,
    ):
        assert output.parent.exists()

    command = commands[0]

    assert command[0] == "ffmpeg"
    assert "-framerate" in command
    assert "30" in command
    assert "-video_size" in command
    assert "1920x1080" in command
    assert "-crf" in command
    assert "18" in command
    assert "-pix_fmt" in command
    assert "yuv420p" in command

    input_index = command.index("-i")
    assert command[input_index + 1] == ":99.0+12,84"

    assert command[-1] == str(output.resolve())
    assert process.terminate_called is True

def test_focus_display_point_uses_real_x11_click(
    monkeypatch,
) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(
        recording.subprocess,
        "run",
        fake_run,
    )

    recording.focus_display_point(
        x=960,
        y=500,
        display=":99",
    )

    command, options = calls[0]

    assert command == [
        "xdotool",
        "mousemove",
        "960",
        "500",
        "click",
        "1",
    ]
    assert options["env"]["DISPLAY"] == ":99"
    assert options["check"] is True
