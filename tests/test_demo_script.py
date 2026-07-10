import pytest

from hermes_screencast.demo.script import (
    DemoActionType,
    DemoScript,
    DemoStep,
)


def test_valid_demo_script_passes_validation():
    script = DemoScript(
        title="Pricing walkthrough",
        steps=[
            DemoStep(action=DemoActionType.GOTO, url="https://example.com"),
            DemoStep(action=DemoActionType.HOVER, selector="text=Pricing"),
            DemoStep(action=DemoActionType.CLICK, selector="text=Pricing"),
            DemoStep(action=DemoActionType.ZOOM, selector=".pricing-table"),
            DemoStep(action=DemoActionType.HIGHLIGHT, selector=".price"),
            DemoStep(action=DemoActionType.NARRATION, text="Show pricing options"),
        ],
    )

    script.validate()


def test_demo_script_requires_title():
    script = DemoScript(
        title=" ",
        steps=[DemoStep(action=DemoActionType.GOTO, url="https://example.com")],
    )

    with pytest.raises(ValueError, match="title"):
        script.validate()


def test_demo_script_requires_steps():
    script = DemoScript(title="Empty script", steps=[])

    with pytest.raises(ValueError, match="at least one step"):
        script.validate()


def test_goto_requires_url():
    script = DemoScript(
        title="Broken script",
        steps=[DemoStep(action=DemoActionType.GOTO)],
    )

    with pytest.raises(ValueError, match="goto requires url"):
        script.validate()


def test_click_requires_selector():
    script = DemoScript(
        title="Broken script",
        steps=[DemoStep(action=DemoActionType.CLICK)],
    )

    with pytest.raises(ValueError, match="click requires selector"):
        script.validate()


def test_fill_requires_selector_and_text():
    script = DemoScript(
        title="Broken script",
        steps=[DemoStep(action=DemoActionType.FILL, selector="#email")],
    )

    with pytest.raises(ValueError, match="fill requires text"):
        script.validate()


def test_wait_requires_non_negative_seconds():
    script = DemoScript(
        title="Broken script",
        steps=[DemoStep(action=DemoActionType.WAIT, seconds=-1)],
    )

    with pytest.raises(ValueError, match="wait requires non-negative seconds"):
        script.validate()
