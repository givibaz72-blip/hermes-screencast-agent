from hermes_screencast.planner import make_basic_task, safe_title_from_url

def test_safe_title_from_url():
    assert safe_title_from_url("https://example.com/path") == "example.com"

def test_make_basic_hover_task():
    task = make_basic_task(
        url="https://example.com",
        title="demo",
        hover_selector="a",
    )

    assert task["title"] == "demo"
    assert task["url"] == "https://example.com"
    assert task["mode"] == "public"
    assert task["steps"][0] == {"action": "wait", "seconds": 2}
    assert task["steps"][1]["action"] == "hover"
    assert task["steps"][-1] == {"action": "wait", "seconds": 1}
