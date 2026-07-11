from __future__ import annotations

import pytest

from hermes_screencast.demo.planner import DemoDryRunPlanner
from hermes_screencast.demo.script import DemoActionType, DemoScript, DemoStep


def test_demo_dry_run_planner_builds_deterministic_plan() -> None:
    script = DemoScript(
        title="Pricing walkthrough",
        target={"kind": "web", "url": "https://example.com/pricing"},
        preferences={"cursor_speed": "natural"},
        metadata={"schema": "hermes.demo.v1"},
        steps=[
            DemoStep(action=DemoActionType.GOTO, url="https://example.com/pricing"),
            DemoStep(action=DemoActionType.HOVER, selector="text=Pricing"),
            DemoStep(action=DemoActionType.CLICK, selector="text=Pricing"),
            DemoStep(action=DemoActionType.FILL, selector="#email", text="demo@example.com"),
            DemoStep(action=DemoActionType.SCROLL, value=300),
            DemoStep(action=DemoActionType.WAIT, seconds=1),
            DemoStep(action=DemoActionType.HIGHLIGHT, selector=".price"),
            DemoStep(action=DemoActionType.NARRATION, text="Show pricing options"),
        ],
    )

    plan = DemoDryRunPlanner().plan(script)

    assert plan.title == "Pricing walkthrough"
    assert plan.target == {"kind": "web", "url": "https://example.com/pricing"}
    assert plan.preferences == {"cursor_speed": "natural"}
    assert plan.metadata == {"schema": "hermes.demo.v1"}
    assert [step.summary for step in plan.steps] == [
        "Open URL: https://example.com/pricing",
        "Move cursor to element: text=Pricing",
        "Click element: text=Pricing",
        "Fill element: #email",
        "Scroll by 300 pixels",
        "Wait for 1 seconds",
        "Highlight element: .price",
        "Show narration: Show pricing options",
    ]


def test_demo_plan_can_be_serialized_to_dict() -> None:
    script = DemoScript(
        title="Serializable plan",
        steps=[
            DemoStep(
                action=DemoActionType.GOTO,
                url="https://example.com",
                metadata={"scene": "intro"},
            ),
        ],
    )

    plan_dict = DemoDryRunPlanner().plan(script).to_dict()

    assert plan_dict == {
        "title": "Serializable plan",
        "target": {},
        "preferences": {},
        "metadata": {},
        "steps": [
            {
                "index": 0,
                "action": "goto",
                "summary": "Open URL: https://example.com",
                "details": {"url": "https://example.com"},
                "metadata": {"scene": "intro"},
            },
        ],
    }


def test_demo_plan_can_be_rendered_as_readable_text() -> None:
    script = DemoScript(
        title="Readable plan",
        target={"kind": "web"},
        preferences={"pacing": "professional"},
        steps=[
            DemoStep(action=DemoActionType.GOTO, url="https://example.com"),
            DemoStep(action=DemoActionType.AUTH_CHECK),
        ],
    )

    text = DemoDryRunPlanner().plan(script).to_text()

    assert "DemoPlan: Readable plan" in text
    assert "Target: {'kind': 'web'}" in text
    assert "Preferences: {'pacing': 'professional'}" in text
    assert "1. Open URL: https://example.com" in text
    assert "2. Check authentication state" in text


def test_demo_dry_run_planner_validates_script_before_planning() -> None:
    script = DemoScript(
        title="Broken plan",
        steps=[DemoStep(action=DemoActionType.CLICK)],
    )

    with pytest.raises(ValueError, match="click requires selector"):
        DemoDryRunPlanner().plan(script)


def test_demo_dry_run_planner_summarizes_assert_text_visible() -> None:
    script = DemoScript(
        title="Assertion plan",
        steps=[
            DemoStep(action=DemoActionType.ASSERT_TEXT_VISIBLE, text="Welcome"),
        ],
    )

    plan = DemoDryRunPlanner().plan(script)

    assert plan.steps[0].summary == "Assert text visible: Welcome"
    assert plan.steps[0].details == {"text": "Welcome"}


def test_demo_dry_run_planner_summarizes_assert_element_visible() -> None:
    script = DemoScript(
        title="Element assertion plan",
        steps=[
            DemoStep(action=DemoActionType.ASSERT_ELEMENT_VISIBLE, selector="#hero"),
        ],
    )

    plan = DemoDryRunPlanner().plan(script)

    assert plan.steps[0].summary == "Assert element visible: #hero"
    assert plan.steps[0].details == {"selector": "#hero"}


def test_demo_dry_run_planner_summarizes_assert_url_contains() -> None:
    script = DemoScript(
        title="URL assertion plan",
        steps=[
            DemoStep(action=DemoActionType.ASSERT_URL_CONTAINS, url="/dashboard"),
        ],
    )

    plan = DemoDryRunPlanner().plan(script)

    assert plan.steps[0].summary == "Assert URL contains: /dashboard"
    assert plan.steps[0].details == {"url": "/dashboard"}


def test_demo_dry_run_planner_summarizes_wait_for_element() -> None:
    script = DemoScript(
        title="Wait plan",
        steps=[
            DemoStep(
                action=DemoActionType.WAIT_FOR_ELEMENT,
                selector="#hero",
                seconds=2,
            ),
        ],
    )

    plan = DemoDryRunPlanner().plan(script)

    assert plan.steps[0].summary == "Wait for element: #hero for up to 2 seconds"
    assert plan.steps[0].details == {"selector": "#hero", "seconds": 2}


def test_demo_dry_run_planner_summarizes_wait_for_url_contains() -> None:
    script = DemoScript(
        title="Wait URL plan",
        steps=[
            DemoStep(
                action=DemoActionType.WAIT_FOR_URL_CONTAINS,
                url="/dashboard",
                seconds=2,
            ),
        ],
    )

    plan = DemoDryRunPlanner().plan(script)

    assert plan.steps[0].summary == "Wait for URL to contain: /dashboard for up to 2 seconds"
    assert plan.steps[0].details == {"url": "/dashboard", "seconds": 2}


def test_demo_dry_run_planner_summarizes_wait_for_text_visible() -> None:
    script = DemoScript(
        title="Wait text plan",
        steps=[
            DemoStep(
                action=DemoActionType.WAIT_FOR_TEXT_VISIBLE,
                text="Welcome",
                seconds=2,
            ),
        ],
    )

    plan = DemoDryRunPlanner().plan(script)

    assert plan.steps[0].summary == "Wait for text: Welcome for up to 2 seconds"
    assert plan.steps[0].details == {"text": "Welcome", "seconds": 2}


def test_demo_dry_run_planner_summarizes_wait_for_not_text_visible() -> None:
    script = DemoScript(
        title="Wait hidden text plan",
        steps=[
            DemoStep(
                action=DemoActionType.WAIT_FOR_NOT_TEXT_VISIBLE,
                text="Loading",
                seconds=2,
            ),
        ],
    )

    plan = DemoDryRunPlanner().plan(script)

    assert plan.steps[0].summary == (
        "Wait for text to disappear: Loading for up to 2 seconds"
    )
    assert plan.steps[0].details == {"text": "Loading", "seconds": 2}


def test_demo_dry_run_planner_summarizes_wait_for_navigation_idle() -> None:
    script = DemoScript(
        title="Wait navigation plan",
        steps=[
            DemoStep(
                action=DemoActionType.WAIT_FOR_NAVIGATION_IDLE,
                seconds=2,
            ),
        ],
    )

    plan = DemoDryRunPlanner().plan(script)

    assert plan.steps[0].summary == "Wait for navigation idle for up to 2 seconds"
    assert plan.steps[0].details == {"seconds": 2}


def test_demo_dry_run_planner_summarizes_assert_not_text_visible() -> None:
    script = DemoScript(
        title="Negative assertion plan",
        steps=[
            DemoStep(
                action=DemoActionType.ASSERT_NOT_TEXT_VISIBLE,
                text="Error",
            ),
        ],
    )

    plan = DemoDryRunPlanner().plan(script)

    assert plan.steps[0].summary == "Assert text not visible: Error"
    assert plan.steps[0].details == {"text": "Error"}


def test_demo_dry_run_planner_summarizes_assert_not_element_visible() -> None:
    script = DemoScript(
        title="Negative element assertion plan",
        steps=[
            DemoStep(
                action=DemoActionType.ASSERT_NOT_ELEMENT_VISIBLE,
                selector="#spinner",
            ),
        ],
    )

    plan = DemoDryRunPlanner().plan(script)

    assert plan.steps[0].summary == "Assert element not visible: #spinner"
    assert plan.steps[0].details == {"selector": "#spinner"}
