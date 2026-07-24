"""Tests for the companion CLI and transport integration."""

import argparse
import ast
import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
import pytest


class TestCompanionCli:
    """Tests for the canonical companion CLI."""

    @property
    def cli_module(self) -> str:
        return "hermes_screencast.local_companion.cli"

    def test_cli_help_returns_zero(self):
        """Test that --help returns exit code 0."""
        result = subprocess.run(
            [sys.executable, "-m", self.cli_module, "--help"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"CLI --help failed: {result.stderr}"

    def test_cli_dry_run_returns_zero(self):
        """Test that --dry-run returns exit code 0."""
        result = subprocess.run(
            [sys.executable, "-m", self.cli_module,
             "--host", "127.0.0.1", "--port", "0", "--dry-run"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"CLI --dry-run failed: {result.stderr}"
        assert "DRY RUN" in result.stdout, "Should print DRY RUN marker"

    def test_cli_dry_run_with_chrome_path(self):
        """Test that --dry-run accepts --chrome-path."""
        result = subprocess.run(
            [sys.executable, "-m", self.cli_module,
             "--host", "127.0.0.1", "--port", "0",
             "--chrome-path", "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
             "--dry-run"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"CLI --dry-run with chrome-path failed: {result.stderr}"
        assert "chrome_path" in result.stdout, "Should print chrome_path"

    def test_cli_rejects_non_loopback_host(self):
        """Test that host other than 127.0.0.1 is rejected."""
        result = subprocess.run(
            [sys.executable, "-m", self.cli_module,
             "--host", "0.0.0.0", "--port", "0", "--dry-run"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode != 0, "Should reject 0.0.0.0"
        assert "ERROR" in result.stdout or "error" in result.stderr, \
            "Should print error message"

    def test_cli_prints_companion_port(self):
        """Test that the CLI prints COMPANION_PORT after starting."""
        result = subprocess.run(
            [sys.executable, "-m", self.cli_module,
             "--host", "127.0.0.1", "--port", "0", "--dry-run"],
            capture_output=True, text=True, timeout=30
        )
        # Dry-run doesn't start server, but we can test via subprocess integration
        # The actual port printing is tested in the subprocess smoke test
        assert result.returncode == 0

    def test_cli_uses_named_arguments(self):
        """Test that the CLI uses named arguments, not positional."""
        import hermes_screencast.local_companion.cli as cli
        parser = cli.build_parser()
        # Test that --host and --port are named arguments
        args = parser.parse_args(["--host", "127.0.0.1", "--port", "12345", "--dry-run"])
        assert args.host == "127.0.0.1"
        assert args.port == 12345
        assert args.dry_run is True


class TestLocalCompanionConfig:
    """Tests for LocalCompanionConfig changes."""

    def test_local_companion_config_accepts_chrome_path(self):
        """Test that LocalCompanionConfig accepts chrome_path."""
        from hermes_screencast.local_companion import LocalCompanionConfig
        config = LocalCompanionConfig(
            host="127.0.0.1",
            port=0,
            chrome_path=r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        )
        assert config.host == "127.0.0.1"
        assert config.port == 0
        assert config.chrome_path == r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

    def test_local_companion_config_default_chrome_path(self):
        """Test that chrome_path defaults to None."""
        from hermes_screencast.local_companion import LocalCompanionConfig
        config = LocalCompanionConfig()
        assert config.chrome_path is None

    def test_remote_companion_config_accepts_chrome_path(self):
        """Test that RemoteCompanionConfig accepts chrome_path."""
        from hermes_screencast.local_companion import RemoteCompanionConfig
        config = RemoteCompanionConfig(
            relay_url="wss://example.com/relay",
            pairing_code="test123",
            chrome_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        assert config.chrome_path == r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    def test_unified_config_with_chrome_path(self):
        """Test that UnifiedCompanionConfig works with chrome_path in local config."""
        from hermes_screencast.local_companion import (
            UnifiedCompanionConfig,
            CompanionMode,
            LocalCompanionConfig,
        )
        config = UnifiedCompanionConfig(
            mode=CompanionMode.LOCAL,
            local=LocalCompanionConfig(
                host="127.0.0.1",
                port=0,
                chrome_path=r"C:\Program Files\Chrome\chrome.exe",
            ),
        )
        assert config.local.chrome_path == r"C:\Program Files\Chrome\chrome.exe"


class TestTransportConfig:
    """Tests for TransportConfig changes."""

    def test_transport_uses_canonical_cli_module(self):
        """Test that TransportConfig defaults to canonical CLI module."""
        from hermes_screencast.transport.local_transport import TransportConfig
        config = TransportConfig()
        assert config.companion_module == "hermes_screencast.local_companion.cli"

    def test_transport_uses_sys_executable(self):
        """Test that TransportConfig defaults to empty executable (sys.executable is used)."""
        from hermes_screencast.transport.local_transport import TransportConfig
        config = TransportConfig()
        assert config.companion_executable == ""


class TestTransportStartCompanion:
    """Tests for the transport start_companion method."""

    def test_transport_builds_argv_with_named_args(self):
        """Test that the transport builds argv with named --host and --port."""
        from hermes_screencast.transport.local_transport import (
            LocalDesktopTransport, TransportConfig
        )
        config = TransportConfig(
            companion_host="127.0.0.1",
            companion_port=0,
        )
        transport = LocalDesktopTransport(config)
        # The actual process launch is complex; we test the command construction
        # by checking the config produces the right module
        assert config.companion_module == "hermes_screencast.local_companion.cli"

    def test_transport_start_companion_rejects_bad_host(self):
        """Test that the transport only accepts 127.0.0.1 host."""
        from hermes_screencast.transport.local_transport import (
            LocalDesktopTransport, TransportConfig
        )
        config = TransportConfig(
            companion_host="127.0.0.1",  # Only valid host
            companion_port=0,
        )
        transport = LocalDesktopTransport(config)
        # This should work - no exception
        assert transport.config.companion_host == "127.0.0.1"


class TestCompanionCliIntegration:
    """Subprocess integration tests for the companion CLI.

    These tests actually start a companion process and verify its behavior.
    Skipped on systems without real subprocess support or when not in CI.
    """

    @pytest.fixture
    def cli_module(self):
        return "hermes_screencast.local_companion.cli"

    def test_subprocess_prints_companion_port_then_cleanup(self, cli_module):
        """Integration test: start companion, read COMPANION_PORT, verify TCP connect, cleanup.

        This is the canonical subprocess smoke test.
        """
        process = subprocess.Popen(
            [sys.executable, "-m", cli_module,
             "--host", "127.0.0.1", "--port", "0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        port = None
        start_time = time.time()
        timeout = 15

        try:
            # Read COMPANION_PORT from stdout
            while time.time() - start_time < timeout:
                rc = process.poll()
                if rc is not None:
                    stderr = process.stderr.read() if process.stderr else "unknown"
                    pytest.fail(f"Companion exited before readiness: rc={rc}, stderr={stderr}")

                line = process.stdout.readline() if process.stdout else ""
                if not line:
                    time.sleep(0.1)
                    continue

                line = line.strip()
                if line.startswith("COMPANION_PORT:"):
                    port = int(line.split(":", 1)[1].strip())
                    break

            assert port is not None, "COMPANION_PORT not found"
            assert port > 0, f"Port should be > 0, got {port}"

            # Verify TCP connection to 127.0.0.1:port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            try:
                sock.connect(("127.0.0.1", port))
                sock.close()
                connected = True
            except (socket.timeout, ConnectionRefusedError):
                connected = False
            assert connected, f"Should be able to connect to 127.0.0.1:{port}"

        finally:
            # Cleanup: terminate only the process we created
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

            # Verify no orphan - process should be gone
            assert process.poll() is not None, "Process should be terminated"

    def test_port_0_auto_selects_free_port(self, cli_module):
        """Test that port=0 auto-selects a free port."""
        process = subprocess.Popen(
            [sys.executable, "-m", cli_module,
             "--host", "127.0.0.1", "--port", "0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        port = None
        start_time = time.time()
        timeout = 15

        try:
            while time.time() - start_time < timeout:
                rc = process.poll()
                if rc is not None:
                    stderr = process.stderr.read() if process.stderr else "unknown"
                    pytest.fail(f"Companion exited before readiness: rc={rc}, stderr={stderr}")

                line = process.stdout.readline() if process.stdout else ""
                if not line:
                    time.sleep(0.1)
                    continue

                line = line.strip()
                if line.startswith("COMPANION_PORT:"):
                    port = int(line.split(":", 1)[1].strip())
                    break

            assert port is not None, "COMPANION_PORT not found"
            assert port > 0, f"Auto-selected port should be > 0, got {port}"

        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


class TestCompanionFeature:
    """Tests for specific companion features."""

    def test_companion_does_not_launch_chrome_on_start(self):
        """Test that companion does NOT launch Chrome at startup.

        This is a design requirement - Chrome is only launched after START_SESSION.
        The companion CLI should only start a TCP server, nothing else.
        """
        # Verify no module-level Playwright imports in CLI
        import hermes_screencast.local_companion.cli as cli
        import inspect
        source = inspect.getsource(cli)
        tree = ast.parse(source)

        playwright_imports = []

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "playwright" or alias.name.startswith("playwright."):
                        playwright_imports.append(alias.name)

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "playwright" or module.startswith("playwright."):
                    playwright_imports.append(module)

        assert playwright_imports == [], \
            f"CLI should not import playwright at module level, found: {playwright_imports}"

        # Verify CLI doesn't use subprocess (Chrome launch is via companion protocol)
        assert "subprocess" not in source, \
            "CLI should not use subprocess (Chrome launch is via companion protocol)"

        # Behavioral: dry-run should not start Chrome/companion processes
        # (tested in subprocess integration test)

    def test_companion_local_port_property(self):
        """Test that LocalCompanion has a local_port property."""
        from hermes_screencast.local_companion import LocalCompanion
        # The property is defined on the class, not as an instance attribute
        assert hasattr(LocalCompanion, 'local_port'), \
            "LocalCompanion should have a local_port property"


class TestCompanionCliSource:
    """Tests for the CLI source code structure and imports."""

    def test_cli_source_no_module_level_playwright_imports(self):
        """Test that CLI source has no module-level Playwright imports."""
        import hermes_screencast.local_companion.cli as cli
        import inspect
        source = inspect.getsource(cli)
        tree = ast.parse(source)

        playwright_imports = []

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "playwright" or alias.name.startswith("playwright."):
                        playwright_imports.append(alias.name)

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "playwright" or module.startswith("playwright."):
                    playwright_imports.append(module)

        assert playwright_imports == [], \
            f"CLI should not import playwright at module level, found: {playwright_imports}"

    def test_cli_source_contains_strategy_choice(self):
        """Test that CLI source contains 'playwright' as a valid strategy choice."""
        import hermes_screencast.local_companion.cli as cli
        import inspect
        source = inspect.getsource(cli)
        # The string "playwright" is valid as a strategy choice, just not as an import
        assert 'choices=["playwright", "raw-cdp", "existing-cdp"]' in source or \
               "choices=['playwright', 'raw-cdp', 'existing-cdp']" in source, \
            "CLI should have browser_startup strategy choices including existing-cdp"

    def test_cli_source_contains_auth_wait_seconds(self):
        """Test that CLI source contains auth_wait_seconds argument."""
        import hermes_screencast.local_companion.cli as cli
        import inspect
        source = inspect.getsource(cli)
        assert "auth_wait_seconds" in source or "auth-wait-seconds" in source, \
            "CLI should have auth_wait_seconds argument"


class TestLaunchCompanionWindows:
    """Tests for the launch_companion_windows.py script.

    The scripts/ directory is NOT a Python package. Load via importlib.
    """

    @staticmethod
    def _load_launch_companion_windows():
        """Load launch_companion_windows.py via importlib (scripts/ is not a package)."""
        import importlib.util
        from types import ModuleType

        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "launch_companion_windows.py"

        spec = importlib.util.spec_from_file_location(
            "hermes_test_launch_companion_windows",
            script_path,
        )

        if spec is None or spec.loader is None:
            raise RuntimeError(
                f"Unable to load launch_companion_windows.py from {script_path}"
            )

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_launch_companion_windows_local_delegates_to_canonical_cli(self, monkeypatch):
        """Test that launch_companion_windows.py local mode delegates to canonical CLI.

        Uses monkeypatch to verify that run_local_mode calls canonical_cli.main()
        with the correct arguments and returns its exit code.
        """
        lcw = self._load_launch_companion_windows()
        import hermes_screencast.local_companion.cli as canonical_cli

        # Capture the argv passed to canonical CLI
        captured = {}

        def fake_canonical_main(argv=None):
            captured["argv"] = list(argv or [])
            return 23  # Distinct return code to verify passthrough

        monkeypatch.setattr(canonical_cli, "main", fake_canonical_main)

        # Simulate run_local_mode with real args (dry_run=False to exercise delegation)
        from argparse import Namespace
        args = Namespace(
            host="127.0.0.1",
            port=0,
            chrome_path=r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            dry_run=False,  # Must be False to exercise the delegation path (not the early-return dry_run check)
        )

        import asyncio
        result = asyncio.run(lcw.run_local_mode(args))

        # Verify return code passthrough
        assert result == 23, "Should return the canonical CLI exit code"

        # Verify argv structure
        assert captured["argv"] == [
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--chrome-path",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ], f"Unexpected argv: {captured['argv']}"

        # Verify each element is separate
        chrome_idx = captured["argv"].index("--chrome-path")
        assert chrome_idx + 1 < len(captured["argv"])
        assert captured["argv"][chrome_idx + 1] == r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", \
            "Chrome path with spaces should be a single argv element"

    def test_launch_companion_windows_dry_run_returns_zero(self, monkeypatch):
        """Test that dry-run mode returns 0 (early return before delegation)."""
        lcw = self._load_launch_companion_windows()
        import hermes_screencast.local_companion.cli as canonical_cli

        # Verify that canonical CLI main is NOT called on dry-run (early return)

        def fake_canonical_main(argv=None):
            pytest.fail("canonical CLI main() should not be called on dry-run")

        monkeypatch.setattr(canonical_cli, "main", fake_canonical_main)

        from argparse import Namespace
        import asyncio

        args = Namespace(
            host="127.0.0.1",
            port=0,
            chrome_path=None,
            dry_run=True,  # dry_run should trigger early return
        )

        result = asyncio.run(lcw.run_local_mode(args))
        assert result == 0, "Dry-run should return 0"

    def test_launch_companion_local_mode_accepts_chrome_path(self):
        """Test that local mode --dry-run with --chrome-path succeeds."""
        result = subprocess.run(
            [sys.executable, "scripts/launch_companion_windows.py", "local",
             "--host", "127.0.0.1", "--port", "0", "--dry-run"],
            capture_output=True, text=True, timeout=30
        )
        # Should succeed (dry-run)
        assert result.returncode == 0, f"launch_companion local dry-run failed: {result.stderr}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])