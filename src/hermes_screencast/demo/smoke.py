from __future__ import annotations

from hermes_screencast.browser import BrowserRuntime, BrowserRuntimeConfig
from hermes_screencast.demo.browser_executor import BrowserDemoExecutor
from hermes_screencast.demo.runner import DemoRunner
from hermes_screencast.demo.script import DemoActionType, DemoRunResult, DemoScript, DemoStep


def build_smoke_script() -> DemoScript:
    return DemoScript(
        title="Hermes Demo Engine smoke test",
        steps=[
            DemoStep(action=DemoActionType.GOTO, url="https://example.com"),
            DemoStep(action=DemoActionType.WAIT, seconds=1),
            DemoStep(action=DemoActionType.NARRATION, text="Hermes is executing a DemoScript"),
            DemoStep(action=DemoActionType.HIGHLIGHT, selector="h1"),
            DemoStep(action=DemoActionType.DRAW_BOX, selector="h1"),
            DemoStep(action=DemoActionType.WAIT, seconds=2),
        ],
    )


def run_smoke_demo(profile: str = "demo-smoke", headless: bool = True) -> DemoRunResult:
    script = build_smoke_script()

    config = BrowserRuntimeConfig(
        profile=profile,
        headless=headless,
    )

    with BrowserRuntime(config=config) as runtime:
        executor = BrowserDemoExecutor(runtime=runtime)
        runner = DemoRunner(executor=executor)
        return runner.run(script)
