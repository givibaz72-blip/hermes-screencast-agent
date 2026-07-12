from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from hermes_screencast.demo.discovery import (
    PageDiscoveryService,
    build_discovery_report,
)


def element(**overrides) -> dict[str, Any]:
    payload = {
        "tag": "button",
        "role": "button",
        "name": "Save",
        "text": "Save",
        "test_id": None,
        "id": None,
        "name_attribute": None,
        "href": None,
        "href_selector": None,
        "href_selectable": False,
        "input_type": None,
        "placeholder": None,
        "bounds": {"x": 10, "y": 20, "width": 100, "height": 40},
    }
    payload.update(overrides)
    return payload


def report_payload(elements, total_count=None) -> dict[str, Any]:
    return {
        "url": "https://example.com/dashboard",
        "title": "Dashboard",
        "total_count": len(elements) if total_count is None else total_count,
        "elements": elements,
    }


def test_discovery_prefers_unique_test_id_and_lists_fallbacks() -> None:
    report = build_discovery_report(
        report_payload(
            [
                element(
                    test_id="save-button",
                    id="save",
                    name_attribute="save",
                )
            ]
        )
    )

    discovered = report.elements[0]
    assert discovered.selector == '[data-testid="save-button"]'
    assert discovered.locator_strategy == "test_id"
    assert [candidate.strategy for candidate in discovered.locator_candidates] == [
        "test_id",
        "id",
        "name_attribute",
        "role_name",
        "exact_text",
    ]


def test_discovery_marks_duplicate_role_and_name_as_ambiguous() -> None:
    report = build_discovery_report(
        report_payload([element(), element()])
    )

    assert report.elements[0].selector is None
    assert report.elements[1].selector is None
    assert report.ambiguities == (
        {
            "kind": "duplicate_role_name",
            "role": "button",
            "name": "Save",
            "element_indices": [0, 1],
        },
    )
    assert report.to_dict()["summary"]["unresolved_without_selector"] == 2


def test_unique_ids_resolve_elements_with_duplicate_accessible_names() -> None:
    report = build_discovery_report(
        report_payload([element(id="save-top"), element(id="save-bottom")])
    )

    assert [item.selector for item in report.elements] == [
        '[id="save-top"]',
        '[id="save-bottom"]',
    ]
    assert len(report.ambiguities) == 1


def test_duplicate_test_ids_are_reported_and_not_selected() -> None:
    report = build_discovery_report(
        report_payload(
            [
                element(test_id="action", name="Save", text="Save"),
                element(test_id="action", name="Cancel", text="Cancel"),
            ]
        )
    )

    assert all(item.locator_strategy == "role_name" for item in report.elements)
    assert {
        "kind": "duplicate_test_id",
        "value": "action",
        "element_indices": [0, 1],
    } in report.ambiguities


def test_sensitive_href_is_reported_but_never_used_as_selector() -> None:
    report = build_discovery_report(
        report_payload(
            [
                element(
                    tag="a",
                    role="link",
                    name=None,
                    text=None,
                    href="https://example.com/reset?token=REDACTED",
                    href_selector=None,
                    href_selectable=False,
                )
            ]
        )
    )

    discovered = report.elements[0]
    assert discovered.selector is None
    assert discovered.attributes["href"].endswith("token=REDACTED")


def test_safe_relative_href_can_be_used_as_selector() -> None:
    report = build_discovery_report(
        report_payload(
            [
                element(
                    tag="a",
                    role="link",
                    name="Pricing",
                    text="Pricing",
                    href="https://example.com/pricing",
                    href_selector="/pricing",
                    href_selectable=True,
                )
            ]
        )
    )

    assert report.elements[0].selector == 'a[href="/pricing"]'
    assert report.elements[0].locator_strategy == "href"


def test_report_summarizes_truncated_results() -> None:
    report = build_discovery_report(report_payload([element()], total_count=12))

    assert report.truncated is True
    assert report.to_dict()["summary"] == {
        "total_visible_interactive": 12,
        "included": 1,
        "actionable_with_selector": 0,
        "unresolved_without_selector": 1,
        "truncated": True,
    }
    assert report.ambiguities[-1] == {
        "kind": "truncated_catalog",
        "omitted_count": 11,
    }


@dataclass
class FakeRuntime:
    payload: dict[str, Any]
    calls: list[tuple[str, str]] = field(default_factory=list)

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

    def evaluate(self, script: str) -> Any:
        self.calls.append(("evaluate", script))
        return self.payload


def test_page_discovery_service_opens_page_and_limits_collection() -> None:
    runtime = FakeRuntime(report_payload([element()]))

    report = PageDiscoveryService(runtime=runtime).discover(
        "https://example.com/dashboard",
        max_elements=25,
    )

    assert report.title == "Dashboard"
    assert runtime.calls[0] == ("goto", "https://example.com/dashboard")
    assert "const maxElements = 25" in runtime.calls[1][1]
    assert "element.value" not in runtime.calls[1][1]


def test_page_discovery_rejects_invalid_limit_before_browser_use() -> None:
    runtime = FakeRuntime(report_payload([]))

    with pytest.raises(ValueError, match="must be positive"):
        PageDiscoveryService(runtime=runtime).discover(
            "https://example.com",
            max_elements=0,
        )

    assert runtime.calls == []


def test_page_discovery_rejects_non_web_url_before_browser_use() -> None:
    runtime = FakeRuntime(report_payload([]))

    with pytest.raises(ValueError, match="absolute HTTP or HTTPS"):
        PageDiscoveryService(runtime=runtime).discover("javascript:alert(1)")

    assert runtime.calls == []


def test_page_discovery_rejects_excessive_limit_before_browser_use() -> None:
    runtime = FakeRuntime(report_payload([]))

    with pytest.raises(ValueError, match="cannot exceed 1000"):
        PageDiscoveryService(runtime=runtime).discover(
            "https://example.com",
            max_elements=1001,
        )

    assert runtime.calls == []


def test_discovery_script_redacts_url_secrets() -> None:
    runtime = FakeRuntime(report_payload([]))

    PageDiscoveryService(runtime=runtime).discover("https://example.com")

    script = runtime.calls[1][1]
    assert 'url.username = ""' in script
    assert 'url.password = ""' in script
    assert "REDACTED" in script
    assert "interactiveRoles" in script


def test_discovery_rejects_invalid_browser_payload() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        build_discovery_report([])
