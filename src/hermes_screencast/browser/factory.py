from dataclasses import dataclass

from playwright.sync_api import BrowserContext, Playwright

from .session_manager import SessionManager


@dataclass(frozen=True)
class BrowserConfig:
    profile: str = "legacy"
    headless: bool = False
    viewport_width: int = 1920
    viewport_height: int = 1080
    locale: str = "ru-RU"


class BrowserFactory:
    def __init__(self, config: BrowserConfig):
        self.config = config
        self.session_manager = SessionManager()

    def create(self, playwright: Playwright) -> BrowserContext:
        profile = self.session_manager.ensure_profile(self.config.profile)

        return playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=self.config.headless,
            viewport={
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            },
            locale=self.config.locale,
        )
