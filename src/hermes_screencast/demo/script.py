from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DemoActionType(str, Enum):
    GOTO = "goto"
    CLICK = "click"
    HOVER = "hover"
    FILL = "fill"
    SCROLL = "scroll"
    WAIT = "wait"

    ZOOM = "zoom"
    HIGHLIGHT = "highlight"
    DRAW_BOX = "draw_box"
    DRAW_ARROW = "draw_arrow"

    NARRATION = "narration"
    AUTH_CHECK = "auth_check"
    ASSERT_TEXT_VISIBLE = "assert_text_visible"
    ASSERT_ELEMENT_VISIBLE = "assert_element_visible"
    ASSERT_URL_CONTAINS = "assert_url_contains"


@dataclass(frozen=True)
class DemoStep:
    action: DemoActionType
    selector: str | None = None
    url: str | None = None
    text: str | None = None
    seconds: float | None = None
    value: Any | None = None
    note: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DemoScript:
    title: str
    steps: list[DemoStep]
    target: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("DemoScript title cannot be empty")

        self._validate_mapping("target", self.target)
        self._validate_mapping("preferences", self.preferences)
        self._validate_mapping("metadata", self.metadata)

        if not self.steps:
            raise ValueError("DemoScript must contain at least one step")

        for index, step in enumerate(self.steps):
            self._validate_step(index, step)

    def _validate_mapping(self, field_name: str, value: Any) -> None:
        if not isinstance(value, dict):
            raise ValueError(f"DemoScript {field_name} must be an object")

    def _validate_step(self, index: int, step: DemoStep) -> None:
        if step.action == DemoActionType.GOTO and not step.url:
            raise ValueError(f"Step {index}: goto requires url")

        if step.action in {
            DemoActionType.CLICK,
            DemoActionType.HOVER,
            DemoActionType.FILL,
            DemoActionType.ZOOM,
            DemoActionType.HIGHLIGHT,
            DemoActionType.DRAW_BOX,
            DemoActionType.DRAW_ARROW,
        } and not step.selector:
            raise ValueError(f"Step {index}: {step.action.value} requires selector")

        if step.action == DemoActionType.FILL and step.text is None:
            raise ValueError(f"Step {index}: fill requires text")

        if step.action == DemoActionType.WAIT:
            if step.seconds is None or step.seconds < 0:
                raise ValueError(f"Step {index}: wait requires non-negative seconds")

        if step.action == DemoActionType.SCROLL:
            if step.value is None:
                raise ValueError(f"Step {index}: scroll requires value")

            try:
                int(step.value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Step {index}: scroll value must be an integer") from exc

        if step.action == DemoActionType.NARRATION and step.text is None:
            raise ValueError(f"Step {index}: narration requires text")

        if step.action == DemoActionType.ASSERT_TEXT_VISIBLE and step.text is None:
            raise ValueError(f"Step {index}: assert_text_visible requires text")

        if step.action == DemoActionType.ASSERT_ELEMENT_VISIBLE and not step.selector:
            raise ValueError(f"Step {index}: assert_element_visible requires selector")

        if step.action == DemoActionType.ASSERT_URL_CONTAINS and not step.url:
            raise ValueError(f"Step {index}: assert_url_contains requires url")


@dataclass(frozen=True)
class DemoRunResult:
    success: bool
    completed_steps: int
    output_path: str | None = None
    error: str | None = None
