from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class CompanionCommand(str, Enum):
    """Commands that can be sent to the local companion."""
    START_SESSION = "start_session"
    OPEN_URL = "open_url"
    GET_SAFE_PAGE_STATE = "get_safe_page_state"
    CONFIRM_AUTHENTICATION = "confirm_authentication"
    START_RECORDING = "start_recording"
    STOP_RECORDING = "stop_recording"
    FINISH_SESSION = "finish_session"


class SessionStatus(str, Enum):
    """Session status values."""
    PENDING = "pending"
    RUNNING = "running"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    RECORDING = "recording"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BrowserStartup(str, Enum):
    """Browser startup strategy for Windows-local E2E."""
    RAW_CDP = "raw-cdp"
    PLAYWRIGHT = "playwright"


class AuthStatus(str, Enum):
    """Authentication status values."""
    UNKNOWN = "unknown"
    LOGIN_REQUIRED = "login_required"
    PROVIDER_BLOCKED = "provider_blocked"
    AUTHENTICATED = "authenticated"


@dataclass
class PairingToken:
    """Short-lived pairing token for backend-companion connection."""
    token: str
    created_at: float
    expires_at: float
    session_id: str
    used: bool = False

    @classmethod
    def create(cls, session_id: str, ttl_seconds: float = 300) -> "PairingToken":
        """Create a new cryptographically secure pairing token."""
        return cls(
            token=secrets.token_urlsafe(32),
            created_at=time.time(),
            expires_at=time.time() + ttl_seconds,
            session_id=session_id,
        )

    def is_valid(self) -> bool:
        """Check if token is valid and not expired."""
        return not self.used and time.time() < self.expires_at

    def mark_used(self) -> None:
        """Mark token as used (single-use)."""
        self.used = True


@dataclass
class SafePageState:
    """Safe page state returned by local companion - NO secrets."""
    current_url: str
    hostname: str
    title: str
    visible_markers: list[str] = field(default_factory=list)
    success_selector_visible: bool = False
    viewport_width: int = 1920
    viewport_height: int = 1080
    session_status: str = SessionStatus.RUNNING.value
    auth_status: str = AuthStatus.UNKNOWN.value
    login_markers: list[str] = field(default_factory=list)
    provider_block_markers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_url": self.current_url,
            "hostname": self.hostname,
            "title": self.title,
            "visible_markers": self.visible_markers,
            "success_selector_visible": self.success_selector_visible,
            "viewport_width": self.viewport_width,
            "viewport_height": self.viewport_height,
            "session_status": self.session_status,
            "auth_status": self.auth_status,
            "login_markers": self.login_markers,
            "provider_block_markers": self.provider_block_markers,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafePageState":
        return cls(**data)


@dataclass
class CompanionRequest:
    """Request sent to local companion."""
    command: str
    session_id: str
    pairing_token: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps({
            "command": self.command,
            "session_id": self.session_id,
            "pairing_token": self.pairing_token,
            "payload": self.payload,
            "timestamp": self.timestamp,
        })

    @classmethod
    def from_json(cls, data: str) -> "CompanionRequest":
        obj = json.loads(data)
        return cls(
            command=obj["command"],
            session_id=obj["session_id"],
            pairing_token=obj["pairing_token"],
            payload=obj.get("payload", {}),
            timestamp=obj.get("timestamp", time.time()),
        )


@dataclass
class CompanionResponse:
    """Response from local companion."""
    success: bool
    session_id: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps({
            "success": self.success,
            "session_id": self.session_id,
            "status": self.status,
            "payload": self.payload,
            "error": self.error,
            "timestamp": self.timestamp,
        })

    @classmethod
    def from_json(cls, data: str) -> "CompanionResponse":
        obj = json.loads(data)
        return cls(
            success=obj["success"],
            session_id=obj["session_id"],
            status=obj["status"],
            payload=obj.get("payload", {}),
            error=obj.get("error"),
            timestamp=obj.get("timestamp", time.time()),
        )


@dataclass
class SessionConfig:
    """Configuration for a companion session."""
    session_id: str
    profile_name: str
    profile_path: Path
    target_url: str
    success_url_prefix: str = ""
    success_selector: str = ""
    width: int = 1920
    height: int = 1080
    headless: bool = True
    chrome_path: Optional[str] = None
    chrome_args: list[str] = field(default_factory=list)
    browser_startup: str = "playwright"
    auth_wait_seconds: int = 300


@dataclass
class RecordingConfig:
    """Configuration for local recording."""
    output_path: Path
    events_output_path: Optional[Path] = None
    recording_dir: Optional[Path] = None
    width: int = 1920
    height: int = 1080
    fps: int = 30
    show_recording_indicator: bool = True