"""Canonical CLI entry point for local companion.

Usage:
    python -m hermes_screencast.local_companion.cli \
        --host 127.0.0.1 \
        --port 0 \
        --chrome-path "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"

Startup contract:
    - Binds to 127.0.0.1 only
    - Prints COMPANION_PORT:<port> exactly once, with flush=True, after successful start_server
    - Continues running until Ctrl+C or termination
    - Cleanup of owned processes on exit
"""

import argparse
import asyncio
import logging
import sys
import socket
from typing import Optional

from .companion import (
    LocalCompanion,
    CompanionMode,
    UnifiedCompanionConfig,
    LocalCompanionConfig,
)

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hermes local companion server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Startup contract:
  - Binds to 127.0.0.1 only
  - Prints COMPANION_PORT:<port> exactly once after successful start
  - Continues running until Ctrl+C
  - Chrome is NOT launched at startup; it starts only after START_SESSION
        """,
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind to (must be 127.0.0.1)")
    parser.add_argument("--port", type=int, default=0,
                        help="Port to listen on (0 = auto-select)")
    parser.add_argument("--chrome-path", default=None,
                        help="Path to Chrome executable")
    parser.add_argument("--headless", action="store_true",
                        help="Run browser in headless mode")
    parser.add_argument("--browser-startup", default="playwright",
                        choices=["playwright", "raw-cdp", "existing-cdp"],
                        help="Browser startup strategy (default: playwright)")
    parser.add_argument("--auth-wait-seconds", type=int, default=300,
                        help="Maximum seconds to wait for authentication (default: 300)")
    parser.add_argument("--cdp-endpoint", default=None,
                        help="Full CDP endpoint URL (e.g., http://127.0.0.1:9222)")
    parser.add_argument("--cdp-host", default="127.0.0.1",
                        help="CDP host for existing-cdp mode (default: 127.0.0.1)")
    parser.add_argument("--cdp-port", type=int, default=9222,
                        help="CDP port for existing-cdp mode (default: 9222)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate arguments and exit without starting server")
    return parser


async def run(args: argparse.Namespace) -> int:
    """Run the companion with parsed arguments."""
    if args.host != "127.0.0.1":
        print(f"ERROR: host must be 127.0.0.1, got '{args.host}'", flush=True)
        return 1

    if args.dry_run:
        print("DRY RUN: Companion would start with:", flush=True)
        print(f"  host={args.host}", flush=True)
        print(f"  port={args.port}", flush=True)
        print(f"  chrome_path={args.chrome_path}", flush=True)
        print(f"  headless={args.headless}", flush=True)
        print(f"  browser_startup={args.browser_startup}", flush=True)
        print(f"  cdp_endpoint={args.cdp_endpoint}", flush=True)
        print(f"  cdp_host={args.cdp_host}", flush=True)
        print(f"  cdp_port={args.cdp_port}", flush=True)
        print(f"  auth_wait_seconds={args.auth_wait_seconds}", flush=True)
        return 0

    config = UnifiedCompanionConfig(
        mode=CompanionMode.LOCAL,
        local=LocalCompanionConfig(
            host=args.host,
            port=args.port,
            chrome_path=args.chrome_path,
            headless=args.headless,
            browser_startup=args.browser_startup,
            cdp_endpoint=args.cdp_endpoint,
            cdp_host=args.cdp_host,
            cdp_port=args.cdp_port,
            auth_wait_seconds=args.auth_wait_seconds,
        ),
    )

    companion = LocalCompanion(config)
    try:
        await companion.start()
        # Print the canonical startup marker exactly once
        print(f"COMPANION_PORT:{companion.local_port}", flush=True)
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        return 1
    finally:
        await companion.stop()

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())