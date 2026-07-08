from pathlib import Path
import pytest

from hermes_screencast.verifier import verify_mp4, VerificationError

def test_missing_mp4_fails(tmp_path: Path):
    with pytest.raises(VerificationError):
        verify_mp4(tmp_path / "missing.mp4")
