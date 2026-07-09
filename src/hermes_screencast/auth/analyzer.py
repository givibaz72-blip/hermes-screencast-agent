from __future__ import annotations

from dataclasses import dataclass

from hermes_screencast.auth import AuthResult, AuthState
from hermes_screencast.browser.page import BrowserPage


@dataclass(frozen=True)
class AuthAnalyzer:
    page: BrowserPage

    def analyze(self) -> AuthResult:
        state = self.page.state()

        if state == AuthState.AUTHENTICATED:
            return AuthResult(
                state=AuthState.AUTHENTICATED,
                reason="Authenticated session detected",
            )

        if state == AuthState.LOGIN_REQUIRED:
            return AuthResult(
                state=AuthState.LOGIN_REQUIRED,
                reason="Login page detected",
            )

        if state == AuthState.CAPTCHA_REQUIRED:
            return AuthResult(
                state=AuthState.CAPTCHA_REQUIRED,
                reason="CAPTCHA or bot challenge detected",
            )

        if state == AuthState.TWO_FACTOR_REQUIRED:
            return AuthResult(
                state=AuthState.TWO_FACTOR_REQUIRED,
                reason="Two-factor authentication required",
            )

        return AuthResult(
            state=AuthState.UNKNOWN,
            reason="Unable to determine authentication state",
        )
