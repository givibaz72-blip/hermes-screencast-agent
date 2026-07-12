from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_screencast.project import (
    validate_hermes_project,
    validate_project_composition,
    validate_project_timeline,
)


class ProjectEditConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class EditorProjectSnapshot:
    root: Path
    etag: str
    project: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root), "etag": self.etag,
            "project": copy.deepcopy(self.project),
        }


def read_editor_project(project_directory: str | Path) -> EditorProjectSnapshot:
    root = Path(project_directory).expanduser().resolve()
    project = validate_hermes_project(root)
    manifest = root / "project.json"
    raw = manifest.read_bytes()
    return EditorProjectSnapshot(
        root=root, etag=_etag(raw), project=project.to_dict()
    )


def save_editor_project(
    project_directory: str | Path,
    *,
    composition: dict[str, Any],
    timeline: dict[str, Any],
    expected_etag: str,
) -> EditorProjectSnapshot:
    root = Path(project_directory).expanduser().resolve()
    manifest = root / "project.json"
    initial = manifest.read_bytes()
    if _etag(initial) != expected_etag:
        raise ProjectEditConflictError(
            "HermesProject changed since the editor snapshot was loaded"
        )
    validate_project_composition(composition)
    validate_project_timeline(timeline, composition=composition)
    current = validate_hermes_project(root).to_dict()
    current["composition"] = copy.deepcopy(composition)
    current["timeline"] = copy.deepcopy(timeline)
    encoded = (
        json.dumps(current, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    temporary = root / "project.json.editor.tmp"
    temporary.write_bytes(encoded)
    if _etag(manifest.read_bytes()) != expected_etag:
        temporary.unlink(missing_ok=True)
        raise ProjectEditConflictError(
            "HermesProject changed while editor changes were being saved"
        )
    temporary.replace(manifest)
    return read_editor_project(root)


def _etag(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
