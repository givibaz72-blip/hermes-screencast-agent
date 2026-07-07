from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .session import BrowserSession
from hermes_screencast.detectors import (
    detect_auth_state,
    detect_challenge_state,
)


class PageState(str, Enum):
    UNKNOWN = "unknown"
    AUTHENTICATED = "authenticated"
    LOGIN_REQUIRED = "login_required"
    CAPTCHA_REQUIRED = "captcha_required"
    TWO_FACTOR_REQUIRED = "two_factor_required"


@dataclass
class BrowserPage:
    session: BrowserSession

    def html(self) -> str:
        return self.session.content()

    def title(self) -> str:
        return self.session.require_page().title()

    def url(self) -> str:
        return self.session.require_page().url

    def state(self) -> PageState:
        html = self.html()

        challenge = detect_challenge_state(html)
        if challenge == "captcha_required":
            return PageState.CAPTCHA_REQUIRED

        if challenge == "two_factor_required":
            return PageState.TWO_FACTOR_REQUIRED

        auth = detect_auth_state(html)
        if auth == "authenticated":
            return PageState.AUTHENTICATED

        if auth == "login_required":
            return PageState.LOGIN_REQUIRED

        return PageState.UNKNOWN

    def is_authenticated(self) -> bool:
        return self.state() == PageState.AUTHENTICATED

    def requires_login(self) -> bool:
        return self.state() == PageState.LOGIN_REQUIRED

    def has_captcha(self) -> bool:
        return self.state() == PageState.CAPTCHA_REQUIRED

    def requires_two_factor(self) -> bool:
        return self.state() == PageState.TWO_FACTOR_REQUIRED

    def find(self, selector: str):
        return self.session.locator(selector)

    def click(self, selector: str) -> None:
        self.session.click(selector)

    def hover(self, selector: str) -> None:
        self.session.hover(selector)

    def fill(self, selector: str, text: str) -> None:
        self.session.fill(selector, text)

    def evaluate(self, script: str):
        return self.session.evaluate(script)
