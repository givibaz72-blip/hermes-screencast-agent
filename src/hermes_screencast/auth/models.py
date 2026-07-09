from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os


class AuthState(str, Enum):
    UNKNOWN = "unknown"
    AUTHENTICATED = "authenticated"
    LOGIN_REQUIRED = "login_required"
    CAPTCHA_REQUIRED = "captcha_required"
    TWO_FACTOR_REQUIRED = "two_factor_required"


class AuthMode(str, Enum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    CREDENTIALS_LOGIN = "credentials_login"
    ASSISTED_LOGIN = "assisted_login"


@dataclass(frozen=True)
class CredentialSpec:
    email_env: str
    password_env: str

    def load(self) -> tuple[str, str]:
        email = os.environ.get(self.email_env)
        password = os.environ.get(self.password_env)

        if not email:
            raise RuntimeError(
                f"Missing environment variable: {self.email_env}"
            )

        if not password:
            raise RuntimeError(
                f"Missing environment variable: {self.password_env}"
            )

        return email, password


@dataclass(frozen=True)
class AuthResult:
    state: AuthState
    reason: str | None = None

    @property
    def authenticated(self) -> bool:
        return self.state == AuthState.AUTHENTICATED

    @property
    def requires_login(self) -> bool:
        return self.state == AuthState.LOGIN_REQUIRED

    @property
    def requires_user_action(self) -> bool:
        return self.state in (
            AuthState.CAPTCHA_REQUIRED,
            AuthState.TWO_FACTOR_REQUIRED,
        )
