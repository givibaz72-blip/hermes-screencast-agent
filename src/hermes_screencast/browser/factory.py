from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from playwright.sync_api import BrowserContext, Playwright

from .session_manager import SessionManager


@dataclass(frozen=True)
class BrowserConfig:
    profile: str = "legacy"
    headless: bool = False
    viewport_width: int = 1920
    viewport_height: int = 1080
    locale: str = "ru-RU"
    kiosk: bool = False
    display: str = ":99"


class BrowserFactory:
    def __init__(self, config: BrowserConfig):
        self.config = config
        self.session_manager = SessionManager()

    def create(self, playwright: Playwright) -> BrowserContext:
        profile = self.session_manager.ensure_profile(
            self.config.profile
        )

        browser_args = [
            f"--display={self.config.display}",
            "--no-sandbox",
            "--window-position=0,0",
            (
                "--window-size="
                f"{self.config.viewport_width},"
                f"{self.config.viewport_height}"
            ),
            "--force-device-scale-factor=1",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
        ]

        launch_options: dict[str, Any] = {
            "user_data_dir": str(profile),
            "headless": self.config.headless,
            "locale": self.config.locale,
            "args": browser_args,
        }

        if self.config.kiosk:
            # Chromium app mode removes tabs and the address bar.
            browser_args.append("--app=about:blank")

            # Let the page use the real content area of the 1920×1080 window.
            # A forced 1920×1080 viewport would extend below the screen when
            # Chromium adds any window decoration.
            launch_options["no_viewport"] = True
        else:
            browser_args.append("--start-maximized")
            launch_options["viewport"] = {
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            }

        return playwright.chromium.launch_persistent_context(
            **launch_options
        )
