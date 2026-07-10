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
