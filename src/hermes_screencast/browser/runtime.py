from dataclasses import dataclass
from typing import Any

from .factory import BrowserConfig
from .session import BrowserSession


@dataclass(frozen=True)
class BrowserRuntimeConfig:
    profile: str = "legacy"
    headless: bool = False
    viewport_width: int = 1920
    viewport_height: int = 1080
    locale: str = "ru-RU"


class BrowserRuntime:
    def __init__(self, config: BrowserRuntimeConfig | None = None):
        self.config = config or BrowserRuntimeConfig()
        browser_config = BrowserConfig(
            profile=self.config.profile,
            headless=self.config.headless,
            viewport_width=self.config.viewport_width,
            viewport_height=self.config.viewport_height,
            locale=self.config.locale,
        )
        self.session = BrowserSession(profile=browser_config.profile)

    def __enter__(self) -> "BrowserRuntime":
        self.session.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def page(self):
        return self.session.require_page()

    @property
    def context(self):
        return self.session.context

    @property
    def pages(self):
        return self.session.pages

    @property
    def mouse(self):
        return self.session.mouse

    def new_page(self):
        return self.session.new_page()

    def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000) -> None:
        self.session.goto(url, wait_until=wait_until, timeout=timeout)

    def wait(self, seconds: float) -> None:
        self.session.wait(seconds)

    def hover(self, selector: str, timeout: int = 5000) -> None:
        self.session.hover(selector, timeout=timeout)

    def click(self, selector: str, timeout: int = 5000) -> None:
        self.session.click(selector, timeout=timeout)

    def fill(self, selector: str, text: str, timeout: int = 5000) -> None:
        self.session.fill(selector, text, timeout=timeout)

    def locator(self, selector: str) -> Any:
        return self.session.locator(selector)

    def evaluate(self, script: str) -> Any:
        return self.session.evaluate(script)

    def add_init_script(self, script: str) -> None:
        self.session.add_init_script(script)

    def content(self) -> str:
        return self.session.content()

    def close(self) -> None:
        self.session.close()
