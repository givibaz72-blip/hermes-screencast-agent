from __future__ import annotations

from hermes_screencast.browser import BrowserRuntime, BrowserRuntimeConfig
from hermes_screencast.demo.browser_executor import BrowserDemoExecutor
from hermes_screencast.demo.runner import DemoRunner
from hermes_screencast.demo.script import DemoActionType, DemoScript, DemoStep


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


def main() -> None:
    script = build_smoke_script()

    config = BrowserRuntimeConfig(
        profile="demo-smoke",
        headless=True,
    )

    with BrowserRuntime(config=config) as runtime:
        executor = BrowserDemoExecutor(runtime=runtime)
        runner = DemoRunner(executor=executor)

        result = runner.run(script)

        if not result.success:
            raise RuntimeError(result.error)

        print(f"✅ DemoScript executed: {result.completed_steps} steps")


if __name__ == "__main__":
    main()
