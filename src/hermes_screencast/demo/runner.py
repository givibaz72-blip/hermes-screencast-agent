from __future__ import annotations

from dataclasses import dataclass

from hermes_screencast.demo.executor import DemoExecutor
from hermes_screencast.demo.script import DemoActionType, DemoRunResult, DemoScript, DemoStep


@dataclass
class DemoRunner:
    executor: DemoExecutor

    def run(self, script: DemoScript) -> DemoRunResult:
        try:
            script.validate()

            completed_steps = 0
            for step in script.steps:
                self._run_step(step)
                completed_steps += 1

            return DemoRunResult(success=True, completed_steps=completed_steps)

        except Exception as exc:
            return DemoRunResult(
                success=False,
                completed_steps=completed_steps if "completed_steps" in locals() else 0,
                error=str(exc),
            )

    def _run_step(self, step: DemoStep) -> None:
        handlers = {
            DemoActionType.GOTO: self._goto,
            DemoActionType.CLICK: self._click,
            DemoActionType.HOVER: self._hover,
            DemoActionType.FILL: self._fill,
            DemoActionType.SCROLL: self._scroll,
            DemoActionType.WAIT: self._wait,
            DemoActionType.ZOOM: self._zoom,
            DemoActionType.HIGHLIGHT: self._highlight,
            DemoActionType.DRAW_BOX: self._draw_box,
            DemoActionType.DRAW_ARROW: self._draw_arrow,
            DemoActionType.NARRATION: self._narration,
            DemoActionType.AUTH_CHECK: self._auth_check,
        }

        handlers[step.action](step)

    def _goto(self, step: DemoStep) -> None:
        self.executor.goto(step.url or "")

    def _click(self, step: DemoStep) -> None:
        self.executor.click(step.selector or "")

    def _hover(self, step: DemoStep) -> None:
        self.executor.hover(step.selector or "")

    def _fill(self, step: DemoStep) -> None:
        self.executor.fill(step.selector or "", step.text or "")

    def _scroll(self, step: DemoStep) -> None:
        self.executor.scroll(int(step.value or 0))

    def _wait(self, step: DemoStep) -> None:
        self.executor.wait(step.seconds or 0)

    def _zoom(self, step: DemoStep) -> None:
        self.executor.zoom(step.selector or "")

    def _highlight(self, step: DemoStep) -> None:
        self.executor.highlight(step.selector or "")

    def _draw_box(self, step: DemoStep) -> None:
        self.executor.draw_box(step.selector or "")

    def _draw_arrow(self, step: DemoStep) -> None:
        self.executor.draw_arrow(step.selector or "")

    def _narration(self, step: DemoStep) -> None:
        self.executor.narration(step.text or "")

    def _auth_check(self, step: DemoStep) -> None:
        self.executor.auth_check()
