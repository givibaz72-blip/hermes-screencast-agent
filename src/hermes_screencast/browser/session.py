import time
from types import TracebackType

from playwright.sync_api import Page, Playwright, sync_playwright

from .factory import BrowserConfig, BrowserFactory


class BrowserSession:
    def __init__(self, profile: str = "legacy"):
        self.config = BrowserConfig(profile=profile)

        self._playwright: Playwright | None = None
        self._context = None
        self.page: Page | None = None

    def __enter__(self):
        self._playwright = sync_playwright().start()

        self._context = BrowserFactory(self.config).create(self._playwright)

        if self._context.pages:
            self.page = self._context.pages[0]
        else:
            self.page = self._context.new_page()

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ):
        self.close()
    def require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError("BrowserSession is not started")
        return self.page

    def goto(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout: int = 30000,
    ) -> None:
        self.require_page().goto(
            url,
            wait_until=wait_until,
            timeout=timeout,
        )

    def wait(self, seconds: float):
        time.sleep(seconds)

    def hover(self, selector: str):
        self.require_page().hover(selector)

    def click(self, selector: str):
        self.require_page().click(selector)

    def content(self) -> str:
        return self.require_page().content()
    def evaluate(self, script: str):
        return self.require_page().evaluate(script)
    def add_init_script(self, script: str) -> None:
        self.require_page().add_init_script(script)

    def close(self):
        if self._context:
            self._context.close()
            self._context = None

        if self._playwright:
            self._playwright.stop()
            self.page = None
            self._context = None
            self._playwright = None

        self.page = None
