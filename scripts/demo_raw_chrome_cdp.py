#!/usr/bin/env python3
"""Smoke test for raw Chrome CDP startup on Windows.

Usage (via PowerShell launcher on Windows):
    .venv/Scripts/python.exe scripts/demo_raw_chrome_cdp.py ^
        --chrome-path "C:/Program Files/Google/Chrome/Application/chrome.exe" ^
        --profile-dir "$env:LOCALAPPDATA/Hermes/Profiles/raw-cdp-smoke"

Or directly on Linux (for test validation only):
    python scripts/demo_raw_chrome_cdp.py --help
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("raw-cdp-smoke")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test raw Chrome CDP startup (Windows E2E)."
    )
    parser.add_argument(
        "--chrome-path",
        help="Path to Chrome/Chromium executable.",
    )
    parser.add_argument(
        "--profile-dir",
        required=True,
        help="Chrome persistent profile directory (separate from personal profile).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Seconds to wait for DevToolsActivePort (default: 30).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate arguments without launching Chrome.",
    )
    return parser.parse_args(argv[1:] if argv else None)


def _find_chrome() -> str | None:
    """Search common Windows Chrome install locations."""
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        # Explicit --chrome-path already handled before calling this
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c

    # Program Files, Program Files (x86), Local AppData
    prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    local_appdata = os.environ.get("LOCALAPPDATA", "")

    search_paths = [
        os.path.join(prog_files, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(prog_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
    ]
    if local_appdata:
        search_paths.append(
            os.path.join(local_appdata, "Google", "Chrome", "Application", "chrome.exe")
        )

    for p in search_paths:
        if os.path.isfile(p):
            return p
    return None


def _get_smoke_profile_dir(profile_dir_arg: str) -> str:
    """Return the explicit profile dir; no personal profile fallback."""
    return profile_dir_arg


def main() -> int:
    args = parse_args()
    chrome_path = args.chrome_path or _find_chrome() or "chrome"

    profile_dir = _get_smoke_profile_dir(args.profile_dir)

    if args.dry_run:
        logger.info("smoke_test_status=dry_run chrome_path=%s profile_dir=%s", chrome_path, profile_dir)
        return 0

    # Import the production class
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from src.hermes_screencast.local_companion.raw_chrome import (
            RawChromeCdpProcess,
            RawChromeStartupError,
        )
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        logger.error("smoke_test_status=failed error=import:%s", e)
        return 1

    raw = RawChromeCdpProcess(
        chrome_path=chrome_path,
        profile_dir=profile_dir,
        target_url="about:blank",
    )

    try:
        raw.start(timeout=float(args.timeout))
    except RawChromeStartupError as e:
        logger.error("smoke_test_status=failed error=startup:%s", e)
        return 1

    logger.info("chrome_pid=%d", raw.pid)
    logger.info("cdp_host=127.0.0.1")
    logger.info("cdp_port=%d", raw.cdp_port)

    try:
        with sync_playwright() as p:
            cdp_url = raw.cdp_endpoint
            if not cdp_url:
                logger.error("smoke_test_status=failed error=no_cdp_endpoint")
                return 1
            browser = p.chromium.connect_over_cdp(cdp_url)
            if not browser.contexts:
                logger.error("smoke_test_status=failed error=no_contexts")
                browser.close()
                return 1
            page = browser.contexts[0].pages[0] if browser.contexts[0].pages else browser.contexts[0].new_page()
            logger.info("page_url=%s", page.url)
            logger.info("page_title=%s", page.title())
            logger.info("smoke_test_status=passed")
            browser.close()
    except Exception as e:
        logger.error("smoke_test_status=failed error=cdp_connect:%s", e)
        return 1
    finally:
        raw.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())