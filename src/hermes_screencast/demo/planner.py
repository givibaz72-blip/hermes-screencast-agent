from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hermes_screencast.demo.script import DemoActionType, DemoScript, DemoStep


@dataclass(frozen=True)
class DemoPlanStep:
    index: int
    action: DemoActionType
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action.value,
            "summary": self.summary,
            "details": self.details,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class DemoPlan:
    title: str
    target: dict[str, Any]
    preferences: dict[str, Any]
    metadata: dict[str, Any]
    steps: list[DemoPlanStep]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "target": self.target,
            "preferences": self.preferences,
            "metadata": self.metadata,
            "steps": [step.to_dict() for step in self.steps],
        }

    def to_text(self) -> str:
        lines = [f"DemoPlan: {self.title}"]

        if self.target:
            lines.append(f"Target: {self.target}")

        if self.preferences:
            lines.append(f"Preferences: {self.preferences}")

        lines.append("Steps:")

        for step in self.steps:
            lines.append(f"{step.index + 1}. {step.summary}")

        return "\n".join(lines)


@dataclass(frozen=True)
class DemoDryRunPlanner:
    def plan(self, script: DemoScript) -> DemoPlan:
        script.validate()

        return DemoPlan(
            title=script.title,
            target=dict(script.target),
            preferences=dict(script.preferences),
            metadata=dict(script.metadata),
            steps=[
                self._plan_step(index=index, step=step)
                for index, step in enumerate(script.steps)
            ],
        )

    def _plan_step(self, index: int, step: DemoStep) -> DemoPlanStep:
        return DemoPlanStep(
            index=index,
            action=step.action,
            summary=self._summary_for_step(step),
            details=self._details_for_step(step),
            metadata=dict(step.metadata),
        )

    def _summary_for_step(self, step: DemoStep) -> str:
        if step.action == DemoActionType.GOTO:
            return f"Open URL: {step.url}"

        if step.action == DemoActionType.CLICK:
            return f"Click element: {step.selector}"

        if step.action == DemoActionType.HOVER:
            return f"Move cursor to element: {step.selector}"

        if step.action == DemoActionType.FILL:
            return f"Fill element: {step.selector}"

        if step.action == DemoActionType.SCROLL:
            return f"Scroll by {int(step.value)} pixels"

        if step.action == DemoActionType.WAIT:
            return f"Wait for {step.seconds} seconds"

        if step.action == DemoActionType.WAIT_FOR_ELEMENT:
            timeout = (
                ""
                if step.seconds is None
                else f" for up to {step.seconds} seconds"
            )
            return f"Wait for element: {step.selector}{timeout}"

        if step.action == DemoActionType.WAIT_FOR_URL_CONTAINS:
            timeout = (
                ""
                if step.seconds is None
                else f" for up to {step.seconds} seconds"
            )
            return f"Wait for URL to contain: {step.url}{timeout}"

        if step.action == DemoActionType.ZOOM:
            return f"Zoom into element: {step.selector}"

        if step.action == DemoActionType.HIGHLIGHT:
            return f"Highlight element: {step.selector}"

        if step.action == DemoActionType.DRAW_BOX:
            return f"Draw box around element: {step.selector}"

        if step.action == DemoActionType.DRAW_ARROW:
            return f"Draw arrow toward element: {step.selector}"

        if step.action == DemoActionType.NARRATION:
            return f"Show narration: {step.text}"

        if step.action == DemoActionType.AUTH_CHECK:
            return "Check authentication state"

        if step.action == DemoActionType.ASSERT_TEXT_VISIBLE:
            return f"Assert text visible: {step.text}"

        if step.action == DemoActionType.ASSERT_ELEMENT_VISIBLE:
            return f"Assert element visible: {step.selector}"

        if step.action == DemoActionType.ASSERT_URL_CONTAINS:
            return f"Assert URL contains: {step.url}"

        raise ValueError(f"Unsupported demo action: {step.action}")

    def _details_for_step(self, step: DemoStep) -> dict[str, Any]:
        details: dict[str, Any] = {}

        if step.selector is not None:
            details["selector"] = step.selector

        if step.url is not None:
            details["url"] = step.url

        if step.text is not None:
            details["text"] = step.text

        if step.seconds is not None:
            details["seconds"] = step.seconds

        if step.value is not None:
            details["value"] = step.value

        if step.note is not None:
            details["note"] = step.note

        return details
