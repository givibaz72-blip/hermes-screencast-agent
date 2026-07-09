from dataclasses import dataclass

from hermes_screencast.auth import AuthState


CAPTCHA_KEYWORDS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "i'm not a robot",
    "i am not a robot",
    "verify you are human",
    "cloudflare",
    "turnstile",
    "security check",
)

TWO_FACTOR_KEYWORDS = (
    "two-factor",
    "2fa",
    "verification code",
    "email code",
    "sms code",
    "one-time code",
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


@dataclass(frozen=True)
class ChallengeDetector:
    def detect_from_text(self, text: str) -> AuthState:
        value = (text or "").lower()

        if any(keyword in value for keyword in CAPTCHA_KEYWORDS):
            return AuthState.CAPTCHA_REQUIRED

        if any(keyword in value for keyword in TWO_FACTOR_KEYWORDS):
            return AuthState.TWO_FACTOR_REQUIRED

        return AuthState.UNKNOWN


@dataclass(frozen=True)
class AuthDetector:
    challenge_detector: ChallengeDetector = ChallengeDetector()

    def detect_from_text(self, text: str) -> AuthState:
        challenge_state = self.challenge_detector.detect_from_text(text)
        if challenge_state != AuthState.UNKNOWN:
            return challenge_state

        value = (text or "").lower()

        if any(keyword in value for keyword in LOGIN_KEYWORDS):
            return AuthState.LOGIN_REQUIRED

        return AuthState.UNKNOWN
