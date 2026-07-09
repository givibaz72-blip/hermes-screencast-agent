from hermes_screencast.auth import AuthState
from hermes_screencast.detectors import AuthDetector


def test_authenticated_dashboard():
    detector = AuthDetector()

    html = """
    <html>
        <body>
            Dashboard
            Profile
            Logout
        </body>
    </html>
    """

    assert detector.detect(html) == AuthState.AUTHENTICATED
