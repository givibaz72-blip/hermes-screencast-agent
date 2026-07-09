from __future__ import annotations

from dataclasses import dataclass

from hermes_screencast.auth import AuthState


CAPTCHA_KEYWORDS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "turnstile",
    "cloudflare",
    "verify you are human",
    "i'm not a robot",
    "i am not a robot",
    "security check",
)

TWO_FACTOR_KEYWORDS = (
    "2fa",
    "two-factor",
    "verification code",
    "one-time code",
    "email code",
    "sms code",
    "passkey",
    "webauthn",
)

LOGIN_KEYWORDS = (
    "sign in",
    "log in",
    "login",
    "email",
    "password",
)

AUTHENTICATED_KEYWORDS = (
    "logout",
    "sign out",
    "my account",
    "profile",
    "dashboard",
    "settings",
)


@dataclass(frozen=True)
class ChallengeDetector:
    def detect(self, html: str) -> AuthState:
        value = (html or "").lower()

        if any(keyword in value for keyword in CAPTCHA_KEYWORDS):
            return AuthState.CAPTCHA_REQUIRED

        if any(keyword in value for keyword in TWO_FACTOR_KEYWORDS):
            return AuthState.TWO_FACTOR_REQUIRED

        return AuthState.UNKNOWN


@dataclass(frozen=True)
class AuthDetector:
    challenge_detector: ChallengeDetector = ChallengeDetector()

    def detect(self, html: str) -> AuthState:
        challenge = self.challenge_detector.detect(html)

        if challenge != AuthState.UNKNOWN:
            return challenge

        value = (html or "").lower()

        if any(keyword in value for keyword in AUTHENTICATED_KEYWORDS):
            return AuthState.AUTHENTICATED

        if any(keyword in value for keyword in LOGIN_KEYWORDS):
            return AuthState.LOGIN_REQUIRED

        return AuthState.UNKNOWN

    # Временная совместимость со старым API
    def detect_from_text(self, text: str) -> AuthState:
        return self.detect(text)
