import time
from types import TracebackType
from typing import Any

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .factory import BrowserConfig, BrowserFactory


class BrowserSession:
    def __init__(self, profile: str = "legacy", config: BrowserConfig | None = None):
        self.config = config or BrowserConfig(profile=profile)
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    def __enter__(self) -> "BrowserSession":
        self._playwright = sync_playwright().start()
        self._context = BrowserFactory(self.config).create(self._playwright)
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError("BrowserSession is not started")
        return self.page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("BrowserSession is not started")
        return self._context

    @property
    def pages(self) -> list[Page]:
        return self.context.pages

    @property
    def mouse(self):
        return self.require_page().mouse

    def new_page(self) -> Page:
        return self.context.new_page()

    def goto(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout: int = 30000,
    ) -> None:
        self.require_page().goto(url, wait_until=wait_until, timeout=timeout)

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)

    def hover(self, selector: str, timeout: int = 5000) -> None:
        self.require_page().hover(selector, timeout=timeout)

    def click(self, selector: str, timeout: int = 5000) -> None:
        self.require_page().click(selector, timeout=timeout)

    def fill(self, selector: str, text: str, timeout: int = 5000) -> None:
        self.require_page().fill(selector, text, timeout=timeout)

    def locator(self, selector: str) -> Any:
        return self.require_page().locator(selector)

    def evaluate(self, script: str) -> Any:
        return self.require_page().evaluate(script)

    def add_init_script(self, script: str) -> None:
        self.require_page().add_init_script(script)

    def content(self) -> str:
        return self.require_page().content()

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None

        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

        self.page = None
