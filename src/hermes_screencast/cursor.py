import time
from typing import Any


def get_center(page: Any, selector: str):
    """Return element center coordinates or None if element is not found."""
    print(f"  [DEBUG] get_center ищет селектор: {selector!r}")

    try:
        box = page.locator(selector).first.bounding_box()
        if box:
            return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    except Exception:
        pass

    escaped = selector.replace("\\", "\\\\").replace("'", "\\'")
    result = page.evaluate(f"""
        (() => {{
            const el = document.querySelector('{escaped}');
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            return {{x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}};
        }})()
    """)

    if result:
        return result["x"], result["y"]

    return None


def move_cursor_to(page: Any, x: float, y: float, steps: int = 25, step_delay: float = 0.012) -> None:
    """Move both real and visual cursors smoothly along one path."""
    print(f"  [DEBUG] move_cursor_to вызван: x={x:.1f} y={y:.1f}")

    try:
        start = page.evaluate(
            "({x: parseFloat(window.__cursor.style.left)||0, "
            "y: parseFloat(window.__cursor.style.top)||0})"
        )
        sx, sy = start.get("x", x), start.get("y", y)
    except Exception:
        sx, sy = x, y

    page.evaluate("window.__cursor.style.transition='none'")

    for i in range(1, steps + 1):
        ix = sx + (x - sx) * i / steps
        iy = sy + (y - sy) * i / steps
        page.mouse.move(ix, iy)
        page.evaluate(
            f"window.__cursor.style.left='{ix}px'; window.__cursor.style.top='{iy}px'"
        )
        time.sleep(step_delay)
