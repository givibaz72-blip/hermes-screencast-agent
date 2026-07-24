from __future__ import annotations

from pathlib import Path
from typing import Callable

from hermes_screencast.auth import create_handoff, AssistedLoginHandoff, HandoffResult
from hermes_screencast.browser import BrowserRuntime, BrowserRuntimeConfig
from hermes_screencast.demo.browser_executor import BrowserDemoExecutor
from hermes_screencast.demo.events import (
    EventLoggingDemoRunner,
    RecordingEventJournal,
    default_events_path,
    resolve_page_state,
    resolve_target_snapshot,
)
from hermes_screencast.demo.script import (
    DemoActionType,
    DemoScript,
)
from hermes_screencast.recording import (
    DEFAULT_DISPLAY,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    ScreenRecorder,
    VirtualDisplay,
    focus_display_point,
)
from hermes_screencast.verifier import verify_mp4


DEFAULT_BROWSER_WARMUP_SECONDS = 1.0
DEFAULT_RECORDING_TAIL_SECONDS = 0.35
DEFAULT_BROWSER_CHROME_RESERVE = 160

BROWSER_UI_VISIBLE = "visible"
BROWSER_UI_CONTENT_ONLY = "content_only"
VALID_BROWSER_UI_MODES = {
    BROWSER_UI_VISIBLE,
    BROWSER_UI_CONTENT_ONLY,
}


def resolve_browser_ui(script: DemoScript) -> str:
    browser_ui = script.preferences.get(
        "browser_ui",
        BROWSER_UI_VISIBLE,
    )

    if browser_ui not in VALID_BROWSER_UI_MODES:
        raise ValueError(
            "DemoScript preferences.browser_ui must be "
            "'visible' or 'content_only'"
        )

    return browser_ui


def build_recorded_steps_script(script: DemoScript) -> DemoScript:
    """
    Create a DemoScript containing only the steps recorded after initial goto.

    The first goto is executed before FFmpeg starts so browser startup and page
    loading are not included in the final video.
    """
    if not script.steps:
        raise ValueError("DemoScript must contain at least one step")

    first_step = script.steps[0]

    if first_step.action != DemoActionType.GOTO:
        raise ValueError(
            "DemoScript recording requires goto as the first step"
        )

    if len(script.steps) < 2:
        raise ValueError(
            "DemoScript recording requires at least one step after initial goto"
        )

    return DemoScript(
        title=script.title,
        steps=list(script.steps[1:]),
        target=dict(script.target),
        preferences=dict(script.preferences),
        metadata=dict(script.metadata),
    )


def auth_preflight_check(url: str, profile: str = "demo-record", timeout: float = 30.0,
                         success_url_prefix: str = "", success_selector: str = "") -> HandoffResult:
    """Check authentication status before recording.

    This performs a lightweight check to verify the browser profile is authenticated
    for the given URL without starting the full handoff flow.

    Returns:
        HandoffResult with status indicating authentication state
    """
    handoff = create_handoff(
        target_url=url,
        profile=profile,
        timeout=timeout,
        success_url_prefix=success_url_prefix,
        success_selector=success_selector,
        no_auto_detect=False,
    )

    try:
        result = handoff.start()
        # Wait for initial page load and check login state
        result = handoff.wait_for_completion(timeout=timeout)
        return result
    finally:
        handoff.stop()


def record_demo_script(
    script: DemoScript,
    output_file: str | Path,
    *,
    profile: str = "demo-record",
    display: str = DEFAULT_DISPLAY,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    browser_warmup_seconds: float = DEFAULT_BROWSER_WARMUP_SECONDS,
    recording_tail_seconds: float = DEFAULT_RECORDING_TAIL_SECONDS,
    browser_chrome_reserve: int = DEFAULT_BROWSER_CHROME_RESERVE,
    display_factory=VirtualDisplay,
    recorder_factory=ScreenRecorder,
    runtime_factory=BrowserRuntime,
    verifier: Callable[[Path], Path] = verify_mp4,
    focus_action: Callable[..., None] | None = None,
    events_output_file: str | Path | None = None,
    event_journal_factory=RecordingEventJournal,
    event_runner_factory=EventLoggingDemoRunner,
    auth_preflight_checker: Callable | None = None,
) -> Path:
    """Execute a modern DemoScript and record its visible actions to MP4."""
    script.validate()
    recorded_script = build_recorded_steps_script(script)

    first_step = script.steps[0]
    assert first_step.url is not None

    # Perform auth preflight check only if requires_auth is true
    requires_auth = script.target.get("requires_auth", False)
    if requires_auth:
        if auth_preflight_checker is None:
            auth_preflight_checker = auth_preflight_check
        success_url_prefix = script.target.get("success_url_prefix", "")
        success_selector = script.target.get("success_selector", "")
        auth_result = auth_preflight_checker(
            first_step.url,
            profile=profile,
            success_url_prefix=success_url_prefix,
            success_selector=success_selector,
        )
        if auth_result.status != "authenticated":
            # Authentication not complete or blocked - do not record
            raise RuntimeError(
                f"Authentication preflight failed: {auth_result.status} - "
                f"target={auth_result.target_url}, final={auth_result.final_url}. "
                f"Cannot start recording without authenticated session."
            )

    output_path = Path(output_file).expanduser().resolve()
    events_path = (
        Path(events_output_file).expanduser().resolve()
        if events_output_file is not None
        else default_events_path(output_path)
    )

    if focus_action is None:
        focus_action = focus_display_point

    browser_ui = resolve_browser_ui(script)
    content_only = browser_ui == BROWSER_UI_CONTENT_ONLY

    display_height = (
        height + browser_chrome_reserve
        if content_only
        else height
    )

    runtime_config = BrowserRuntimeConfig(
        profile=profile,
        headless=False,
        viewport_width=width,
        viewport_height=display_height,
        kiosk=True,
    )

    with display_factory(
        display=display,
        width=width,
        height=display_height,
    ):
        with runtime_factory(config=runtime_config) as runtime:
            executor = BrowserDemoExecutor(runtime=runtime)

            # Prepare the page before FFmpeg starts.
            executor.goto(first_step.url)
            executor.wait(browser_warmup_seconds)
            executor.enable_visual_cursor()

            # Move focus away from the address bar before FFmpeg starts.
            runtime.evaluate(
                """
                (() => {
                    window.focus();

                    if (document.body) {
                        document.body.setAttribute("tabindex", "-1");
                        document.body.focus({preventScroll: true});
                    }
                })();
                """
            )
            focus_display_point(
                x=width // 2,
                y=min(height // 2, 500),
                display=display,
            )
            executor.wait(0.15)

            capture_offset_y = 0

            if content_only:
                chrome_offset_y = runtime.evaluate(
                    """
                    (() => Math.max(
                        0,
                        Math.round(
                            window.outerHeight - window.innerHeight
                        )
                    ))();
                    """
                )

                try:
                    capture_offset_y = max(
                        0,
                        int(chrome_offset_y or 0),
                    )
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        "Cannot determine Chromium toolbar height"
                    ) from exc

                if capture_offset_y + height > display_height:
                    raise RuntimeError(
                        "Browser content does not fit the recording display"
                    )

            # Stop FFmpeg while the browser is still visible. This prevents
            # black frames from appearing at the end of the output.
            with recorder_factory(
                output_file=output_path,
                display=display,
                width=width,
                height=height,
                offset_y=capture_offset_y,
            ):
                journal = event_journal_factory()
                journal.start(
                    {
                        "title": script.title,
                        "video_file": output_path.name,
                        "width": width,
                        "height": height,
                        "capture_offset_y": capture_offset_y,
                        "browser_ui": browser_ui,
                    }
                )
                failure: BaseException | None = None
                try:
                    def cursor_resolver() -> dict[str, float] | None:
                        if executor.visual_cursor is None:
                            return None
                        x, y = executor.visual_cursor.position
                        return {"x": round(x, 2), "y": round(y, 2)}

                    result = event_runner_factory(
                        executor=executor,
                        journal=journal,
                        target_resolver=lambda selector: resolve_target_snapshot(
                            runtime, selector
                        ),
                        state_resolver=lambda: resolve_page_state(runtime),
                        cursor_resolver=cursor_resolver,
                    ).run(recorded_script)

                    if not result.success:
                        raise RuntimeError(
                            result.error or "DemoScript recording failed"
                        )

                    if recording_tail_seconds > 0:
                        executor.wait(recording_tail_seconds)
                except BaseException as exc:
                    failure = exc
                    raise
                finally:
                    journal.finish(success=failure is None, error=failure)
                    journal.write(events_path)

    return verifier(output_path)
