from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from hermes_screencast.editor_server import create_editor_server
from hermes_screencast.project import create_hermes_project


def create_project(tmp_path):
    video = tmp_path / "source.mp4"
    events = tmp_path / "events.json"
    script = tmp_path / "script.json"
    video.write_bytes(b"fake mp4")
    events.write_text(json.dumps({
        "schema": "hermes.recording.events.v1",
        "metadata": {"width": 1920, "height": 1080},
        "events": [{"sequence": 0, "time_seconds": 2, "type": "recording_finished"}],
    }), encoding="utf-8")
    script.write_text(json.dumps({
        "title": "HTTP Editor", "steps": [
            {"action": "goto", "url": "https://example.com"},
            {"action": "wait", "seconds": 1},
        ],
    }), encoding="utf-8")
    root = tmp_path / "editor.hermes"
    create_hermes_project(
        root, title="HTTP Editor", video_file=video, events_file=events,
        script_file=script, video_verifier=lambda path: path,
    )
    return root


@pytest.fixture
def editor_url(tmp_path):
    server = create_editor_server(create_project(tmp_path), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request_json(url, *, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read())


def test_editor_serves_ui_and_project_snapshot(editor_url) -> None:
    with urllib.request.urlopen(editor_url + "/", timeout=3) as response:
        markup = response.read().decode("utf-8")
        assert "Hermes Editor" in markup
        assert "Save project" in markup
        assert response.headers["Cache-Control"] == "no-store"
    status, snapshot = request_json(editor_url + "/api/project")
    assert status == 200
    assert snapshot["project"]["title"] == "HTTP Editor"
    assert len(snapshot["etag"]) == 64


def test_editor_http_save_and_stale_conflict(editor_url) -> None:
    _, snapshot = request_json(editor_url + "/api/project")
    update = {
        "etag": snapshot["etag"],
        "composition": snapshot["project"]["composition"],
        "timeline": snapshot["project"]["timeline"],
    }
    update["composition"]["background"] = {
        "type": "color", "value": "#123456",
    }
    status, saved = request_json(
        editor_url + "/api/project", method="PUT", payload=update
    )
    assert status == 200
    assert saved["project"]["composition"]["background"]["value"] == "#123456"
    with pytest.raises(urllib.error.HTTPError) as exc:
        request_json(editor_url + "/api/project", method="PUT", payload=update)
    assert exc.value.code == 409


def test_editor_rejects_non_loopback_bind(tmp_path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        create_editor_server(create_project(tmp_path), host="0.0.0.0")
