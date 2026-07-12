from __future__ import annotations

import argparse
import json

from hermes_screencast import runner
from hermes_screencast.demo.discovery import PageDiscoveryReport


class FakeRuntime:
    instances = []

    def __init__(self, config) -> None:
        self.config = config
        FakeRuntime.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        pass


class FakeDiscovery:
    calls = []

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def discover(self, url: str, max_elements: int) -> PageDiscoveryReport:
        FakeDiscovery.calls.append((self.runtime, url, max_elements))
        return PageDiscoveryReport(
            url=url,
            title="Product",
            total_visible_interactive=0,
            truncated=False,
            elements=(),
            ambiguities=(),
        )


def test_demo_discover_writes_deterministic_report(tmp_path) -> None:
    FakeRuntime.instances.clear()
    FakeDiscovery.calls.clear()
    output_path = tmp_path / "discovery.json"
    args = argparse.Namespace(
        url="https://example.com",
        output=str(output_path),
        profile="discovery-test",
        headless=True,
        max_elements=50,
    )

    result = runner.run_demo_discover_command(
        args,
        runtime_factory=FakeRuntime,
        discovery_factory=FakeDiscovery,
    )

    assert result == output_path.resolve()
    assert output_path.read_text(encoding="utf-8").endswith("\n")
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "hermes.discovery.v1"
    assert payload["summary"]["included"] == 0
    assert FakeRuntime.instances[0].config.profile == "discovery-test"
    assert FakeRuntime.instances[0].config.headless is True
    assert FakeDiscovery.calls[0][1:] == ("https://example.com", 50)
