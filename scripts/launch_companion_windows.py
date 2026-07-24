#!/usr/bin/env python3
"""
Hermes Local Companion Launcher for Windows.

This script launches the Hermes companion on Windows desktop in two modes:
- local: Development mode, listens on 127.0.0.1 for same-machine backend
- remote: Production mode, initiates outbound TLS WebSocket to relay server
"""

import argparse
import asyncio
import json
import os
import sys
import subprocess
from pathlib import Path
import stat

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hermes_screencast.local_companion import (
    LocalCompanion,
    CompanionMode,
    UnifiedCompanionConfig,
    LocalCompanionConfig,
    RemoteCompanionConfig,
)


def read_pairing_code_file(path: str) -> str:
    """
    Read pairing code from file with security checks.
    
    Args:
        path: Path to pairing code file
        
    Returns:
        Pairing code string
        
    Raises:
        ValueError: If file is invalid, empty, or has insecure permissions
    """
    file_path = Path(path)
    
    # Check file exists
    if not file_path.exists():
        raise ValueError(f"Pairing code file not found: {path}")
    
    if not file_path.is_file():
        raise ValueError(f"Pairing code path is not a file: {path}")
    
    # Check file permissions (POSIX systems only)
    if hasattr(os, 'stat') and hasattr(stat, 'S_IRWXG'):
        try:
            file_stat = file_path.stat()
            mode = file_stat.st_mode
            # Check group/other read/write/execute permissions
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise ValueError(
                    f"Pairing code file has insecure permissions (mode {oct(mode)}). "
                    f"Recommended mode: 0600 (owner read/write only)"
                )
        except OSError:
            pass  # If we can't stat, continue
    
    # Read file content
    try:
        content = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise ValueError(f"Pairing code file is not valid UTF-8: {path}")
    except OSError as e:
        raise ValueError(f"Cannot read pairing code file: {e}")
    
    # Strip only trailing whitespace and newlines
    pairing_code = content.rstrip('\r\n \t')
    
    if not pairing_code:
        raise ValueError("Pairing code file is empty or contains only whitespace")
    
    return pairing_code


def find_chrome_path() -> str | None:
    """Find Chrome executable on Windows."""
    possible_paths = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    
    for path in possible_paths:
        if path.exists():
            return str(path)
    return None


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="Hermes Local Companion Launcher (Windows)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local development mode (listens on 127.0.0.1)
  python scripts/launch_companion_windows.py local --port 0

  # Remote mode (connects to relay server)
  python scripts/launch_companion_windows.py remote \\
    --relay-url wss://relay.example.com:8765 \\
    --pairing-code ABC123DEF456

  # Remote mode with pairing code file
  python scripts/launch_companion_windows.py remote \\
    --relay-url wss://relay.example.com:8765 \\
    --pairing-code-file C:\\Hermes\\pairing-code.txt

  # Remote mode with custom companion ID
  python scripts/launch_companion_windows.py remote \\
    --relay-url wss://relay.example.com:8765 \\
    --pairing-code ABC123DEF456 \\
    --companion-id my-workstation
"""
    )
    
    subparsers = parser.add_subparsers(dest="mode", required=True, help="Operation mode")
    
    # Local mode
    local_parser = subparsers.add_parser("local", help="Local development mode (listens on 127.0.0.1)")
    local_parser.add_argument("--port", type=int, default=0, help="Port to listen on (0 = auto)")
    local_parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (must be 127.0.0.1)")
    local_parser.add_argument("--chrome-path", help="Path to Chrome executable")
    local_parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    
    # Remote mode
    remote_parser = subparsers.add_parser("remote", help="Remote Windows desktop mode (connects to relay)")
    remote_parser.add_argument("--relay-url", required=True, help="Relay server URL (wss://host:port)")
    remote_parser.add_argument("--chrome-path", help="Path to Chrome executable")
    remote_parser.add_argument("--profile-dir", help="Chrome profile directory")
    remote_parser.add_argument("--recording-dir", required=True, help="Recording output directory")
    remote_parser.add_argument("--companion-id", help="Companion identifier")
    remote_parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    
    # Mutually exclusive pairing code sources
    pairing_group = remote_parser.add_mutually_exclusive_group(required=True)
    pairing_group.add_argument("--pairing-code", help="Pairing code from relay")
    pairing_group.add_argument("--pairing-code-file", help="Path to file containing pairing code (mode 0600)")
    
    return parser


async def run_local_mode(args) -> int:
    """Run companion in local development mode using canonical CLI."""
    if args.dry_run:
        print("DRY RUN: Would execute companion in local mode")
        return 0

    if args.host != "127.0.0.1":
        print("ERROR: Local mode must bind to 127.0.0.1")
        return 1

    chrome_path = args.chrome_path or find_chrome_path()
    if chrome_path:
        print(f"Using Chrome: {chrome_path}")

    # Delegate to canonical CLI runner
    import hermes_screencast.local_companion.cli as canonical_cli
    cli_args = [
        "--host", args.host,
        "--port", str(args.port),
    ]
    if chrome_path:
        cli_args += ["--chrome-path", chrome_path]
    return canonical_cli.main(cli_args)


async def run_remote_mode(args) -> int:
    """Run companion in remote mode (connects to relay)."""
    if args.dry_run:
        print("DRY RUN: Would execute companion in remote mode")
        print(f"  Relay URL: {args.relay_url}")
        print(f"  Pairing code: ***REDACTED***")
        return 0
    
    # Read pairing code
    pairing_code = None
    if args.pairing_code_file:
        try:
            pairing_code = read_pairing_code_file(args.pairing_code_file)
        except ValueError as e:
            print(f"Error reading pairing code file: {e}")
            return 1
    elif args.pairing_code:
        pairing_code = args.pairing_code
    
    if not pairing_code:
        print("Error: Pairing code required (use --pairing-code-file or --pairing-code)")
        return 1
    
    if not pairing_code:
        print("Error: Empty pairing code")
        return 1
    
    chrome_path = args.chrome_path or find_chrome_path()
    if chrome_path:
        print(f"Using Chrome: {chrome_path}")
    
    config = UnifiedCompanionConfig(
        mode=CompanionMode.REMOTE,
        remote=RemoteCompanionConfig(
            relay_url=args.relay_url,
            pairing_code=pairing_code,
            companion_id=args.companion_id,
            chrome_path=chrome_path,
            profile_dir=args.profile_dir,
            recording_dir=args.recording_dir,
        ),
    )
    
    companion = LocalCompanion(config)
    try:
        await companion.start()
        print("Remote companion connected to relay")
        print("COMPANION_READY", flush=True)
        
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")
        return 1
    finally:
        await companion.stop()
    
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    
    if args.mode == "local":
        return asyncio.run(run_local_mode(args))
    elif args.mode == "remote":
        return asyncio.run(run_remote_mode(args))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())