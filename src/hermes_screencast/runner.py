import argparse
import json
import subprocess
import sys
from pathlib import Path

from .config import OUTPUT_DIR, PYTHON, RECORDER
from .demo.smoke import run_smoke_demo
from .planner import make_basic_task
from .recorder_adapter import RecorderAdapter
from .verifier import verify_mp4

VALID_MODES = {"public", "authenticated", "assisted_login"}


def record_task(task_path: Path) -> Path:
    task_path = task_path.expanduser().resolve()
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
    RecorderAdapter().run(task_path)
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
    return final


def write_planned_task(args: argparse.Namespace) -> Path:
    task = make_basic_task(
        url=args.url,
        title=args.title,
        mode=args.mode,
        wait_before=args.wait_before,
        wait_after=args.wait_after,
        hover_selector=args.hover,
        click_selector=args.click,
        sync_offset=args.sync_offset,
    )

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Task written: {output}", flush=True)
    return output


def run_demo_smoke_command(args: argparse.Namespace) -> None:
    result = run_smoke_demo(
        profile=args.profile,
        headless=args.headless,
    )

    if not result.success:
        raise RuntimeError(result.error)

    print(f"✅ DemoScript executed: {result.completed_steps} steps", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-screencast")
    sub = parser.add_subparsers(dest="command")

    record = sub.add_parser("record", help="Record from an existing task JSON")
    record.add_argument("task_json")

    plan = sub.add_parser("plan", help="Create a basic task JSON")
    plan.add_argument("--url", required=True)
    plan.add_argument("--title")
    plan.add_argument("--mode", default="public", choices=sorted(VALID_MODES))
    plan.add_argument("--hover")
    plan.add_argument("--click")
    plan.add_argument("--wait-before", type=int, default=2)
    plan.add_argument("--wait-after", type=int, default=1)
    plan.add_argument("--sync-offset", type=float, default=0.3)
    plan.add_argument("--output", required=True)

    run_cmd = sub.add_parser("run", help="Create a basic task JSON and record it")
    run_cmd.add_argument("--url", required=True)
    run_cmd.add_argument("--title")
    run_cmd.add_argument("--mode", default="public", choices=sorted(VALID_MODES))
    run_cmd.add_argument("--hover")
    run_cmd.add_argument("--click")
    run_cmd.add_argument("--wait-before", type=int, default=2)
    run_cmd.add_argument("--wait-after", type=int, default=1)
    run_cmd.add_argument("--sync-offset", type=float, default=0.3)
    run_cmd.add_argument("--output", default="/tmp/hermes_screencast_task.json")

    demo_smoke = sub.add_parser("demo-smoke", help="Run the built-in DemoScript smoke test")
    demo_smoke.add_argument("--headless", action="store_true")
    demo_smoke.add_argument("--profile", default="demo-smoke")

    parser.add_argument("legacy_task_json", nargs="?")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "record":
        record_task(Path(args.task_json))
        return

    if args.command == "plan":
        write_planned_task(args)
        return

    if args.command == "run":
        task_path = write_planned_task(args)
        record_task(task_path)
        return

    if args.command == "demo-smoke":
        run_demo_smoke_command(args)
        return

    if args.legacy_task_json:
        record_task(Path(args.legacy_task_json))
        return

    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
