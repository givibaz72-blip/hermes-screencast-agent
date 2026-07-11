import pytest

from hermes_screencast.demo.script import (
    DemoActionType,
    DemoScript,
    DemoStep,
)


def test_valid_demo_script_passes_validation():
    script = DemoScript(
        title="Pricing walkthrough",
        target={"kind": "web", "url": "https://example.com"},
        preferences={"cursor_speed": "natural"},
        metadata={"schema": "hermes.demo.v1"},
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


def test_demo_script_keeps_schema_fields_optional_for_legacy_scripts():
    script = DemoScript(
        title="Legacy script",
        steps=[DemoStep(action=DemoActionType.GOTO, url="https://example.com")],
    )

    script.validate()

    assert script.target == {}
    assert script.preferences == {}
    assert script.metadata == {}


def test_demo_script_requires_object_schema_fields():
    script = DemoScript(
        title="Broken script",
        target=[],
        steps=[DemoStep(action=DemoActionType.GOTO, url="https://example.com")],
    )

    with pytest.raises(ValueError, match="target must be an object"):
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


def test_assert_text_visible_requires_text():
    script = DemoScript(
        title="Broken script",
        steps=[DemoStep(action=DemoActionType.ASSERT_TEXT_VISIBLE)],
    )

    with pytest.raises(ValueError, match="assert_text_visible requires text"):
        script.validate()


def test_assert_element_visible_requires_selector():
    script = DemoScript(
        title="Broken script",
        steps=[DemoStep(action=DemoActionType.ASSERT_ELEMENT_VISIBLE)],
    )

    with pytest.raises(ValueError, match="assert_element_visible requires selector"):
        script.validate()


def test_assert_url_contains_requires_url():
    script = DemoScript(
        title="Broken script",
        steps=[DemoStep(action=DemoActionType.ASSERT_URL_CONTAINS)],
    )

    with pytest.raises(ValueError, match="assert_url_contains requires url"):
        script.validate()


def test_wait_for_element_requires_selector():
    script = DemoScript(
        title="Broken script",
        steps=[DemoStep(action=DemoActionType.WAIT_FOR_ELEMENT)],
    )

    with pytest.raises(ValueError, match="wait_for_element requires selector"):
        script.validate()


def test_wait_for_element_rejects_negative_seconds():
    script = DemoScript(
        title="Broken script",
        steps=[
            DemoStep(
                action=DemoActionType.WAIT_FOR_ELEMENT,
                selector="#hero",
                seconds=-1,
            ),
        ],
    )

    with pytest.raises(ValueError, match="wait_for_element requires non-negative seconds"):
        script.validate()


def test_wait_for_url_contains_requires_url():
    script = DemoScript(
        title="Broken script",
        steps=[DemoStep(action=DemoActionType.WAIT_FOR_URL_CONTAINS)],
    )

    with pytest.raises(ValueError, match="wait_for_url_contains requires url"):
        script.validate()


def test_wait_for_url_contains_rejects_negative_seconds():
    script = DemoScript(
        title="Broken script",
        steps=[
            DemoStep(
                action=DemoActionType.WAIT_FOR_URL_CONTAINS,
                url="/dashboard",
                seconds=-1,
            ),
        ],
    )

    with pytest.raises(ValueError, match="wait_for_url_contains requires non-negative seconds"):
        script.validate()
