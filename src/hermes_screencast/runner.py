import json
import subprocess
import sys
from pathlib import Path

from .config import OUTPUT_DIR, PYTHON, RECORDER
from .verifier import verify_mp4

VALID_MODES = {"public", "authenticated", "assisted_login"}

def run(cmd: list[str]) -> None:
    print("→", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: hermes-screencast task.json")
        raise SystemExit(1)

    task_path = Path(sys.argv[1]).expanduser().resolve()
    if not task_path.exists():
        raise FileNotFoundError(task_path)

    task = json.loads(task_path.read_text(encoding="utf-8"))
    mode = task.get("mode", "public")

    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode: {mode}")

    if not task.get("url"):
        raise ValueError("Task must include url")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    before = set(OUTPUT_DIR.glob("*.mp4"))
    run([str(PYTHON), str(RECORDER), str(task_path)])
    after = set(OUTPUT_DIR.glob("*.mp4"))

    new_files = sorted(after - before, key=lambda p: p.stat().st_mtime)
    zoomed = [p for p in new_files if p.name.endswith("_zoomed.mp4")]

    if zoomed:
        final = zoomed[-1]
    else:
        all_zoomed = sorted(OUTPUT_DIR.glob("*_zoomed.mp4"), key=lambda p: p.stat().st_mtime)
        if not all_zoomed:
            raise RuntimeError("No *_zoomed.mp4 found")
        final = all_zoomed[-1]

    verify_mp4(final)
    print(f"✅ Final screencast: {final}", flush=True)

if __name__ == "__main__":
    main()
