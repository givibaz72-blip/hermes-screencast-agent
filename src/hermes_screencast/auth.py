from dataclasses import dataclass
from enum import Enum
import os


class AuthState(str, Enum):
    AUTHENTICATED = "authenticated"
    LOGIN_REQUIRED = "login_required"
    CAPTCHA_REQUIRED = "captcha_required"
    TWO_FACTOR_REQUIRED = "two_factor_required"
    UNKNOWN = "unknown"


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
            raise RuntimeError(f"Missing email env var: {self.email_env}")
        if not password:
            raise RuntimeError(f"Missing password env var: {self.password_env}")

        return email, password
