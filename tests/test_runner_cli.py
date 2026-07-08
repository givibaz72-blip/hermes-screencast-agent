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
