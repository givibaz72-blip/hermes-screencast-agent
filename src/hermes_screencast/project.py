from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from hermes_screencast.demo.events import EVENT_SCHEMA
from hermes_screencast.demo.json_loader import load_demo_script
from hermes_screencast.verifier import verify_mp4


PROJECT_SCHEMA = "hermes.project.v1"
REQUIRED_ASSETS = {"video", "events", "script"}


@dataclass(frozen=True)
class ProjectAsset:
    path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size_bytes": self.size_bytes, "sha256": self.sha256}


@dataclass(frozen=True)
class HermesProject:
    title: str
    assets: dict[str, ProjectAsset]
    composition: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PROJECT_SCHEMA,
            "title": self.title,
            "assets": {name: asset.to_dict() for name, asset in sorted(self.assets.items())},
            "composition": dict(self.composition),
            "timeline": {"tracks": []},
        }


def create_hermes_project(
    project_directory: str | Path,
    *,
    title: str,
    video_file: str | Path,
    events_file: str | Path,
    script_file: str | Path,
    video_verifier: Callable[[Path], Path] = verify_mp4,
) -> Path:
    if not title.strip():
        raise ValueError("HermesProject title cannot be empty")
    root = Path(project_directory).expanduser().resolve()
    manifest_path = root / "project.json"
    if manifest_path.exists():
        raise FileExistsError(f"HermesProject already exists: {manifest_path}")

    video = _existing_file(video_file, "video")
    events = _existing_file(events_file, "events")
    script = _existing_file(script_file, "script")
    video_verifier(video)
    _validate_events_file(events)
    load_demo_script(script)

    destinations = {
        "video": (video, PurePosixPath("assets/source.mp4")),
        "events": (events, PurePosixPath("events/recording.events.json")),
        "script": (script, PurePosixPath("script/demo.json")),
    }
    assets: dict[str, ProjectAsset] = {}
    for name, (source, relative) in destinations.items():
        destination = root / Path(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        assets[name] = _asset_for_file(destination, relative.as_posix())

    project = HermesProject(
        title=title,
        assets=assets,
        composition={
            "canvas": {"width": 1920, "height": 1080},
            "background": {"type": "color", "value": "#111827"},
            "frame": {"padding": 0, "corner_radius": 0, "shadow": False},
        },
    )
    root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(project.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    validate_hermes_project(root)
    return manifest_path


def load_hermes_project(project_directory: str | Path) -> HermesProject:
    root = Path(project_directory).expanduser().resolve()
    manifest = root / "project.json"
    if not manifest.exists():
        raise FileNotFoundError(manifest)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != PROJECT_SCHEMA:
        raise ValueError(f"HermesProject must use schema {PROJECT_SCHEMA}")
    if set(payload) - {"schema", "title", "assets", "composition", "timeline"}:
        raise ValueError("HermesProject contains unknown top-level fields")
    title = payload.get("title")
    assets_payload = payload.get("assets")
    composition = payload.get("composition")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("HermesProject requires non-empty title")
    if not isinstance(assets_payload, dict) or not REQUIRED_ASSETS.issubset(assets_payload):
        raise ValueError("HermesProject requires video, events, and script assets")
    if not isinstance(composition, dict):
        raise ValueError("HermesProject composition must be an object")
    assets = {name: _asset_from_dict(name, value) for name, value in assets_payload.items()}
    return HermesProject(title=title, assets=assets, composition=composition)


def validate_hermes_project(project_directory: str | Path) -> HermesProject:
    root = Path(project_directory).expanduser().resolve()
    project = load_hermes_project(root)
    resolved: dict[str, Path] = {}
    for name, asset in project.assets.items():
        path = _resolve_relative_asset(root, asset.path)
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != asset.size_bytes:
            raise ValueError(f"HermesProject asset size mismatch: {name}")
        if _sha256(path) != asset.sha256:
            raise ValueError(f"HermesProject asset checksum mismatch: {name}")
        resolved[name] = path
    _validate_events_file(resolved["events"])
    load_demo_script(resolved["script"])
    return project


def _asset_from_dict(name: str, payload: Any) -> ProjectAsset:
    if not isinstance(payload, dict) or set(payload) != {"path", "size_bytes", "sha256"}:
        raise ValueError(f"HermesProject asset is invalid: {name}")
    path, size, digest = payload["path"], payload["size_bytes"], payload["sha256"]
    if not isinstance(path, str) or not isinstance(size, int) or size < 0:
        raise ValueError(f"HermesProject asset is invalid: {name}")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"HermesProject asset checksum is invalid: {name}")
    _validate_relative_path(path)
    return ProjectAsset(path=path, size_bytes=size, sha256=digest)


def _resolve_relative_asset(root: Path, value: str) -> Path:
    _validate_relative_path(value)
    resolved = (root / Path(*PurePosixPath(value).parts)).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("HermesProject asset escapes project directory")
    return resolved


def _validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"HermesProject asset path must be safe and relative: {value}")


def _existing_file(value: str | Path, name: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"HermesProject {name} file not found: {path}")
    return path


def _validate_events_file(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != EVENT_SCHEMA:
        raise ValueError(f"Recording events must use schema {EVENT_SCHEMA}")
    if not isinstance(payload.get("events"), list):
        raise ValueError("Recording events must contain events list")


def _asset_for_file(path: Path, relative: str) -> ProjectAsset:
    return ProjectAsset(path=relative, size_bytes=path.stat().st_size, sha256=_sha256(path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
