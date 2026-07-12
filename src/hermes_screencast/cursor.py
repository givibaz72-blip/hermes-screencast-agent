from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol


VISUAL_CURSOR_INIT_SCRIPT = r"""
(() => {
    window.__hermesInstallVisualCursor = function () {
        if (!document.documentElement) {
            return;
        }

        let style = document.querySelector(
            'style[data-hermes-visual-cursor-style]'
        );

        if (!style) {
            style = document.createElement('style');
            style.setAttribute('data-hermes-visual-cursor-style', 'true');
            style.textContent = `
                *, *::before, *::after {
                    cursor: none !important;
                }

                [data-hermes-visual-cursor] {
                    position: fixed;
                    left: -100px;
                    top: -100px;
                    width: 24px;
                    height: 24px;
                    z-index: 2147483647;
                    pointer-events: none;
                    background: #111111;
                    clip-path: polygon(
                        0 0,
                        0 76%,
                        25% 59%,
                        42% 96%,
                        58% 88%,
                        40% 53%,
                        76% 53%
                    );
                    filter:
                        drop-shadow(1px 1px 1px rgba(255,255,255,0.95))
                        drop-shadow(-1px -1px 0 rgba(255,255,255,0.95));
                    transform: translate(-2px, -2px);
                }
            `;

            document.documentElement.appendChild(style);
        }

        let cursor = document.querySelector(
            '[data-hermes-visual-cursor]'
        );

        if (!cursor) {
            cursor = document.createElement('div');
            cursor.setAttribute('data-hermes-visual-cursor', 'true');
            document.documentElement.appendChild(cursor);
        }

        window.__hermesVisualCursor = cursor;

        // Compatibility with the previous recorder implementation.
        window.__cursor = cursor;

        if (!window.__hermesCursorListenerInstalled) {
            document.addEventListener(
                'mousemove',
                (event) => {
                    const current = window.__hermesVisualCursor;
                    if (!current) {
                        return;
                    }

                    current.style.left = `${event.clientX}px`;
                    current.style.top = `${event.clientY}px`;
                },
                true
            );

            window.__hermesCursorListenerInstalled = true;
        }

        window.__hermesClickRipple = function (x, y) {
            const ripple = document.createElement('div');

            ripple.setAttribute('data-hermes-click-ripple', 'true');

            Object.assign(ripple.style, {
                position: 'fixed',
                left: `${x - 11}px`,
                top: `${y - 11}px`,
                width: '22px',
                height: '22px',
                borderRadius: '50%',
                border: '3px solid rgba(255, 72, 72, 0.95)',
                zIndex: '2147483646',
                pointerEvents: 'none',
                opacity: '1',
                transform: 'scale(0.75)',
                transition:
                    'transform 420ms ease-out, opacity 420ms ease-out'
            });

            document.documentElement.appendChild(ripple);

            requestAnimationFrame(() => {
                ripple.style.transform = 'scale(2.4)';
                ripple.style.opacity = '0';
            });

            window.setTimeout(() => ripple.remove(), 480);
        };

        // Compatibility with the previous recorder implementation.
        window.__clickRipple = window.__hermesClickRipple;
    };

    if (document.readyState === 'loading') {
        document.addEventListener(
            'DOMContentLoaded',
            window.__hermesInstallVisualCursor,
            {once: true}
        );
    } else {
        window.__hermesInstallVisualCursor();
    }
})();
"""


class VisualCursorRuntime(Protocol):
    @property
    def mouse(self) -> Any:
        ...

    def add_init_script(self, script: str) -> None:
        ...

    def evaluate(self, script: str) -> Any:
        ...

    def wait(self, seconds: float) -> None:
        ...


@dataclass
class VisualCursor:
    """Visible browser cursor controlled by Playwright mouse movement."""

    runtime: VisualCursorRuntime
    movement_steps: int = 25
    scroll_settle_seconds: float = 0.25

    _installed: bool = False
    _x: float = 0.0
    _y: float = 0.0

    def install(self) -> None:
        """Install the cursor in the current page and future documents."""
        if self._installed:
            return

        # Install the cursor for future navigations.
        self.runtime.add_init_script(VISUAL_CURSOR_INIT_SCRIPT)

        # Also install it immediately in the page that is already open.
        self.runtime.evaluate(VISUAL_CURSOR_INIT_SCRIPT)

        self._installed = True

    def move_to_selector(self, selector: str) -> tuple[float, float]:
        """Smoothly move the cursor to the center of a page element."""
        self.install()

        self.runtime.evaluate(
            f"""
            (() => {{
                const element = document.querySelector({selector!r});
                if (!element) {{
                    throw new Error("Element not found: {selector}");
                }}

                element.scrollIntoView({{
                    behavior: "smooth",
                    block: "center",
                    inline: "center"
                }});
            }})();
            """
        )

        self.runtime.wait(self.scroll_settle_seconds)

        center = self.runtime.evaluate(
            f"""
            (() => {{
                const element = document.querySelector({selector!r});
                if (!element) {{
                    return null;
                }}

                const rect = element.getBoundingClientRect();

                return {{
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2
                }};
            }})();
            """
        )

        if not center:
            raise RuntimeError(f"Element not found: {selector}")

        x = float(center["x"])
        y = float(center["y"])

        self.runtime.mouse.move(
            x,
            y,
            steps=self.movement_steps,
        )

        self._x = x
        self._y = y
        return x, y

    def show_click_ripple(self) -> None:
        """Show a short click indicator at the current cursor position."""
        self.install()

        self.runtime.evaluate(
            f"""
            (() => {{
                if (window.__hermesClickRipple) {{
                    window.__hermesClickRipple({self._x}, {self._y});
                }}
            }})();
            """
        )


def get_center(page: Any, selector: str):
    """Return element center coordinates or None if element is not found."""
    try:
        box = page.locator(selector).first.bounding_box()
        if box:
            return (
                box["x"] + box["width"] / 2,
                box["y"] + box["height"] / 2,
            )
    except Exception:
        pass

    return page.evaluate(
        f"""
        (() => {{
            const element = document.querySelector({selector!r});
            if (!element) {{
                return null;
            }}

            const rect = element.getBoundingClientRect();

            return {{
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2
            }};
        }})();
        """
    )


def move_cursor_to(
    page: Any,
    x: float,
    y: float,
    steps: int = 25,
    step_delay: float = 0.012,
) -> None:
    """Legacy-compatible smooth visual cursor movement."""
    try:
        start = page.evaluate(
            """
            (() => {
                const cursor =
                    window.__hermesVisualCursor || window.__cursor;

                if (!cursor) {
                    return null;
                }

                return {
                    x: parseFloat(cursor.style.left) || 0,
                    y: parseFloat(cursor.style.top) || 0
                };
            })();
            """
        )
        sx = start.get("x", x) if start else x
        sy = start.get("y", y) if start else y
    except Exception:
        sx, sy = x, y

    for index in range(1, steps + 1):
        current_x = sx + (x - sx) * index / steps
        current_y = sy + (y - sy) * index / steps

        page.mouse.move(current_x, current_y)
        page.evaluate(
            f"""
            (() => {{
                const cursor =
                    window.__hermesVisualCursor || window.__cursor;

                if (cursor) {{
                    cursor.style.left = {current_x!r} + "px";
                    cursor.style.top = {current_y!r} + "px";
                }}
            }})();
            """
        )
        time.sleep(step_delay)
