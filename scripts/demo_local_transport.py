#!/usr/bin/env python3
"""
Demo: Using Local Desktop Browser Transport with Hermes.

Three modes:
- local: Development mode, runs on same machine (uses 127.0.0.1)
- remote: Production mode, connects to relay server from Windows desktop
- windows-e2e: Same-machine Windows E2E for HeyGen review (no relay, no domain, no TLS)
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
import stat

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hermes_screencast.transport.local_transport import (
    LocalDesktopTransport,
    RemoteDesktopTransport,
    TransportConfig,
    create_transport,
    TopologyMode,
    PairingResult,
)
from hermes_screencast.transport.protocol import (
    SessionConfig,
    SessionStatus,
    AuthStatus,
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
    if os.name == "posix" and hasattr(stat, 'S_IRWXG'):
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
        description="Hermes Local Desktop Browser Transport Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/demo_local_transport.py local
  python scripts/demo_local_transport.py remote --relay-url wss://relay.example.com/desktop-relay --pairing-code-file /run/hermes/pairing-code --profile heygen-review
  python scripts/demo_local_transport.py remote --relay-url wss://relay.example.com/desktop-relay --pairing-code ABC123 --dry-run
  
  # Windows E2E (same machine, no relay, no domain, no TLS)
  python scripts/demo_local_transport.py windows-e2e --profile-dir "%LOCALAPPDATA%\\Hermes\\Profiles\\heygen-review" --recording-dir "%USERPROFILE%\\Videos\\Hermes" --inspect-only
  python scripts/demo_local_transport.py windows-e2e --profile-dir "%LOCALAPPDATA%\\Hermes\\Profiles\\heygen-review" --recording-dir "%USERPROFILE%\\Videos\\Hermes" --success-selector "[data-testid='dashboard']" --record --record-seconds 10 --output-name "heygen-review-demo.mp4"
"""
    )

    subparsers = parser.add_subparsers(dest="mode", required=True, help="Demo mode")

    # Local mode
    local_parser = subparsers.add_parser("local", help="Local development mode (listens on 127.0.0.1)")
    local_parser.add_argument("--port", type=int, default=0, help="Port to listen on (0 = auto)")
    local_parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (must be 127.0.0.1)")
    local_parser.add_argument("--dry-run", action="store_true", help="Show what would be done")

    # Remote mode
    remote_parser = subparsers.add_parser("remote", help="Remote Windows desktop mode (connects to relay)")
    remote_parser.add_argument("--relay-url", required=True, help="Relay server URL (wss://host:port/path)")
    remote_parser.add_argument("--profile", help="Profile name for session")
    remote_parser.add_argument("--target-url", default="https://app.heygen.com/", help="Target URL to open")
    remote_parser.add_argument("--companion-id", help="Companion identifier")
    remote_parser.add_argument("--allow-insecure-local-test", action="store_true", help="Allow ws:// for localhost testing")
    remote_parser.add_argument("--connect-timeout", type=float, default=30.0, help="Connection timeout seconds")
    remote_parser.add_argument("--debug", action="store_true", help="Enable debug output (with secret redaction)")
    remote_parser.add_argument("--dry-run", action="store_true", help="Show what would be done without connecting")
    remote_parser.add_argument("--browser-startup", default="playwright",
                               choices=["playwright", "raw-cdp"],
                               help="Browser startup strategy (default: playwright)")
    remote_parser.add_argument("--auth-wait-seconds", type=int, default=300,
                               help="Maximum seconds to wait for authentication (default: 300)")

    # Inspect-only / recording options
    remote_parser.add_argument("--inspect-only", action="store_true", help="Only inspect page state, no recording")
    remote_parser.add_argument("--record", action="store_true", help="Enable recording (requires --success-selector)")
    remote_parser.add_argument("--record-seconds", type=int, default=10, help="Recording duration in seconds")
    remote_parser.add_argument("--output-name", help="Output filename for recording")
    remote_parser.add_argument("--success-selector", help="CSS selector for authenticated dashboard element")

    # Mutually exclusive pairing code sources
    pairing_group = remote_parser.add_mutually_exclusive_group(required=True)
    pairing_group.add_argument("--pairing-code", help="Pairing code from relay")
    pairing_group.add_argument("--pairing-code-file", help="Path to file containing pairing code (mode 0600)")

    # Windows E2E mode
    windows_e2e_parser = subparsers.add_parser("windows-e2e", help="Same-machine Windows E2E (no relay, no domain, no TLS)")
    windows_e2e_parser.add_argument("--chrome-path", help="Path to Chrome executable (auto-detected if not provided)")
    windows_e2e_parser.add_argument("--profile-dir", required=True, help="Chrome persistent profile directory")
    windows_e2e_parser.add_argument("--recording-dir", required=True, help="Recording output directory")
    windows_e2e_parser.add_argument("--profile", default="heygen-review", help="Profile name for session")
    windows_e2e_parser.add_argument("--target-url", default="https://app.heygen.com/", help="Target URL to open")
    windows_e2e_parser.add_argument("--inspect-only", action="store_true", help="Only inspect page state, no recording (default)")
    windows_e2e_parser.add_argument("--record", action="store_true", help="Enable recording (requires --success-selector)")
    windows_e2e_parser.add_argument("--record-seconds", type=int, default=10, help="Recording duration in seconds")
    windows_e2e_parser.add_argument("--output-name", default="heygen-review-demo.mp4", help="Output filename for recording")
    windows_e2e_parser.add_argument("--success-selector", help="CSS selector for authenticated dashboard element")
    windows_e2e_parser.add_argument("--connect-timeout", type=float, default=30.0, help="Connection timeout seconds")
    windows_e2e_parser.add_argument("--debug", action="store_true", help="Enable debug output")
    windows_e2e_parser.add_argument("--dry-run", action="store_true", help="Show what would be done without starting Chrome/companion/FFmpeg")
    windows_e2e_parser.add_argument("--browser-startup", default="raw-cdp",
                                    choices=["playwright", "raw-cdp"],
                                    help="Browser startup strategy (default: raw-cdp)")
    windows_e2e_parser.add_argument("--auth-wait-seconds", type=int, default=300,
                                    help="Maximum seconds to wait for authentication (default: 300)")

    return parser


async def demo_local(args: argparse.Namespace) -> int:
    """Demo: Local development mode."""
    if args.dry_run:
        print("DRY RUN: Would execute demo in local mode")
        return 0

    print("=" * 60)
    print("Local Development Mode Demo")
    print("=" * 60)

    transport = create_transport(
        TransportConfig(
            topology_mode=TopologyMode.LOCAL_DEVELOPMENT,
            companion_host=args.host,
            companion_port=args.port,
        )
    )

    try:
        print("\n1. Connecting to local companion...")
        port = await transport.connect()
        print(f"   Connected to companion on port {port}")

        # Create session
        profile_dir = Path(tempfile.gettempdir()) / "hermes_profiles" / "local_demo"
        profile_dir.mkdir(parents=True, exist_ok=True)

        session_id, pairing_token = transport.start_session(
            profile_name="local_demo",
            target_url="https://example.com/",
            success_url_prefix="https://example.com/",
            width=1920,
            height=1080,
            headless=False,
        )
        print(f"   Session created: {session_id}")
        print(f"   Pairing token: ***REDACTED***")

        # Open URL
        print("\n2. Opening URL...")
        response = await transport.open_url(session_id, "https://example.com/")
        if not response.success:
            print("   Failed to open URL")
            return 1
        print("   URL opened")

        # Get page state
        print("\n3. Getting page state...")
        state = await transport.get_safe_page_state(session_id)
        print(f"   URL: {state.current_url}")
        print(f"   Title: {state.title}")
        print(f"   Auth status: {state.auth_status}")
        print(f"   Session status: {state.session_status}")

        # Test recording
        output_dir = Path("recordings")
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / "local_demo.mp4"

        print(f"\n4. Starting recording to {output_path}...")
        response = await transport.start_recording(session_id, output_path)
        if response.success:
            print("   Recording started")

            # Record for a moment
            await asyncio.sleep(2)

            print("\n5. Stopping recording...")
            response = await transport.stop_recording(session_id)
            if response.success:
                print("   Recording stopped")

                if output_path.exists():
                    import subprocess
                    result = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries",
                         "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                         str(output_path)],
                        capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        duration = float(result.stdout.strip())
                        print(f"   Video duration: {duration:.1f}s")
            else:
                print("   Failed to stop recording")

    finally:
        print("\n6. Disconnecting...")
        await transport.disconnect()
        print("   Disconnected")

    print("\n" + "=" * 60)
    print("Local demo completed!")
    print("=" * 60)
    return 0


async def demo_remote(args: argparse.Namespace) -> int:
    """Demo: Remote Windows desktop mode."""
    # Check dry-run first - don't read secret files
    if args.dry_run:
        print("DRY RUN: Would execute demo in remote mode")
        print(f"  Relay URL: {args.relay_url}")
        print(f"  Pairing code: ***REDACTED***")
        return 0

    # Read pairing code from file or direct argument
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

    inspect_only = args.inspect_only
    do_record = args.record
    record_seconds = args.record_seconds
    output_name = args.output_name

    # Validate record options
    if do_record:
        if not args.success_selector:
            print("Error: --record requires --success-selector")
            return 1
        if not args.success_selector.strip():
            print("Error: --success-selector cannot be empty")
            return 1
        if not args.success_selector:
            print("Error: For HeyGen, --success-selector is required (root success_url_prefix not allowed)")
            return 1

    if not args.success_selector and not inspect_only:
        print("Error: For HeyGen, --success-selector is required (root success_url_prefix not allowed)")
        return 1

    print("=" * 60)
    print("Remote Windows Desktop Mode Demo")
    print("=" * 60)

    print("\n⚠️  This demo requires:")
    print(f"   - Relay server running at {args.relay_url}")
    print("   - Windows companion connected with pairing code")
    print("   - Pairing code from relay admin (not printed)")

    if inspect_only:
        print("\n🔍 Mode: INSPECT ONLY - will not record")

    if do_record:
        print(f"\n🎬 Mode: RECORD ({args.record_seconds}s) - requires --success-selector")

    # Create transport with full relay URL
    config = TransportConfig(
        topology_mode=TopologyMode.REMOTE_DESKTOP,
        relay_url=args.relay_url,
        allow_insecure_local_test=args.allow_insecure_local_test,
    )
    transport = create_transport(config)

    try:
        print("\n1. Connecting to relay...")
        await transport.connect()
        print(f"   Connected to relay at {args.relay_url}")

        # Pair with companion
        print("\n2. Pairing with companion...")
        pairing_result = await transport.pair(pairing_code, args.companion_id)

        if not pairing_result.success:
            print(f"   Pairing failed: {pairing_result.error}")
            return 1

        print(f"   Paired with companion: {pairing_result.companion_id}")
        if pairing_result.capability_fingerprint:
            print(f"   Capability fingerprint: {pairing_result.capability_fingerprint}")

        # Wait for companion to be ready
        print("\n3. Waiting for companion...")
        if not await transport.wait_for_companion(timeout=args.connect_timeout):
            print("   Timeout waiting for companion")
            return 1
        print("   Companion ready")

        # Create session
        profile_name = args.profile or "remote_demo"
        session_id, _ = await transport.start_session(
            profile_name=args.profile or "remote_demo",
            target_url=args.target_url,
            success_selector=args.success_selector if args.success_selector else "",
            width=1920,
            height=1080,
            headless=False,
            browser_startup=args.browser_startup,
            auth_wait_seconds=args.auth_wait_seconds,
        )
        print(f"\n2. Session created: {session_id}")

        # Open URL
        print(f"\n3. Opening {args.target_url}...")
        response = await transport.open_url(session_id, args.target_url)
        if not response.success:
            print("   Failed to open URL")
            return 1
        print("   URL opened")

        # Get page state
        print("\n4. Getting page state...")
        state = await transport.get_safe_page_state(session_id)
        print(f"   URL: {state.current_url}")
        print(f"   Title: {state.title}")
        print(f"   Auth status: {state.auth_status}")
        print(f"   Session status: {state.session_status}")
        if state.login_markers:
            print(f"   Login markers: {state.login_markers}")
        if state.provider_block_markers:
            print(f"   Provider block markers: {state.provider_block_markers}")

        if inspect_only:
            print("\n🔍 Inspect-only mode: stopping here (no recording)")
            return 0

        # Confirm authentication with proper checks
        print("\n5. Confirming authentication...")
        confirmed, state = await transport.confirm_authentication(session_id)
        if not confirmed:
            print("   Authentication not confirmed")
            print(f"   Current status: {state.auth_status}")
            if state.auth_status == AuthStatus.LOGIN_REQUIRED.value:
                print("   Login required - please sign in")
                print("   Error: dashboard_selector_required")
            elif state.auth_status == AuthStatus.PROVIDER_BLOCKED.value:
                print("   Provider blocked - check for Google unsafe browser or Cloudflare")
                print("   Error: auth_provider_blocked")
            else:
                print("   Error: authentication_not_completed")
            return 1
        print("   Authentication confirmed!")

        # Final re-verification before recording
        print("\n6. Final auth verification before recording...")
        confirmed, state = await transport.confirm_authentication(session_id)
        if not confirmed:
            print("   Authentication lost before recording")
            return 1
        print("   Still authenticated - starting recording")

        # Start recording
        output_filename = args.output_name or f"{args.profile or 'remote'}_demo.mp4"

        print(f"\n7. Starting recording ({args.record_seconds}s)...")
        response = await transport.start_recording(session_id, Path(output_filename))
        if not response.success:
            print(f"   Failed to start recording: {response.error}")
            return 1
        print("   Recording started")

        print(f"\n8. Recording... ({args.record_seconds}s)")
        await asyncio.sleep(args.record_seconds)

        print("\n9. Stopping recording...")
        response = await transport.stop_recording(session_id)
        if response.success:
            print("   Recording stopped")
        else:
            print(f"   Failed to stop recording: {response.error}")

    except asyncio.TimeoutError:
        print("\nTimeout waiting for Windows companion")
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 1
    except Exception as e:
        if args.debug:
            import traceback
            # Redact secrets from traceback
            tb_text = traceback.format_exc()
            for length in range(8, len(pairing_code) + 1):
                tb_text = tb_text.replace(pairing_code[:length], "***REDACTED***")
            tb_text = tb_text.replace(pairing_code, "***REDACTED***")
            print(f"\nError (debug):\n{tb_text}")
        else:
            print(f"\nError: {e}")
        return 1
    finally:
        print("\n10. Finishing session...")
        if 'session_id' in locals() and session_id:
            await transport.finish_session(session_id)
            print("   Session finished")
        await transport.disconnect()
        print("   Disconnected from relay")

    print("\n" + "=" * 60)
    print("Remote demo completed!")
    print("=" * 60)
    return 0


async def validate_selector(probe_state, success_selector: str, target_url: str) -> tuple[bool, str]:
    """
    Validate a success selector against the current page state.

    Returns:
        (authenticated: bool, reason: str)
        authenticated=True only if ALL checks pass:
        - selector exists
        - selector is visible
        - hostname is not auth.heygen.com
        - no login/sign-in markers
        - no Google unsafe-browser markers
        - no Cloudflare block markers
    """
    # Check 1: Selector exists and is visible
    if not probe_state.success_selector_visible:
        return False, "dashboard_selector_missing"
    
    # Check 2: Hostname is not auth.heygen.com
    if "auth.heygen.com" in probe_state.hostname:
        return False, "login_url_detected"
    
    # Check 3: No login markers
    if probe_state.login_markers:
        return False, "login_markers_present"
    
    # Check 4: No provider block markers (Google unsafe browser, Cloudflare)
    if probe_state.provider_block_markers:
        return False, "provider_block_detected"
    
    # Check 5: Auth status is authenticated
    if probe_state.auth_status != AuthStatus.AUTHENTICATED.value:
        return False, "not_authenticated"
    
    return True, "authenticated_selector_confirmed"


async def demo_windows_e2e(args: argparse.Namespace) -> int:
    """Demo: Same-machine Windows E2E for HeyGen review (no relay, no domain, no TLS)."""
    
    # Normalize parameters for backward compatibility with old Namespace objects
    browser_startup = getattr(args, "browser_startup", "raw-cdp")
    auth_wait_seconds = getattr(args, "auth_wait_seconds", 300)

    # Validate normalized parameters
    if browser_startup not in {"raw-cdp", "playwright"}:
        print("Error: unsupported browser startup strategy")
        return 2

    if auth_wait_seconds <= 0:
        print("Error: auth-wait-seconds must be positive")
        return 2

    if args.dry_run:
        print("DRY RUN: Would execute Windows E2E demo")
        print(f"  Profile dir: {args.profile_dir}")
        print(f"  Recording dir: {args.recording_dir}")
        print(f"  Target URL: {args.target_url}")
        print(f"  Profile: {args.profile}")
        print(f"  Inspect only: {args.inspect_only}")
        print(f"  Browser startup: {browser_startup}")
        print(f"  Auth wait seconds: {auth_wait_seconds}")
        if args.record:
            print(f"  Record: {args.record_seconds}s -> {args.output_name}")
            print(f"  Success selector: {args.success_selector}")
        return 0

    # Validate record options
    if args.record:
        if not args.success_selector:
            print("Error: --record requires --success-selector")
            return 1
        if not args.success_selector.strip():
            print("Error: --success-selector cannot be empty")
            return 1

    # Validate output filename
    if args.record:
        output_name = args.output_name
        if not output_name.lower().endswith('.mp4'):
            print("Error: --output-name must end with .mp4")
            return 1
        # Basic safe filename check (no paths, no .., etc.)
        if '/' in output_name or '\\' in output_name or '..' in output_name:
            print("Error: --output-name must be a simple filename (no path separators)")
            return 1

    # Find Chrome
    chrome_path = args.chrome_path or find_chrome_path()
    if not chrome_path:
        print("Error: Chrome not found (chrome_not_found)")
        print("  Checked: %LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe")
        print("  Checked: %PROGRAMFILES%\\Google\\Chrome\\Application\\chrome.exe")
        print("  Checked: %PROGRAMFILES(X86)%\\Google\\Chrome\\Application\\chrome.exe")
        print("  Use --chrome-path to specify explicitly")
        return 1
    print(f"Using Chrome: {chrome_path}")

    # Verify recording directory
    recording_dir = Path(args.recording_dir)
    try:
        recording_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Error creating recording directory: {e}")
        return 1

    # Verify profile directory
    profile_dir = Path(args.profile_dir)
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Error creating profile directory: {e}")
        return 1

    # Check ffmpeg and ffprobe
    for tool in ("ffmpeg", "ffprobe"):
        try:
            import subprocess
            result = subprocess.run([tool, "-version"], capture_output=True, timeout=5)
            if result.returncode != 0:
                print(f"Error: {tool} not found or not working")
                return 1
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print(f"Error: {tool} not found in PATH")
            return 1

    print("=" * 60)
    print("Windows E2E Mode - HeyGen Review (Local Only)")
    print("=" * 60)
    print(f"\nProfile: {args.profile}")
    print(f"Profile dir: {profile_dir}")
    print(f"Recording dir: {recording_dir}")
    print(f"Target URL: {args.target_url}")
    print(f"Chrome: {chrome_path}")

    if args.inspect_only:
        print("\n🔍 Mode: INSPECT ONLY - will not record")
    else:
        print(f"\n🎬 Mode: RECORD ({args.record_seconds}s) -> {args.output_name}")

    # Create transport with LOCAL_DEVELOPMENT mode
    config = TransportConfig(
        topology_mode=TopologyMode.LOCAL_DEVELOPMENT,
        companion_host="127.0.0.1",
        companion_port=0,  # Auto-select
        connection_timeout=args.connect_timeout,
    )
    transport = create_transport(config)

    session_id = None
    try:
        print("\n1. Starting local companion...")
        port = await transport.connect()
        print(f"   Companion listening on 127.0.0.1:{port}")

        print("\n2. Creating session...")
        session_id, pairing_token = await transport.start_session(
            profile_name=args.profile,
            profile_path=profile_dir,
            target_url=args.target_url,
            success_selector=args.success_selector or "",
            width=1920,
            height=1080,
            headless=False,
            chrome_path=chrome_path,
            browser_startup=browser_startup,
            auth_wait_seconds=auth_wait_seconds,
        )
        print(f"   Session created: {session_id}")

        print(f"\n3. Opening {args.target_url}...")
        response = await transport.open_url(session_id, args.target_url)
        if not response.success:
            print(f"   Failed to open URL: {response.error}")
            return 1
        print("   URL opened - Chrome window should be visible")

        if args.inspect_only:
            print("\n🔍 INSPECT-ONLY MODE: Selector Discovery")
            print("   Please manually log in to HeyGen in the Chrome window.")
            print("   Press Ctrl+C when done to see page state.")
            
            # Periodically get safe page state
            print("\n   Waiting for manual login... (polling page state)")
            try:
                while True:
                    await asyncio.sleep(5)
                    state = await transport.get_safe_page_state(session_id)
                    print(f"   URL: {state.current_url}")
                    print(f"   Hostname: {state.hostname}")
                    print(f"   Title: {state.title}")
                    print(f"   Auth status: {state.auth_status}")
                    print(f"   Session status: {state.session_status}")
                    if state.login_markers:
                        print(f"   Login markers: {state.login_markers}")
                    if state.provider_block_markers:
                        print(f"   Provider blocks: {state.provider_block_markers}")
                    if state.success_selector_visible:
                        print(f"   ✓ Success selector VISIBLE: {args.success_selector}")
                    else:
                        if args.success_selector:
                            print(f"   ✗ Success selector NOT VISIBLE: {args.success_selector}")
            except KeyboardInterrupt:
                print("\n   Interrupted - final page state:")
                state = await transport.get_safe_page_state(session_id)
                print(f"   URL: {state.current_url}")
                print(f"   Hostname: {state.hostname}")
                print(f"   Title: {state.title}")
                print(f"   Auth status: {state.auth_status}")
                print(f"   Session status: {state.session_status}")
                if state.login_markers:
                    print(f"   Login markers: {state.login_markers}")
                if state.provider_block_markers:
                    print(f"   Provider blocks: {state.provider_block_markers}")
                if args.success_selector:
                    if state.success_selector_visible:
                        print(f"   ✓ Success selector VISIBLE: {args.success_selector}")
                        print("   Result: authenticated_selector_confirmed")
                    else:
                        print(f"   ✗ Success selector NOT VISIBLE: {args.success_selector}")
                        print("   Result: dashboard_selector_required")
                return 0

        # RECORDING MODE
        if args.success_selector:
            print(f"\n4. Verifying success selector: {args.success_selector}")
            probe_state = await transport.get_safe_page_state(session_id)
            authenticated, reason = await validate_selector(probe_state, args.success_selector, args.target_url)
            if not authenticated:
                print(f"   ✗ Selector probe failed: {reason}")
                print("   Result: dashboard_selector_required")
                return 1
            print(f"   ✓ Selector verified: {reason}")

        print("\n5. Waiting for manual authentication...")
        print("   Please complete login/CAPTCHA/2FA in the Chrome window.")
        
        # Poll for authentication
        auth_confirmed = False
        max_wait = args.auth_wait_seconds  # from CLI arg
        start_time = time.time()
        while time.time() - start_time < max_wait:
            await asyncio.sleep(3)
            state = await transport.get_safe_page_state(session_id)
            print(f"   Status: {state.auth_status} | URL: {state.current_url}")
            
            # Check if authenticated
            if state.auth_status == AuthStatus.AUTHENTICATED.value:
                # Additional selector verification if provided
                if args.success_selector:
                    authenticated, reason = await validate_selector(state, args.success_selector, args.target_url)
                    if authenticated:
                        auth_confirmed = True
                        print(f"   ✓ Authentication confirmed: {reason}")
                        break
                    else:
                        print(f"   Selector check failed: {reason}")
                else:
                    auth_confirmed = True
                    print("   ✓ Authentication confirmed (URL-based)")
                    break
            elif state.auth_status == AuthStatus.PROVIDER_BLOCKED.value:
                print("   ✗ Provider blocked (Google unsafe browser or Cloudflare)")
                print("   Result: auth_provider_blocked")
                return 1

        if not auth_confirmed:
            print("   Timeout waiting for authentication")
            return 1

        # Final re-verification before recording
        print("\n6. Final authentication verification before recording...")
        confirmed, state = await transport.confirm_authentication(session_id)
        if not confirmed:
            print("   Authentication lost before recording")
            if state.auth_status == AuthStatus.LOGIN_REQUIRED.value:
                print("   Result: dashboard_selector_required")
            elif state.auth_status == AuthStatus.PROVIDER_BLOCKED.value:
                print("   Result: auth_provider_blocked")
            else:
                print("   Result: authentication_not_completed")
            return 1
       
        # Extra selector check if provided
        if args.success_selector:
            authenticated, reason = await validate_selector(state, args.success_selector, args.target_url)
            if not authenticated:
                print(f"   Selector verification failed: {reason}")
                print("   Result: dashboard_selector_required")
                return 1
            print(f"   ✓ Final selector check: {reason}")

        print("\n7. Starting recording...")
        output_path = recording_dir / args.output_name
        response = await transport.start_recording(
            session_id,
            output_path,
            fps=30,
            show_recording_indicator=True,
        )
        if not response.success:
            print(f"   Failed to start recording: {response.error}")
            return 1
        print(f"   🔴 Recording started: {output_path}")

        print(f"\n8. Recording for {args.record_seconds} seconds...")
        await asyncio.sleep(args.record_seconds)

        print("\n9. Stopping recording...")
        response = await transport.stop_recording(session_id)
        if response.success:
            print("   Recording stopped")
        else:
            print(f"   Failed to stop recording: {response.error}")
            return 1

        # Verify MP4 with ffprobe
        print("\n10. Verifying recording...")
        import subprocess
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(output_path)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 3:
                codec = lines[0]
                width = lines[1]
                height = lines[2]
                duration = lines[3] if len(lines) > 3 else "unknown"
            else:
                # Fallback parsing
                codec = "unknown"
                width = "unknown"
                height = "unknown"
                duration = "unknown"
           
            file_size = output_path.stat().st_size
            print(f"   artifact_name: {args.output_name}")
            print(f"   size_bytes: {file_size}")
            print(f"   duration: {duration}s")
            print(f"   video_codec: {codec}")
            print(f"   width: {width}")
            print(f"   height: {height}")
            print(f"   path: {output_path.absolute()} (local Windows path, not sent via remote API)")
        else:
            print("   Warning: ffprobe failed to read video metadata")
            print(f"   Output: {result.stderr}")

    except asyncio.TimeoutError:
        print("\nTimeout waiting for companion")
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 1
    except Exception as e:
        if args.debug:
            import traceback
            print(f"\nError (debug):\n{traceback.format_exc()}")
        else:
            print(f"\nError: {e}")
        return 1
    finally:
        print("\n11. Finishing session...")
        if session_id:
            await transport.finish_session(session_id)
            print("   Session finished")
        await transport.disconnect()
        print("   Disconnected from companion")

    print("\n" + "=" * 60)
    print("Windows E2E demo completed!")
    print("=" * 60)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.mode == "local":
        return asyncio.run(demo_local(args))
    elif args.mode == "remote":
        return asyncio.run(demo_remote(args))
    elif args.mode == "windows-e2e":
        return asyncio.run(demo_windows_e2e(args))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())