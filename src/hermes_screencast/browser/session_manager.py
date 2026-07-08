from pathlib import Path
import re

DEFAULT_PROFILE_ROOT = Path("/root/HermesWorkspace/screencast/profiles")
LEGACY_PROFILE = Path("/root/HermesWorkspace/screencast/chrome-profile")


def safe_profile_name(name: str) -> str:
    name = name or "default"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", name).strip("_") or "default"


class SessionManager:
    def __init__(self, profile_root: Path = DEFAULT_PROFILE_ROOT):
        self.profile_root = profile_root

    def profile_path(self, name: str | None = None) -> Path:
        if not name or name == "legacy":
            return LEGACY_PROFILE
        return self.profile_root / safe_profile_name(name)

    def ensure_profile(self, name: str | None = None) -> Path:
        path = self.profile_path(name)
        path.mkdir(parents=True, exist_ok=True)
        return path
