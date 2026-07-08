from hermes_screencast.auth import AuthState
from hermes_screencast.detectors import AuthDetector, ChallengeDetector


def test_challenge_detector_captcha():
    detector = ChallengeDetector()

    assert detector.detect_from_text("Please verify you are human") == AuthState.CAPTCHA_REQUIRED


def test_challenge_detector_cloudflare():
    detector = ChallengeDetector()

    assert detector.detect_from_text("Cloudflare security check") == AuthState.CAPTCHA_REQUIRED


def test_challenge_detector_two_factor():
    detector = ChallengeDetector()

    assert detector.detect_from_text("Enter verification code") == AuthState.TWO_FACTOR_REQUIRED


def test_auth_detector_login_required():
    detector = AuthDetector()

    assert detector.detect_from_text("Email Password Sign in") == AuthState.LOGIN_REQUIRED


def test_auth_detector_prioritizes_challenge():
    detector = AuthDetector()

    assert detector.detect_from_text("Password required. CAPTCHA required.") == AuthState.CAPTCHA_REQUIRED


def test_auth_detector_unknown():
    detector = AuthDetector()

    assert detector.detect_from_text("Welcome to your dashboard") == AuthState.UNKNOWN
