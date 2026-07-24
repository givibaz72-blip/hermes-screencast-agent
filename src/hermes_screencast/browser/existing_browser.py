from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ExistingBrowserConfig:
    browser_url: str = "http://127.0.0.1:9222"


class ExistingBrowser:
    """
    Placeholder for attaching Hermes to an already-running browser.

    This class intentionally contains no browser implementation yet.
    The next commits will add:
      - raw CDP connection
      - Playwright connection
      - tab discovery
      - tab selection
    """

    def __init__(self, config: ExistingBrowserConfig):
        self.config = config

    def browser_endpoint(self) -> str:
        return self.config.browser_url
