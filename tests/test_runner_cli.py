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
