from pathlib import Path

class VerificationError(RuntimeError):
    pass

def verify_mp4(path: Path, min_size: int = 100_000) -> Path:
    if not path.exists():
        raise VerificationError(f"MP4 not found: {path}")
    if path.stat().st_size < min_size:
        raise VerificationError(f"MP4 too small: {path} ({path.stat().st_size} bytes)")
    return path
