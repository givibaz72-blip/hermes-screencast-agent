from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from hermes_screencast.demo.executor import DemoExecutor
from hermes_screencast.demo.script import DemoActionType, DemoRunResult, DemoScript, DemoStep


@dataclass
class DemoRunner:
    executor: DemoExecutor

    def run(self, script: DemoScript) -> DemoRunResult:
        completed_steps = 0

        try:
            script.validate()

            for step in script.steps:
                self._run_step(step)
                completed_steps += 1

            return DemoRunResult(success=True, completed_steps=completed_steps)

        except Exception as exc:
            return DemoRunResult(
                success=False,
                completed_steps=completed_steps,
                error=str(exc),
            )

    def _run_step(self, step: DemoStep) -> None:
        if step.action == DemoActionType.GOTO:
            self._goto(step)
        elif step.action == DemoActionType.CLICK:
            self._click(step)
        elif step.action == DemoActionType.HOVER:
            self._hover(step)
        elif step.action == DemoActionType.FILL:
            self._fill(step)
        elif step.action == DemoActionType.SCROLL:
            self._scroll(step)
        elif step.action == DemoActionType.WAIT:
            self._wait(step)
        elif step.action == DemoActionType.WAIT_FOR_ELEMENT:
            self._wait_for_element(step)
        elif step.action == DemoActionType.ZOOM:
            self._zoom(step)
        elif step.action == DemoActionType.HIGHLIGHT:
            self._highlight(step)
        elif step.action == DemoActionType.DRAW_BOX:
            self._draw_box(step)
        elif step.action == DemoActionType.DRAW_ARROW:
            self._draw_arrow(step)
        elif step.action == DemoActionType.NARRATION:
            self._narration(step)
        elif step.action == DemoActionType.AUTH_CHECK:
            self._auth_check()
        elif step.action == DemoActionType.ASSERT_TEXT_VISIBLE:
            self._assert_text_visible(step)
        elif step.action == DemoActionType.ASSERT_ELEMENT_VISIBLE:
            self._assert_element_visible(step)
        elif step.action == DemoActionType.ASSERT_URL_CONTAINS:
            self._assert_url_contains(step)
        else:
            self._unsupported_action(step)

    def _goto(self, step: DemoStep) -> None:
        assert step.url is not None
        self.executor.goto(step.url)

    def _click(self, step: DemoStep) -> None:
        assert step.selector is not None
        self.executor.click(step.selector)

    def _hover(self, step: DemoStep) -> None:
        assert step.selector is not None
        self.executor.hover(step.selector)

    def _fill(self, step: DemoStep) -> None:
        assert step.selector is not None
        assert step.text is not None
        self.executor.fill(step.selector, step.text)

    def _scroll(self, step: DemoStep) -> None:
        assert step.value is not None
        self.executor.scroll(int(step.value))

    def _wait(self, step: DemoStep) -> None:
        assert step.seconds is not None
        self.executor.wait(step.seconds)

    def _wait_for_element(self, step: DemoStep) -> None:
        assert step.selector is not None
        self.executor.wait_for_element(step.selector, step.seconds)

    def _zoom(self, step: DemoStep) -> None:
        assert step.selector is not None
        self.executor.zoom(step.selector)

    def _highlight(self, step: DemoStep) -> None:
        assert step.selector is not None
        self.executor.highlight(step.selector)

    def _draw_box(self, step: DemoStep) -> None:
        assert step.selector is not None
        self.executor.draw_box(step.selector)

    def _draw_arrow(self, step: DemoStep) -> None:
        assert step.selector is not None
        self.executor.draw_arrow(step.selector)

    def _narration(self, step: DemoStep) -> None:
        assert step.text is not None
        self.executor.narration(step.text)

    def _auth_check(self) -> None:
        self.executor.auth_check()

    def _assert_text_visible(self, step: DemoStep) -> None:
        assert step.text is not None
        self.executor.assert_text_visible(step.text)

    def _assert_element_visible(self, step: DemoStep) -> None:
        assert step.selector is not None
        self.executor.assert_element_visible(step.selector)

    def _assert_url_contains(self, step: DemoStep) -> None:
        assert step.url is not None
        self.executor.assert_url_contains(step.url)

    def _unsupported_action(self, step: DemoStep) -> NoReturn:
        raise ValueError(f"Unsupported demo action: {step.action}")
