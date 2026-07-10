from __future__ import annotations

import subprocess
from pathlib import Path

from .config import PYTHON, RECORDER


class RecorderAdapter:
    """
    Temporary bridge to the legacy recorder.

    BrowserRuntime owns browser logic.
    Legacy recorder still owns video capture.

    This adapter allows us to migrate gradually.
    """

    def __init__(self):
        self.python = PYTHON
        self.recorder = RECORDER

    def run(self, task: Path) -> None:
        cmd = [
            str(self.python),
            str(self.recorder),
            str(task),
        ]

        print("→", " ".join(cmd), flush=True)

        subprocess.run(
            cmd,
            check=True,
        )
