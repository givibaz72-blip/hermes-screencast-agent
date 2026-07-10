from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BrowserRuntimeLike(Protocol):
    def goto(self, url: str) -> None:
        ...

    def click(self, selector: str) -> None:
        ...

    def hover(self, selector: str) -> None:
        ...

    def fill(self, selector: str, text: str) -> None:
        ...

    def wait(self, seconds: float) -> None:
        ...

    def evaluate(self, script: str):
        ...


@dataclass
class BrowserDemoExecutor:
    runtime: BrowserRuntimeLike

    def goto(self, url: str) -> None:
        self.runtime.goto(url)

    def click(self, selector: str) -> None:
        self.runtime.click(selector)

    def hover(self, selector: str) -> None:
        self.runtime.hover(selector)

    def fill(self, selector: str, text: str) -> None:
        self.runtime.fill(selector, text)

    def scroll(self, amount: int) -> None:
        self.runtime.evaluate(f"window.scrollBy(0, {amount});")

    def wait(self, seconds: float) -> None:
        self.runtime.wait(seconds)

    def zoom(self, selector: str) -> None:
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

                element.style.transition = "transform 200ms ease";
                element.style.transform = "scale(1.03)";
            }})();
            """
        )

    def highlight(self, selector: str) -> None:
        self.runtime.evaluate(
            f"""
            (() => {{
                const element = document.querySelector({selector!r});
                if (!element) {{
                    throw new Error("Element not found: {selector}");
                }}

                element.style.outline = "3px solid #ffcc00";
                element.style.outlineOffset = "4px";
                element.style.borderRadius = "6px";
            }})();
            """
        )

    def draw_box(self, selector: str) -> None:
        self.runtime.evaluate(
            f"""
            (() => {{
                const element = document.querySelector({selector!r});
                if (!element) {{
                    throw new Error("Element not found: {selector}");
                }}

                const rect = element.getBoundingClientRect();
                const box = document.createElement("div");

                box.setAttribute("data-hermes-demo-overlay", "box");
                box.style.position = "fixed";
                box.style.left = `${{rect.left}}px`;
                box.style.top = `${{rect.top}}px`;
                box.style.width = `${{rect.width}}px`;
                box.style.height = `${{rect.height}}px`;
                box.style.border = "3px solid #ffcc00";
                box.style.borderRadius = "8px";
                box.style.pointerEvents = "none";
                box.style.zIndex = "2147483647";

                document.body.appendChild(box);
            }})();
            """
        )

    def draw_arrow(self, selector: str) -> None:
        self.runtime.evaluate(
            f"""
            (() => {{
                const element = document.querySelector({selector!r});
                if (!element) {{
                    throw new Error("Element not found: {selector}");
                }}

                const rect = element.getBoundingClientRect();
                const arrow = document.createElement("div");

                arrow.setAttribute("data-hermes-demo-overlay", "arrow");
                arrow.textContent = "➜";
                arrow.style.position = "fixed";
                arrow.style.left = `${{Math.max(rect.left - 48, 0)}}px`;
                arrow.style.top = `${{rect.top + rect.height / 2 - 18}}px`;
                arrow.style.fontSize = "36px";
                arrow.style.fontWeight = "bold";
                arrow.style.pointerEvents = "none";
                arrow.style.zIndex = "2147483647";

                document.body.appendChild(arrow);
            }})();
            """
        )

    def narration(self, text: str) -> None:
        self.runtime.evaluate(
            f"""
            (() => {{
                const existing = document.querySelector("[data-hermes-demo-narration]");
                if (existing) {{
                    existing.remove();
                }}

                const narration = document.createElement("div");
                narration.setAttribute("data-hermes-demo-narration", "true");
                narration.textContent = {text!r};

                narration.style.position = "fixed";
                narration.style.left = "50%";
                narration.style.bottom = "32px";
                narration.style.transform = "translateX(-50%)";
                narration.style.maxWidth = "70vw";
                narration.style.padding = "14px 18px";
                narration.style.borderRadius = "12px";
                narration.style.background = "rgba(0, 0, 0, 0.78)";
                narration.style.color = "white";
                narration.style.fontSize = "18px";
                narration.style.lineHeight = "1.4";
                narration.style.zIndex = "2147483647";
                narration.style.pointerEvents = "none";

                document.body.appendChild(narration);
            }})();
            """
        )

    def auth_check(self) -> None:
        page = getattr(self.runtime, "page", None)

        if page is None:
            return

        is_authenticated = getattr(page, "is_authenticated", None)

        if callable(is_authenticated) and not is_authenticated():
            raise RuntimeError("Browser page is not authenticated")

    def assert_text_visible(self, text: str) -> None:
        result = self.runtime.evaluate(
            f"""
            (() => {{
                const expectedText = {text!r};
                const bodyText = document.body ? document.body.innerText : "";
                return bodyText.includes(expectedText);
            }})();
            """
        )

        if not result:
            raise AssertionError(f"Text not visible: {text}")
