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
    ])

    assert args.command == "demo-record"
    assert args.demo_json == "/tmp/demo.json"
    assert args.output == "/tmp/demo.mp4"
    assert args.profile == "recorded-demo"


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
