import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .auto_zoom import AutoZoomSettings, apply_auto_zoom
from .browser import BrowserRuntime, BrowserRuntimeConfig
from .config import OUTPUT_DIR, PYTHON, RECORDER
from .cursor_motion import CursorMotionSettings, apply_cursor_motion
from .demo.browser_executor import BrowserDemoExecutor
from .demo.discovery import PageDiscoveryService
from .demo.events import default_events_path
from .demo.json_loader import demo_script_to_dict, load_demo_script
from .demo.planner import DemoDryRunPlanner
from .demo.recording import record_demo_script
from .demo.runner import DemoRunner
from .demo.scenario_planner import (
    CommandScenarioProvider,
    ScenarioPlanner,
    ScenarioPlanningRequest,
)
from .demo.smoke import run_smoke_demo
from .framing import (
    apply_framing_preset,
    available_framing_presets,
)
from .planner import make_basic_task
from .project import create_hermes_project, validate_hermes_project
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


def build_demo_template() -> dict:
    return {
        "title": "Hermes demo",
        "target": {
            "kind": "web",
            "url": "https://example.com",
        },
        "preferences": {
            "resolution": "1080p",
            "cursor_speed": "natural",
            "highlight_style": "subtle",
            "marker_colors": ["yellow", "blue"],
            "pacing": "professional",
        },
        "metadata": {
            "schema": "hermes.demo.v1",
        },
        "steps": [
            {
                "action": "goto",
                "url": "https://example.com",
            },
            {
                "action": "wait",
                "seconds": 1,
            },
            {
                "action": "narration",
                "text": "Hermes is executing a DemoScript from JSON",
            },
            {
                "action": "highlight",
                "selector": "h1",
            },
            {
                "action": "draw_box",
                "selector": "h1",
            },
            {
                "action": "wait",
                "seconds": 1,
            },
        ],
    }


def write_demo_template(output: Path) -> Path:
    output_path = output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    template = build_demo_template()
    output_path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"✅ DemoScript JSON written: {output_path}", flush=True)
    return output_path


def run_demo_smoke_command(args: argparse.Namespace) -> None:
    result = run_smoke_demo(
        profile=args.profile,
        headless=args.headless,
    )

    if not result.success:
        raise RuntimeError(result.error)

    print(f"✅ DemoScript executed: {result.completed_steps} steps", flush=True)


def run_demo_json_command(args: argparse.Namespace) -> None:
    script = load_demo_script(Path(args.demo_json))

    config = BrowserRuntimeConfig(
        profile=args.profile,
        headless=args.headless,
    )

    with BrowserRuntime(config=config) as runtime:
        executor = BrowserDemoExecutor(runtime=runtime)
        runner = DemoRunner(executor=executor)
        result = runner.run(script)

    if not result.success:
        raise RuntimeError(result.error)

    print(f"✅ DemoScript executed: {result.completed_steps} steps", flush=True)


def run_demo_record_command(args: argparse.Namespace) -> Path:
    script = load_demo_script(Path(args.demo_json))

    output_path = record_demo_script(
        script,
        Path(args.output),
        profile=args.profile,
        events_output_file=args.events_output,
    )

    print(
        f"✅ DemoScript recorded: {output_path}",
        flush=True,
    )
    events_path = (
        Path(args.events_output).expanduser().resolve()
        if args.events_output
        else default_events_path(output_path)
    )
    print(f"Recording events written: {events_path}", flush=True)
    return output_path


def run_demo_init_command(args: argparse.Namespace) -> None:
    write_demo_template(Path(args.output))


def run_demo_validate_command(args: argparse.Namespace) -> None:
    script = load_demo_script(Path(args.demo_json))
    print(f"✅ DemoScript valid: {len(script.steps)} steps", flush=True)


def run_demo_plan_command(args: argparse.Namespace) -> None:
    script = load_demo_script(Path(args.demo_json))
    plan = DemoDryRunPlanner().plan(script)
    print(plan.to_text(), flush=True)


def run_demo_generate_command(args: argparse.Namespace) -> Path:
    scenario_path = Path(args.scenario).expanduser().resolve()
    if not scenario_path.exists():
        raise FileNotFoundError(scenario_path)

    preferences = (
        _load_json_object(Path(args.preferences), "Preferences")
        if args.preferences
        else {}
    )
    discovery = (
        _load_json_object(Path(args.discovery), "Discovery")
        if args.discovery
        else None
    )
    request = ScenarioPlanningRequest(
        scenario=scenario_path.read_text(encoding="utf-8"),
        target_url=args.target_url,
        title=args.title,
        preferences=preferences,
        constraints=tuple(args.constraint),
        discovery=discovery,
    )
    provider = CommandScenarioProvider(
        command=(args.provider_command, *args.provider_arg),
    )
    script = ScenarioPlanner(provider=provider).plan(request)

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(demo_script_to_dict(script), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"DemoScript generated: {output_path}", flush=True)
    return output_path


def run_demo_discover_command(
    args: argparse.Namespace,
    runtime_factory=None,
    discovery_factory=None,
) -> Path:
    if runtime_factory is None:
        runtime_factory = BrowserRuntime
    if discovery_factory is None:
        discovery_factory = PageDiscoveryService

    config = BrowserRuntimeConfig(
        profile=args.profile,
        headless=args.headless,
    )
    with runtime_factory(config=config) as runtime:
        report = discovery_factory(runtime=runtime).discover(
            args.url,
            max_elements=args.max_elements,
        )

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Page discovery written: {output_path}", flush=True)
    return output_path


def _load_json_object(path: Path, field_name: str) -> dict[str, Any]:
    resolved_path = path.expanduser().resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(resolved_path)

    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{field_name} JSON root must be an object")
    return payload


def run_project_init_command(args: argparse.Namespace) -> Path:
    path = create_hermes_project(
        args.project_directory,
        title=args.title,
        video_file=args.video,
        events_file=args.events,
        script_file=args.script,
    )
    print(f"HermesProject created: {path}", flush=True)
    return path


def run_project_validate_command(args: argparse.Namespace) -> None:
    project = validate_hermes_project(args.project_directory)
    print(f"HermesProject valid: {project.title}", flush=True)


def run_project_auto_zoom_command(args: argparse.Namespace) -> dict[str, Any]:
    track = apply_auto_zoom(
        args.project_directory,
        settings=AutoZoomSettings(
            scale=args.scale,
            lead_seconds=args.lead,
            hold_seconds=args.hold,
            transition_seconds=args.transition,
            target_margin=args.target_margin,
            merge_distance=args.merge_distance,
        ),
    )
    print(
        f"HermesProject auto zoom generated: {len(track['segments'])} segments",
        flush=True,
    )
    return track


def run_project_cursor_motion_command(args: argparse.Namespace) -> dict[str, Any]:
    track = apply_cursor_motion(
        args.project_directory,
        settings=CursorMotionSettings(
            speed_pixels_per_second=args.speed,
            minimum_move_seconds=args.min_duration,
            maximum_move_seconds=args.max_duration,
            settle_seconds=args.settle,
            tension=args.tension,
        ),
    )
    print(
        "HermesProject cursor motion generated: "
        f"{len(track['anchors'])} anchors, {len(track['segments'])} segments",
        flush=True,
    )
    return track


def run_project_style_command(args: argparse.Namespace) -> dict[str, Any]:
    composition = apply_framing_preset(
        args.project_directory,
        preset=args.preset,
        background_color=args.background_color,
        padding=args.padding,
        corner_radius=args.corner_radius,
        shadow_enabled=args.shadow_enabled,
        canvas_width=args.canvas_width,
        canvas_height=args.canvas_height,
    )
    canvas = composition["canvas"]
    print(
        "HermesProject style applied: "
        f"{composition['preset']} ({canvas['width']}x{canvas['height']})",
        flush=True,
    )
    return composition


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

    demo_run = sub.add_parser("demo-run", help="Run a DemoScript JSON file")
    demo_run.add_argument("demo_json")
    demo_run.add_argument("--headless", action="store_true")
    demo_run.add_argument("--profile", default="demo-json")

    demo_record = sub.add_parser(
        "demo-record",
        help="Record a DemoScript JSON file to MP4",
    )
    demo_record.add_argument("demo_json")
    demo_record.add_argument("--output", required=True)
    demo_record.add_argument("--profile", default="demo-record")
    demo_record.add_argument("--events-output")

    demo_init = sub.add_parser("demo-init", help="Create a starter DemoScript JSON file")
    demo_init.add_argument("output")

    demo_validate = sub.add_parser("demo-validate", help="Validate a DemoScript JSON file")
    demo_validate.add_argument("demo_json")

    demo_plan = sub.add_parser("demo-plan", help="Print a dry-run plan for a DemoScript JSON file")
    demo_plan.add_argument("demo_json")

    demo_generate = sub.add_parser(
        "demo-generate",
        help="Generate a validated DemoScript from a user-written scenario",
    )
    demo_generate.add_argument("scenario")
    demo_generate.add_argument("--output", required=True)
    demo_generate.add_argument("--provider-command", required=True)
    demo_generate.add_argument("--provider-arg", action="append", default=[])
    demo_generate.add_argument("--target-url")
    demo_generate.add_argument("--title")
    demo_generate.add_argument("--preferences")
    demo_generate.add_argument("--discovery")
    demo_generate.add_argument("--constraint", action="append", default=[])

    demo_discover = sub.add_parser(
        "demo-discover",
        help="Catalog visible interactive elements before planning a DemoScript",
    )
    demo_discover.add_argument("url")
    demo_discover.add_argument("--output", required=True)
    demo_discover.add_argument("--profile", default="demo-discovery")
    demo_discover.add_argument("--headless", action="store_true")
    demo_discover.add_argument("--max-elements", type=int, default=250)

    project_init = sub.add_parser("project-init", help="Create a portable HermesProject")
    project_init.add_argument("project_directory")
    project_init.add_argument("--title", required=True)
    project_init.add_argument("--video", required=True)
    project_init.add_argument("--events", required=True)
    project_init.add_argument("--script", required=True)

    project_validate = sub.add_parser("project-validate", help="Validate HermesProject assets")
    project_validate.add_argument("project_directory")

    project_auto_zoom = sub.add_parser(
        "project-auto-zoom",
        help="Generate a non-destructive camera track from recorded clicks",
    )
    project_auto_zoom.add_argument("project_directory")
    project_auto_zoom.add_argument("--scale", type=float, default=1.35)
    project_auto_zoom.add_argument("--lead", type=float, default=0.25)
    project_auto_zoom.add_argument("--hold", type=float, default=0.65)
    project_auto_zoom.add_argument("--transition", type=float, default=0.35)
    project_auto_zoom.add_argument("--target-margin", type=float, default=80.0)
    project_auto_zoom.add_argument("--merge-distance", type=float, default=120.0)

    project_cursor_motion = sub.add_parser(
        "project-cursor-motion",
        help="Generate a smooth non-destructive cursor motion track",
    )
    project_cursor_motion.add_argument("project_directory")
    project_cursor_motion.add_argument("--speed", type=float, default=1400.0)
    project_cursor_motion.add_argument("--min-duration", type=float, default=0.12)
    project_cursor_motion.add_argument("--max-duration", type=float, default=0.75)
    project_cursor_motion.add_argument("--settle", type=float, default=0.06)
    project_cursor_motion.add_argument("--tension", type=float, default=0.6)

    project_style = sub.add_parser(
        "project-style",
        help="Apply a validated canvas and frame preset to HermesProject",
    )
    project_style.add_argument("project_directory")
    project_style.add_argument(
        "--preset", required=True, choices=available_framing_presets()
    )
    project_style.add_argument("--background-color")
    project_style.add_argument("--padding", type=int)
    project_style.add_argument("--corner-radius", type=int)
    project_style.add_argument("--canvas-width", type=int)
    project_style.add_argument("--canvas-height", type=int)
    shadow_group = project_style.add_mutually_exclusive_group()
    shadow_group.add_argument(
        "--shadow", dest="shadow_enabled", action="store_true"
    )
    shadow_group.add_argument(
        "--no-shadow", dest="shadow_enabled", action="store_false"
    )
    project_style.set_defaults(shadow_enabled=None)

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

    if args.command == "demo-run":
        run_demo_json_command(args)
        return

    if args.command == "demo-record":
        run_demo_record_command(args)
        return

    if args.command == "demo-init":
        run_demo_init_command(args)
        return

    if args.command == "demo-validate":
        run_demo_validate_command(args)
        return

    if args.command == "demo-plan":
        run_demo_plan_command(args)
        return

    if args.command == "demo-generate":
        run_demo_generate_command(args)
        return

    if args.command == "demo-discover":
        run_demo_discover_command(args)
        return

    if args.command == "project-init":
        run_project_init_command(args)
        return

    if args.command == "project-validate":
        run_project_validate_command(args)
        return

    if args.command == "project-auto-zoom":
        run_project_auto_zoom_command(args)
        return

    if args.command == "project-cursor-motion":
        run_project_cursor_motion_command(args)
        return

    if args.command == "project-style":
        run_project_style_command(args)
        return

    if args.legacy_task_json:
        record_task(Path(args.legacy_task_json))
        return

    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
