from __future__ import annotations

from typing import Protocol


class DemoExecutor(Protocol):
    """Contract for executing demo actions."""

    def goto(self, url: str) -> None:
        ...

    def click(self, selector: str) -> None:
        ...

    def hover(self, selector: str) -> None:
        ...

    def fill(self, selector: str, text: str) -> None:
        ...

    def scroll(self, amount: int) -> None:
        ...

    def wait(self, seconds: float) -> None:
        ...

    def zoom(self, selector: str) -> None:
        ...

    def highlight(self, selector: str) -> None:
        ...

    def draw_box(self, selector: str) -> None:
        ...

    def draw_arrow(self, selector: str) -> None:
        ...

    def narration(self, text: str) -> None:
        ...

    def auth_check(self) -> None:
        ...
