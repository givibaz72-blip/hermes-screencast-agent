import pytest

from hermes_screencast.auth import (
    AuthMode,
    AuthState,
    CredentialSpec,
)


def test_auth_modes_exist():
    assert AuthMode.PUBLIC.value == "public"
    assert AuthMode.AUTHENTICATED.value == "authenticated"
    assert AuthMode.CREDENTIALS_LOGIN.value == "credentials_login"
    assert AuthMode.ASSISTED_LOGIN.value == "assisted_login"


def test_auth_states_exist():
    assert AuthState.AUTHENTICATED.value == "authenticated"
    assert AuthState.LOGIN_REQUIRED.value == "login_required"
    assert AuthState.CAPTCHA_REQUIRED.value == "captcha_required"
    assert AuthState.TWO_FACTOR_REQUIRED.value == "two_factor_required"
    assert AuthState.UNKNOWN.value == "unknown"


def test_credentials_load(monkeypatch):
    monkeypatch.setenv("TEST_EMAIL", "user@example.com")
    monkeypatch.setenv("TEST_PASSWORD", "secret")

    spec = CredentialSpec("TEST_EMAIL", "TEST_PASSWORD")

    assert spec.load() == ("user@example.com", "secret")


def test_credentials_missing(monkeypatch):
    monkeypatch.delenv("MISSING_EMAIL", raising=False)
    monkeypatch.delenv("MISSING_PASSWORD", raising=False)

    spec = CredentialSpec("MISSING_EMAIL", "MISSING_PASSWORD")

    with pytest.raises(RuntimeError):
        spec.load()
