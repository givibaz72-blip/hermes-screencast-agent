from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit


DEFAULT_MAX_DISCOVERY_ELEMENTS = 250
MAX_DISCOVERY_ELEMENTS = 1000
MAX_TEXT_LENGTH = 160
MAX_LOCATOR_TEXT_LENGTH = 80


DISCOVERY_SCRIPT = r"""
(() => {
    const maxElements = __MAX_ELEMENTS__;
    const selector = [
        "a[href]",
        "button",
        "input:not([type='hidden'])",
        "select",
        "textarea",
        "[role]",
        "[contenteditable='true']",
        "[tabindex]:not([tabindex='-1'])"
    ].join(",");

    const normalize = (value) => (value || "").replace(/\s+/g, " ").trim();
    const clipped = (value) => normalize(value).slice(0, 160);
    const interactiveRoles = new Set([
        "button", "checkbox", "combobox", "link", "listbox", "menuitem",
        "menuitemcheckbox", "menuitemradio", "option", "radio", "searchbox",
        "slider", "spinbutton", "switch", "tab", "textbox", "treeitem"
    ]);

    const isInteractive = (element) => {
        const tag = element.tagName.toLowerCase();
        const role = element.getAttribute("role");
        const tabIndex = element.getAttribute("tabindex");
        return (
            ["a", "button", "input", "select", "textarea"].includes(tag) ||
            element.isContentEditable ||
            (tabIndex !== null && Number(tabIndex) >= 0) ||
            interactiveRoles.has(role)
        );
    };

    const isVisible = (element) => {
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        return (
            rect.width > 0 &&
            rect.height > 0 &&
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            style.opacity !== "0"
        );
    };

    const implicitRole = (element) => {
        const tag = element.tagName.toLowerCase();
        const type = (element.getAttribute("type") || "text").toLowerCase();
        if (tag === "a" && element.hasAttribute("href")) return "link";
        if (tag === "button") return "button";
        if (tag === "select") return "combobox";
        if (tag === "textarea" || element.isContentEditable) return "textbox";
        if (tag !== "input") return null;
        if (["button", "submit", "reset", "image"].includes(type)) return "button";
        if (type === "checkbox") return "checkbox";
        if (type === "radio") return "radio";
        if (type === "range") return "slider";
        return "textbox";
    };

    const labelText = (element) => {
        const id = element.getAttribute("id");
        if (id) {
            const escaped = window.CSS && CSS.escape ? CSS.escape(id) : id;
            const label = document.querySelector(`label[for="${escaped}"]`);
            if (label) return label.textContent;
        }
        const parentLabel = element.closest("label");
        return parentLabel ? parentLabel.textContent : "";
    };

    const accessibleName = (element) => {
        const labelledBy = element.getAttribute("aria-labelledby");
        const labelledText = labelledBy
            ? labelledBy.split(/\s+/).map((id) => {
                const target = document.getElementById(id);
                return target ? target.textContent : "";
            }).join(" ")
            : "";
        return clipped(
            element.getAttribute("aria-label") ||
            labelledText ||
            labelText(element) ||
            element.getAttribute("alt") ||
            element.getAttribute("title") ||
            element.getAttribute("placeholder") ||
            (["submit", "button", "reset"].includes(
                (element.getAttribute("type") || "").toLowerCase()
            ) ? element.getAttribute("value") : "") ||
            element.textContent
        );
    };

    const safeUrl = (value, baseUrl) => {
        if (!value) return { value: null, selectable: false };
        try {
            const url = new URL(value, baseUrl);
            url.username = "";
            url.password = "";
            url.hash = "";
            if (url.search) {
                const keys = Array.from(url.searchParams.keys());
                url.search = keys.map((key) => `${encodeURIComponent(key)}=REDACTED`).join("&");
                return { value: url.toString(), selectable: false };
            }
            return { value: url.toString(), selectable: true };
        } catch (_error) {
            return { value: null, selectable: false };
        }
    };

    const allVisible = Array.from(document.querySelectorAll(selector)).filter(
        (element) => isVisible(element) && isInteractive(element)
    );
    const elements = allVisible.slice(0, maxElements).map((element, index) => {
        const rect = element.getBoundingClientRect();
        const rawHref = element.getAttribute("href");
        const href = safeUrl(rawHref, window.location.href);
        return {
            index,
            tag: element.tagName.toLowerCase(),
            role: element.getAttribute("role") || implicitRole(element),
            name: accessibleName(element),
            text: clipped(element.textContent),
            test_id: element.getAttribute("data-testid"),
            id: element.getAttribute("id"),
            name_attribute: element.getAttribute("name"),
            href: href.value,
            href_selector: href.selectable ? rawHref : null,
            href_selectable: href.selectable,
            input_type: element.getAttribute("type"),
            placeholder: clipped(element.getAttribute("placeholder")),
            bounds: {
                x: Math.round(rect.x * 100) / 100,
                y: Math.round(rect.y * 100) / 100,
                width: Math.round(rect.width * 100) / 100,
                height: Math.round(rect.height * 100) / 100
            }
        };
    });
    return {
        url: safeUrl(window.location.href, window.location.href).value,
        title: document.title,
        total_count: allVisible.length,
        elements
    };
})();
"""


class DiscoveryRuntime(Protocol):
    def goto(self, url: str) -> None:
        ...

    def evaluate(self, script: str) -> Any:
        ...


@dataclass(frozen=True)
class LocatorCandidate:
    strategy: str
    selector: str

    def to_dict(self) -> dict[str, str]:
        return {"strategy": self.strategy, "selector": self.selector}


@dataclass(frozen=True)
class DiscoveredElement:
    index: int
    tag: str
    role: str | None
    name: str | None
    text: str | None
    selector: str | None
    locator_strategy: str | None
    locator_candidates: tuple[LocatorCandidate, ...]
    attributes: dict[str, Any]
    bounds: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "tag": self.tag,
            "role": self.role,
            "name": self.name,
            "text": self.text,
            "selector": self.selector,
            "locator_strategy": self.locator_strategy,
            "locator_candidates": [
                candidate.to_dict() for candidate in self.locator_candidates
            ],
            "attributes": dict(self.attributes),
            "bounds": dict(self.bounds),
        }


@dataclass(frozen=True)
class PageDiscoveryReport:
    url: str
    title: str
    total_visible_interactive: int
    truncated: bool
    elements: tuple[DiscoveredElement, ...]
    ambiguities: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        actionable = sum(element.selector is not None for element in self.elements)
        return {
            "schema": "hermes.discovery.v1",
            "url": self.url,
            "title": self.title,
            "summary": {
                "total_visible_interactive": self.total_visible_interactive,
                "included": len(self.elements),
                "actionable_with_selector": actionable,
                "unresolved_without_selector": len(self.elements) - actionable,
                "truncated": self.truncated,
            },
            "elements": [element.to_dict() for element in self.elements],
            "ambiguities": [dict(ambiguity) for ambiguity in self.ambiguities],
        }


@dataclass(frozen=True)
class PageDiscoveryService:
    runtime: DiscoveryRuntime

    def discover(
        self,
        url: str,
        max_elements: int = DEFAULT_MAX_DISCOVERY_ELEMENTS,
    ) -> PageDiscoveryReport:
        if not url.strip():
            raise ValueError("Discovery URL cannot be empty")
        parsed_url = urlsplit(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("Discovery URL must be an absolute HTTP or HTTPS URL")
        if max_elements <= 0:
            raise ValueError("Discovery max elements must be positive")
        if max_elements > MAX_DISCOVERY_ELEMENTS:
            raise ValueError(
                f"Discovery max elements cannot exceed {MAX_DISCOVERY_ELEMENTS}"
            )

        self.runtime.goto(url)
        script = DISCOVERY_SCRIPT.replace("__MAX_ELEMENTS__", str(max_elements))
        payload = self.runtime.evaluate(script)
        return build_discovery_report(payload)


def build_discovery_report(payload: Any) -> PageDiscoveryReport:
    if not isinstance(payload, dict):
        raise ValueError("Discovery result must be an object")

    url = payload.get("url")
    title = payload.get("title")
    total_count = payload.get("total_count")
    raw_elements = payload.get("elements")
    if not isinstance(url, str) or not isinstance(title, str):
        raise ValueError("Discovery result requires string URL and title")
    if not isinstance(total_count, int) or total_count < 0:
        raise ValueError("Discovery result requires non-negative total_count")
    if not isinstance(raw_elements, list):
        raise ValueError("Discovery result requires elements list")

    normalized = [_normalize_element(index, item) for index, item in enumerate(raw_elements)]
    truncated = total_count > len(normalized)
    counts = _identity_counts(normalized)
    if truncated:
        _mark_counts_non_unique(counts)
    elements = tuple(_build_element(item, counts) for item in normalized)
    ambiguities = list(_build_ambiguities(elements))
    if truncated:
        ambiguities.append(
            {
                "kind": "truncated_catalog",
                "omitted_count": total_count - len(elements),
            }
        )
    return PageDiscoveryReport(
        url=url,
        title=title,
        total_visible_interactive=total_count,
        truncated=truncated,
        elements=elements,
        ambiguities=tuple(ambiguities),
    )


def _normalize_element(index: int, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"Discovery element {index} must be an object")
    tag = payload.get("tag")
    if not isinstance(tag, str) or not tag:
        raise ValueError(f"Discovery element {index} requires tag")

    result = dict(payload)
    result["index"] = index
    result["tag"] = tag.lower()
    for field_name in ("role", "name", "text"):
        result[field_name] = _optional_text(
            payload.get(field_name),
            max_length=MAX_TEXT_LENGTH,
        )
    for field_name in (
        "test_id",
        "id",
        "name_attribute",
        "input_type",
        "placeholder",
    ):
        result[field_name] = _optional_text(payload.get(field_name))
    result["href"] = _optional_text(payload.get("href"))
    result["href_selector"] = _optional_text(payload.get("href_selector"))
    result["href_selectable"] = payload.get("href_selectable") is True
    bounds = payload.get("bounds", {})
    if not isinstance(bounds, dict):
        raise ValueError(f"Discovery element {index} bounds must be an object")
    result["bounds"] = {
        key: float(bounds.get(key, 0.0)) for key in ("x", "y", "width", "height")
    }
    return result


def _optional_text(value: Any, max_length: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    if max_length is not None:
        normalized = normalized[:max_length]
    return normalized or None


def _identity_counts(elements: list[dict[str, Any]]) -> dict[str, Counter[Any]]:
    return {
        "test_id": Counter(item["test_id"] for item in elements if item["test_id"]),
        "id": Counter(item["id"] for item in elements if item["id"]),
        "name_attribute": Counter(
            item["name_attribute"] for item in elements if item["name_attribute"]
        ),
        "href": Counter(
            item["href_selector"]
            for item in elements
            if item["href_selector"] and item["href_selectable"]
        ),
        "role_name": Counter(
            (item["role"], item["name"])
            for item in elements
            if item["role"] and item["name"]
        ),
        "text": Counter(item["text"] for item in elements if item["text"]),
    }


def _mark_counts_non_unique(counts: dict[str, Counter[Any]]) -> None:
    for counter in counts.values():
        for identity in tuple(counter):
            counter[identity] = max(counter[identity], 2)


def _build_element(
    item: dict[str, Any],
    counts: dict[str, Counter[Any]],
) -> DiscoveredElement:
    candidates: list[LocatorCandidate] = []
    _add_attribute_candidate(candidates, item, counts, "test_id", "data-testid")
    _add_attribute_candidate(candidates, item, counts, "id", "id")
    _add_attribute_candidate(candidates, item, counts, "name_attribute", "name")

    href = item["href_selector"]
    if href and item["href_selectable"] and counts["href"][href] == 1:
        candidates.append(
            LocatorCandidate("href", f'a[href="{_escape_selector_text(href)}"]')
        )

    role_name = (item["role"], item["name"])
    if all(role_name) and counts["role_name"][role_name] == 1:
        candidates.append(
            LocatorCandidate(
                "role_name",
                f'role={item["role"]}[name="{_escape_selector_text(item["name"])}"]',
            )
        )

    text = item["text"]
    if text and len(text) <= MAX_LOCATOR_TEXT_LENGTH and counts["text"][text] == 1:
        candidates.append(
            LocatorCandidate("exact_text", f'text="{_escape_selector_text(text)}"')
        )

    selected = candidates[0] if candidates else None
    attributes = {
        key: item.get(key)
        for key in (
            "test_id",
            "id",
            "name_attribute",
            "href",
            "input_type",
            "placeholder",
        )
        if item.get(key) is not None
    }
    return DiscoveredElement(
        index=item["index"],
        tag=item["tag"],
        role=item["role"],
        name=item["name"],
        text=item["text"],
        selector=selected.selector if selected else None,
        locator_strategy=selected.strategy if selected else None,
        locator_candidates=tuple(candidates),
        attributes=attributes,
        bounds=item["bounds"],
    )


def _add_attribute_candidate(
    candidates: list[LocatorCandidate],
    item: dict[str, Any],
    counts: dict[str, Counter[Any]],
    field_name: str,
    attribute_name: str,
) -> None:
    value = item[field_name]
    if value and counts[field_name][value] == 1:
        candidates.append(
            LocatorCandidate(
                field_name,
                f'[{attribute_name}="{_escape_selector_text(value)}"]',
            )
        )


def _build_ambiguities(
    elements: tuple[DiscoveredElement, ...],
) -> tuple[dict[str, Any], ...]:
    role_groups: dict[tuple[str, str], list[int]] = {}
    for element in elements:
        if element.role and element.name:
            role_groups.setdefault((element.role, element.name), []).append(element.index)

    ambiguities: list[dict[str, Any]] = [
        {
            "kind": "duplicate_role_name",
            "role": role,
            "name": name,
            "element_indices": indices,
        }
        for (role, name), indices in sorted(role_groups.items())
        if len(indices) > 1
    ]

    for field_name in ("test_id", "id", "name_attribute", "href"):
        groups: dict[str, list[int]] = {}
        for element in elements:
            value = element.attributes.get(field_name)
            if isinstance(value, str) and value:
                groups.setdefault(value, []).append(element.index)
        ambiguities.extend(
            {
                "kind": f"duplicate_{field_name}",
                "value": value,
                "element_indices": indices,
            }
            for value, indices in sorted(groups.items())
            if len(indices) > 1
        )

    return tuple(ambiguities)


def _escape_selector_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
