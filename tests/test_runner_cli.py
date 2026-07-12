from hermes_screencast.runner import build_parser


def test_plan_parser():
    parser = build_parser()
    args = parser.parse_args([
        "plan",
        "--url", "https://example.com",
        "--hover", "a",
        "--output", "/tmp/task.json",
    ])

    assert args.command == "plan"
    assert args.url == "https://example.com"
    assert args.hover == "a"
    assert args.output == "/tmp/task.json"


def test_demo_smoke_parser():
    parser = build_parser()
    args = parser.parse_args([
        "demo-smoke",
        "--headless",
        "--profile", "test-demo",
    ])

    assert args.command == "demo-smoke"
    assert args.headless is True
    assert args.profile == "test-demo"


def test_demo_run_parser():
    parser = build_parser()
    args = parser.parse_args([
        "demo-run",
        "/tmp/demo.json",
        "--headless",
        "--profile", "json-demo",
    ])

    assert args.command == "demo-run"
    assert args.demo_json == "/tmp/demo.json"
    assert args.headless is True
    assert args.profile == "json-demo"


def test_demo_record_parser():
    parser = build_parser()
    args = parser.parse_args([
        "demo-record",
        "/tmp/demo.json",
        "--output", "/tmp/demo.mp4",
        "--profile", "recorded-demo",
        "--events-output", "/tmp/demo.events.json",
    ])

    assert args.command == "demo-record"
    assert args.demo_json == "/tmp/demo.json"
    assert args.output == "/tmp/demo.mp4"
    assert args.profile == "recorded-demo"
    assert args.events_output == "/tmp/demo.events.json"


def test_demo_init_parser():
    parser = build_parser()
    args = parser.parse_args([
        "demo-init",
        "/tmp/demo.json",
    ])

    assert args.command == "demo-init"
    assert args.output == "/tmp/demo.json"


def test_demo_validate_parser():
    parser = build_parser()
    args = parser.parse_args([
        "demo-validate",
        "/tmp/demo.json",
    ])

    assert args.command == "demo-validate"
    assert args.demo_json == "/tmp/demo.json"


def test_demo_plan_parser():
    parser = build_parser()
    args = parser.parse_args([
        "demo-plan",
        "/tmp/demo.json",
    ])

    assert args.command == "demo-plan"
    assert args.demo_json == "/tmp/demo.json"


def test_demo_generate_parser():
    parser = build_parser()
    args = parser.parse_args([
        "demo-generate",
        "/tmp/scenario.txt",
        "--output", "/tmp/demo.json",
        "--provider-command", "provider-wrapper",
        "--provider-arg=--model",
        "--provider-arg", "local-model",
        "--target-url", "https://example.com",
        "--title", "Generated demo",
        "--preferences", "/tmp/preferences.json",
        "--discovery", "/tmp/discovery.json",
        "--constraint", "Do not submit forms",
    ])

    assert args.command == "demo-generate"
    assert args.scenario == "/tmp/scenario.txt"
    assert args.output == "/tmp/demo.json"
    assert args.provider_command == "provider-wrapper"
    assert args.provider_arg == ["--model", "local-model"]
    assert args.target_url == "https://example.com"
    assert args.title == "Generated demo"
    assert args.preferences == "/tmp/preferences.json"
    assert args.discovery == "/tmp/discovery.json"
    assert args.constraint == ["Do not submit forms"]


def test_demo_discover_parser():
    parser = build_parser()
    args = parser.parse_args([
        "demo-discover",
        "https://example.com",
        "--output", "/tmp/discovery.json",
        "--profile", "discovery-test",
        "--headless",
        "--max-elements", "50",
    ])

    assert args.command == "demo-discover"
    assert args.url == "https://example.com"
    assert args.output == "/tmp/discovery.json"
    assert args.profile == "discovery-test"
    assert args.headless is True
    assert args.max_elements == 50


def test_project_init_parser():
    args = build_parser().parse_args([
        "project-init", "/tmp/demo.hermes", "--title", "Demo",
        "--video", "/tmp/demo.mp4", "--events", "/tmp/demo.events.json",
        "--script", "/tmp/demo.json",
    ])
    assert args.command == "project-init"
    assert args.title == "Demo"
    assert args.video == "/tmp/demo.mp4"


def test_project_validate_parser():
    args = build_parser().parse_args(["project-validate", "/tmp/demo.hermes"])
    assert args.command == "project-validate"
    assert args.project_directory == "/tmp/demo.hermes"


def test_project_auto_zoom_parser():
    args = build_parser().parse_args([
        "project-auto-zoom", "/tmp/demo.hermes",
        "--scale", "1.45", "--hold", "0.8", "--merge-distance", "90",
    ])
    assert args.command == "project-auto-zoom"
    assert args.project_directory == "/tmp/demo.hermes"
    assert args.scale == 1.45
    assert args.hold == 0.8
    assert args.merge_distance == 90


def test_project_cursor_motion_parser():
    args = build_parser().parse_args([
        "project-cursor-motion", "/tmp/demo.hermes",
        "--speed", "1200", "--settle", "0.08", "--tension", "0.7",
    ])
    assert args.command == "project-cursor-motion"
    assert args.project_directory == "/tmp/demo.hermes"
    assert args.speed == 1200
    assert args.settle == 0.08
    assert args.tension == 0.7


def test_project_style_parser():
    args = build_parser().parse_args([
        "project-style", "/tmp/demo.hermes", "--preset", "social-vertical",
        "--background-color", "#123456", "--padding", "80",
        "--corner-radius", "20", "--no-shadow",
    ])
    assert args.command == "project-style"
    assert args.preset == "social-vertical"
    assert args.background_color == "#123456"
    assert args.padding == 80
    assert args.corner_radius == 20
    assert args.shadow_enabled is False


def test_project_annotate_parser():
    args = build_parser().parse_args([
        "project-annotate", "/tmp/demo.hermes", "--kind", "arrow",
        "--start", "1", "--end", "2.5", "--id", "next-step",
        "--x", "100", "--y", "200", "--to-x", "500", "--to-y", "400",
        "--color", "#FACC15", "--stroke-width", "6",
    ])
    assert args.command == "project-annotate"
    assert args.kind == "arrow"
    assert args.annotation_id == "next-step"
    assert args.to_x == 500
    assert args.stroke_width == 6


def test_project_annotation_management_parsers():
    remove = build_parser().parse_args([
        "project-annotation-remove", "/tmp/demo.hermes", "note-1"
    ])
    listing = build_parser().parse_args([
        "project-annotation-list", "/tmp/demo.hermes"
    ])
    assert remove.annotation_id == "note-1"
    assert listing.command == "project-annotation-list"


def test_project_auto_edit_parser():
    args = build_parser().parse_args([
        "project-auto-edit", "/tmp/demo.hermes",
        "--preserve-threshold", "1.5", "--cut-threshold", "5",
        "--speed", "6", "--context", "0.3", "--minimum-edit", "0.25",
    ])
    assert args.command == "project-auto-edit"
    assert args.preserve_threshold == 1.5
    assert args.cut_threshold == 5
    assert args.speed == 6
    assert args.context == 0.3


def test_project_preview_parser():
    args = build_parser().parse_args([
        "project-preview", "/tmp/demo.hermes", "--output", "/tmp/preview.html"
    ])
    assert args.command == "project-preview"
    assert args.project_directory == "/tmp/demo.hermes"
    assert args.output == "/tmp/preview.html"


def test_project_render_parser():
    args = build_parser().parse_args([
        "project-render", "/tmp/demo.hermes", "--output", "/tmp/final.mp4",
        "--allow-unrendered", "--dry-run", "--encoder", "qsv",
    ])
    assert args.command == "project-render"
    assert args.output == "/tmp/final.mp4"
    assert args.allow_unrendered is True
    assert args.dry_run is True
    assert args.encoder == "qsv"
