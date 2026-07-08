from dataclasses import dataclass, field
from typing import Any, Literal

Mode = Literal["public", "authenticated", "assisted_login"]

@dataclass
class ScreencastTask:
    title: str
    url: str
    mode: Mode = "public"
    steps: list[dict[str, Any]] = field(default_factory=list)
    sync_offset: float = 0.3
