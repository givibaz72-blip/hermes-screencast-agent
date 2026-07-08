import re
from urllib.parse import urlparse

DEFAULT_SYNC_OFFSET = 0.3

def safe_title_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path
    host = host.replace("www.", "")
    title = re.sub(r"[^a-zA-Z0-9_.-]+", "_", host).strip("_")
    return title or "website_demo"

def make_basic_task(
    url: str,
    title: str | None = None,
    mode: str = "public",
    wait_before: int = 2,
    wait_after: int = 1,
    hover_selector: str | None = None,
    click_selector: str | None = None,
    sync_offset: float = DEFAULT_SYNC_OFFSET,
) -> dict:
    if not url:
        raise ValueError("url is required")

    steps = [{"action": "wait", "seconds": wait_before}]

    if hover_selector:
        steps.append({"action": "hover", "selector": hover_selector, "pause": 1})

    if click_selector:
        steps.append({"action": "click", "selector": click_selector})

    steps.append({"action": "wait", "seconds": wait_after})

    return {
        "title": title or safe_title_from_url(url),
        "url": url,
        "mode": mode,
        "steps": steps,
        "sync_offset": sync_offset,
    }
