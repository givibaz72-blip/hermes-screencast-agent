# Hermes Screencast Agent

AI-assisted browser screencast agent for Hermes.

It records polished website walkthroughs using Playwright, Xvfb, FFmpeg, cursor event logging, automatic zoom processing, and DemoScript execution.

## Status

Core screencast pipeline (DemoScript → plan → execute → record → post-process) is implemented and tested. The local desktop browser transport, raw CDP browser startup, remote relay transport, and Windows E2E workflows are all functional with 43 contract/integration tests covering the transport stack.

## What Hermes can do now

Hermes can generate DemoScript from a normal-language scenario and execute the
resulting browser demo.

A DemoScript is a structured scenario made of steps such as:

- open a URL
- wait
- show narration
- highlight an element
- draw a box around an element
- scroll
- click
- fill text

The current execution path is:

```text
DemoScript
  -> DemoDryRunPlanner
  -> DemoPlan

DemoScript
  -> DemoRunner
  -> DemoExecutor
  -> BrowserDemoExecutor
  -> BrowserRuntime
  -> BrowserSession
  -> LocalBrowserProcess
       -> RawChromeCdpProcess  [browser_startup="raw-cdp"]
       -> Playwright            [browser_startup="playwright" (default)]
```

Normal-language generation uses a separate provider-neutral path:

```text
Target page
  -> PageDiscoveryReport

ScenarioPlanningRequest
  + PageDiscoveryReport
  -> ScenarioProvider
  -> strict JSON parsing
  -> DemoScript validation
```

## Quick start: DemoScript CLI

Write a normal-language scenario:

```text
Open the product page, highlight the main heading, and explain the primary action.
```

Inspect the target page before asking a provider to plan selectors:

```bash
hermes-screencast demo-discover https://example.com \
  --headless \
  --profile product-discovery \
  --output /tmp/hermes_discovery.json
```

The discovery report contains visible interactive elements, bounding boxes,
accessible names, locator candidates, and duplicate role/name warnings. Locator
priority is unique test id, id, name attribute, safe href, role plus accessible
name, then short exact text. Input values are never collected. URL credentials,
fragments, and query values are not written to the report; links containing
query parameters are not offered as selectors. If the catalog is truncated,
Hermes conservatively withholds selectors until discovery is rerun with a high
enough `--max-elements` value.

Generate a validated DemoScript through a provider adapter:

```bash
hermes-screencast demo-generate scenario.txt \
  --target-url https://example.com \
  --title "Product overview" \
  --discovery /tmp/hermes_discovery.json \
  --provider-command /path/to/hermes-provider \
  --provider-arg=--model \
  --provider-arg=local-model \
  --output /tmp/hermes_demo.json
```

Hermes is provider-neutral. The provider command receives the complete planning
prompt through standard input and must write exactly one DemoScript JSON object
to standard output. Markdown fences and explanatory text are rejected. The
command is started directly without a shell. Configure provider credentials in
the adapter environment; never put API keys in scenario files or command-line
examples.

Optional generation inputs include repeated `--constraint` values and a
`--preferences` path containing a JSON object. User-supplied title and
preferences take precedence over provider defaults. A supplied target URL must
exactly match the first generated `goto` step. When `--discovery` is supplied,
the report must use the `hermes.discovery.v1` schema and the planning prompt
instructs the provider to use discovered selectors instead of inventing them.

Create a starter DemoScript JSON file:

```bash
hermes-screencast demo-init /tmp/hermes_demo.json
```

Validate the DemoScript JSON without launching a browser:

```bash
hermes-screencast demo-validate /tmp/hermes_demo.json
```

Print a deterministic dry-run plan without launching a browser:

```bash
hermes-screencast demo-plan /tmp/hermes_demo.json
```

Execute the validated DemoScript without recording:

```bash
hermes-screencast demo-run /tmp/hermes_demo.json --headless --profile demo-cli
```

Record the DemoScript as a professional 1080p MP4:

```bash
hermes-screencast demo-record /tmp/hermes_demo.json \
  --output /tmp/hermes_demo.mp4 \
  --events-output /tmp/hermes_demo.events.json \
  --profile demo-record
```

Every recording also writes a synchronized `hermes.recording.events.v1` JSON
sidecar. When `--events-output` is omitted, `demo.mp4` produces
`demo.events.json`. The journal starts after FFmpeg is ready and records
monotonic timestamps for step start, completion, or failure; target bounds;
viewport state; and final cursor position for visible interactions. Form values
and URL query values are never stored. Failed recordings retain their event log
for diagnosis.

Create a portable editing project from verified recording artifacts:

```bash
hermes-screencast project-init /tmp/product.hermes \
  --title "Product demo" \
  --video /tmp/hermes_demo.mp4 \
  --events /tmp/hermes_demo.events.json \
  --script /tmp/hermes_demo.json

hermes-screencast project-validate /tmp/product.hermes

hermes-screencast project-auto-zoom /tmp/product.hermes

hermes-screencast project-cursor-motion /tmp/product.hermes

hermes-screencast project-style /tmp/product.hermes --preset studio
```

`HermesProject` copies assets under the project directory and records relative
paths, sizes, and SHA-256 checksums in `project.json`. Validation rejects missing,
modified, absolute, or path-traversing assets. The initial composition manifest
contains stable canvas, background, frame, and timeline contracts for
non-destructive processing.

`project-auto-zoom` reads completed click events and target bounds from the
synchronized event log, then writes an editable `camera.zoom` track to
`project.json`. The source MP4 is never modified or re-encoded. Camera focus is
clamped to the video frame, large targets reduce the requested scale so they
remain visible, nearby clicks are merged, and overlapping clicks in distant
areas receive consecutive segments. Running the command again replaces only
the generated `auto-zoom` track.

The defaults use a 1.35x zoom with cubic easing. They can be tuned without
recording again:

```bash
hermes-screencast project-auto-zoom /tmp/product.hermes \
  --scale 1.45 \
  --lead 0.25 \
  --hold 0.8 \
  --transition 0.35 \
  --target-margin 80 \
  --merge-distance 120
```

`project-cursor-motion` turns the cursor positions captured for click, hover,
and fill actions into an editable `cursor.motion` track. Exact interaction
positions remain as anchors; movement between them uses clamped cubic Bézier
segments and finishes shortly before the interaction so the cursor visibly
settles on its target. The generated track coexists with `auto-zoom`, does not
change the MP4, and is replaced idempotently when regenerated.

```bash
hermes-screencast project-cursor-motion /tmp/product.hermes \
  --speed 1400 \
  --min-duration 0.12 \
  --max-duration 0.75 \
  --settle 0.06 \
  --tension 0.6
```

`project-style` applies a complete, validated composition preset without
touching the source recording or timeline. Available presets are `source`,
`studio`, `clean`, `social-square` (1:1), `social-vertical` (9:16), and
`cinematic` (64:27). Each preset defines the canvas, background, padding,
corner radius, and structured drop shadow that a renderer can reproduce.

Individual values can be overridden while keeping the manifest valid:

```bash
hermes-screencast project-style /tmp/product.hermes \
  --preset social-vertical \
  --background-color '#123456' \
  --padding 80 \
  --corner-radius 20 \
  --no-shadow
```

Custom `--canvas-width` and `--canvas-height` values automatically update the
stored aspect ratio. Reapplying a style replaces only the composition object;
camera and cursor tracks remain unchanged.

Add editable overlays in canvas coordinates and project time:

```bash
hermes-screencast project-annotate /tmp/product.hermes \
  --kind text --id intro-title \
  --start 0.5 --end 3.0 \
  --x 120 --y 80 \
  --text 'Create a polished demo'

hermes-screencast project-annotate /tmp/product.hermes \
  --kind arrow \
  --start 3.0 --end 5.0 \
  --x 300 --y 240 --to-x 720 --to-y 480
```

Supported kinds are `text`, `box`, `highlight`, and `arrow`. Every annotation
has a stable ID, start/end time, type-specific geometry, and validated style.
They are stored in the `annotation.overlay` timeline track and never burned
into the source MP4.

```bash
hermes-screencast project-annotation-list /tmp/product.hermes
hermes-screencast project-annotation-remove /tmp/product.hermes intro-title
```

Generate a non-destructive automatic time edit from synchronized events:

```bash
hermes-screencast project-auto-edit /tmp/product.hermes \
  --preserve-threshold 1.25 \
  --cut-threshold 4.0 \
  --speed 4.0 \
  --context 0.25
```

Short pauses remain untouched. Medium idle gaps and explicit `wait` steps get
`speed` segments, while long gaps receive `cut` segments. Context is preserved
on both sides so actions are not clipped. The `time.edit` track retains source
timestamps and reports source, estimated, and removed duration; it never edits
or re-encodes the MP4 itself.

Generate a self-contained read-only project preview:

```bash
hermes-screencast project-preview /tmp/product.hermes \
  --output /tmp/product-preview.html
```

The HTML file requires no server or external assets. It displays the selected
composition, source and estimated durations, a scrubber, and synchronized rows
for camera, cursor, annotations, and time edits. The embedded preview data is
escaped before insertion and does not include recording-event payloads or asset
contents.

Render the first production MP4 export stage:

```bash
hermes-screencast project-render /tmp/product.hermes \
  --output /tmp/product-final.mp4
```

This renderer applies smooth `cursor.motion` Bézier paths and `camera.zoom`
segments in source time, followed by `time.edit` cuts/speed changes and the full
composition contract: canvas, solid or two-color gradient background,
contain/cover fit, padding, rounded corners, and shadow. Editable text, rounded
boxes, highlights, and vector arrows are then rendered in canvas coordinates
and project time. Cursor and zoom use
cubic easing around recorded interaction geometry and remain synchronized when
later edits remove or accelerate source-time ranges. The renderer exports
H.264/yuv420p with fast-start metadata and verifies the MP4.

Completed click anchors receive a short expanding, fading vector ring beneath
the cursor. The feedback is rendered before camera zoom, so it remains locked
to the clicked target through zoom and time edits.

Use `--dry-run` to inspect the exact FFmpeg plan. When the source contains an
audio stream, the renderer applies the same trim, cut, and speed timeline to
audio and video, then exports synchronized AAC audio. Silent sources remain
silent without requiring a separate option.

Rendering uses `--encoder auto` by default. Hermes benchmarks libx264, NVENC,
Quick Sync, and AMD AMF with a short real encode, selects hardware only when it
beats software by a useful margin, and caches the result for the process. Use
`--encoder software` for deterministic CPU-only output or select a specific
backend explicitly.

Optional `--fade-in` and `--fade-out` durations add synchronized video and
audio fades after timeline edits, expressed in seconds.

Use `--normalize-audio` to target -16 LUFS integrated loudness, 11 LU loudness
range, and -1.5 dB true peak before final audio fades.

Choose `--quality draft`, `balanced`, `high`, or `archive` to trade encoding
speed and output size for visual fidelity. `high` preserves the prior default.

Run the complete recommended workflow with one command:

```bash
hermes-screencast project-polish /tmp/product.hermes \
  --output /tmp/product-final.mp4
```

`project-polish` applies studio framing, regenerates auto zoom, cursor motion,
and time edits, writes a sibling `.preview.html`, then renders high-quality MP4
with short synchronized fades, automatic encoder selection, and normalized
audio when present. All generated tracks remain editable in HermesProject.
Use `--preset keep` to preserve an existing custom composition.

Produce the complete screencast directly from a
normal-language scenario:

```bash
hermes-screencast demo-produce scenario.txt \
  --target-url https://example.com \
  --title "Product overview" \
  --provider-command /path/to/hermes-provider \
  --provider-arg=--model \
  --provider-arg=local-model \
  --output /tmp/product-final.mp4
```

`demo-produce` performs page discovery, generates and validates
DemoScript, records the browser, creates HermesProject, applies the
complete polish workflow, and writes the final MP4 and HTML preview.

Intermediate artifacts are preserved in a sibling work directory such
as `product-final.work/`. It contains the discovery report, generated
DemoScript, source recording, synchronized events, editable
HermesProject, and `result.json`.

Existing workspaces, final videos, and previews are never overwritten.
Use `--work-directory` to select another workspace.

The editor foundation exposes `read_editor_project` and `save_editor_project`
for validated composition/timeline editing. Snapshots carry a SHA-256 ETag;
stale saves are rejected and accepted edits replace `project.json` atomically
without allowing the editor to mutate asset references.

Start the first local timeline editor with:

```bash
hermes-screencast project-editor /tmp/product.hermes
```

The server binds to `127.0.0.1` only. Its initial UI visualizes all timeline
tracks, previews the composition background, and saves background edits through
the validated ETag API. It never exposes source video or event-log assets.
Frame controls provide live preview editing for fit, padding, corner radius,
and the complete shadow style.
Timeline segments can be selected to edit validated start/end times before
saving the project.
Camera zoom segments additionally expose scale and focus X/Y controls.
Cursor motion segments expose both endpoints and Bézier control points while
keeping interaction anchors synchronized with edited paths.
Annotation segments expose text, color, opacity, and kind-specific geometry;
overlapping segments are stacked so every edit remains selectable.

Record the maintained public example:

```bash
hermes-screencast demo-record templates/public.json \
  --output /tmp/hermes_public_demo.mp4 \
  --profile public-demo
```

The first DemoScript step must be `goto`. Hermes opens the page before FFmpeg starts and stops recording before Chromium closes, reducing black frames at the beginning and end.

Run the built-in smoke DemoScript:

```bash
hermes-screencast demo-smoke --headless --profile demo-smoke
```

## DemoScript JSON format

Example:

```json
{
  "title": "Hermes demo",
  "target": {
    "kind": "web",
    "url": "https://example.com"
  },
  "preferences": {
    "resolution": "1080p",
    "cursor_speed": "natural",
    "highlight_style": "subtle",
    "marker_colors": ["yellow", "blue"],
    "pacing": "professional"
  },
  "metadata": {
    "schema": "hermes.demo.v1"
  },
  "steps": [
    {
      "action": "goto",
      "url": "https://example.com"
    },
    {
      "action": "wait",
      "seconds": 1
    },
    {
      "action": "narration",
      "text": "Hermes is executing a DemoScript from JSON"
    },
    {
      "action": "highlight",
      "selector": "h1"
    },
    {
      "action": "draw_box",
      "selector": "h1"
    },
    {
      "action": "wait",
      "seconds": 1
    }
  ]
}
```

Top-level DemoScript fields:

- `title`: required string
- `target`: optional object describing the application, site, document, or tool
- `preferences`: optional object describing cursor speed, marker colors, resolution, and pacing
- `metadata`: optional object for schema and run metadata
- `steps`: required list of executable demo steps

Supported action types currently include:

```text
goto
click
hover
fill
scroll
wait
wait_for_element
wait_for_not_element_visible
wait_for_url_contains
wait_for_text_visible
wait_for_not_text_visible
wait_for_navigation_idle
zoom
highlight
draw_box
draw_arrow
narration
auth_check
assert_text_visible
assert_not_text_visible
assert_element_visible
assert_not_element_visible
assert_url_contains
```

## Legacy screencast commands

Create a basic task JSON:

```bash
hermes-screencast plan --url https://example.com --output /tmp/task.json
```

Record from an existing task JSON:

```bash
hermes-screencast record /tmp/task.json
```

Create a basic task JSON and record it:

```bash
hermes-screencast run --url https://example.com
```

## Goals

- Record website and SaaS walkthroughs.
- Use saved browser sessions.
- Support assisted login for CAPTCHA/2FA.
- Execute structured DemoScript scenarios.
- Apply automatic cursor-centered zoom.
- Verify final MP4 output.
- Integrate with Hermes as a user-local skill.

## Safety

This project does not bypass CAPTCHA, Cloudflare, 2FA, SMS codes, email codes, or passkeys automatically.

## FFmpeg filter capabilities

Hermes inspects the installed FFmpeg build before rendering. When `drawvg`
is available, vector annotations and cursor click rings use the native vector
backend. Standard FFmpeg builds without `drawvg` automatically use a portable
fallback based on `drawbox`, `geq`, and `overlay`.

The portable backend preserves boxes, highlights, arrows, cursor click rings,
and timed text. Rounded vector corners and antialiasing may differ slightly
from the native `drawvg` backend, but effects are never removed silently.

## Assisted login for authenticated applications

The `browser-login` command assists with logging into websites that require authentication, using a persistent browser profile and a secure, loop‑only handoff mechanism.

### Usage

```bash
python -m hermes_screencast.runner browser-login \
  https://app.example.com/ \
  --profile my-app-profile
```

This will:

1. Launch a Chromium instance with the given profile (created if missing) on a virtual display (`:99` by default).
2. Print a handoff URL (e.g. `http://127.0.0.1:<port>/vnc.html?path=websockify%3Ftoken%3D...&autoconnect=1&resize=scale`).
3. Open that URL in a Hermes Desktop embedded view (when available) or any VNC/noVNC client so the user can complete the login manually.
4. After login succeeds (detected via URL change or success selector), the browser is closed, the profile (with cookies/localStorage) is saved, and a JSON result is returned.

### Example workflow with demo‑produce

```bash
# 1. Assist login (once per profile)
python -m hermes_screencast.runner browser-login \
  https://app.heygen.com/ \
  --profile heygen-review

# 2. Later, produce a demo using the same authenticated profile
# Note: The DemoScript target must declare requires_auth=true and provide
# success criteria (success_url_prefix or success_selector).
# A dashboard selector is required because HeyGen may use the same URL for
# login shell and dashboard.
python -m hermes_screencast.runner demo-produce \
  scenario.txt \
  --target-url https://app.heygen.com/ \
  --provider-command ./my-provider \
  --provider-arg=--model \
  --provider-arg=local-model \
  --output /tmp/product-final.mp4
```

## DemoScript Preflight & Authentication Safety

Before starting a recording that requires authentication, Hermes runs a preflight check against the target URL to detect auth provider blocks.

### Preflight rejection conditions

The preflight navigates to the target URL in headless mode and rejects if any of the following are detected:

- Hostname is `auth.heygen.com` (or similar Google OAuth endpoints)
- Page title contains "Login" or "Sign in"
- Visible OAuth buttons (Google, Apple, email, SSO)
- Google unsafe browser warning detected
- Cloudflare challenge failure detected

### On preflight failure

- No recorder is started
- No MP4 is created
- Structured result is returned with `auth_provider_blocked` status
- Exit code is non-zero

This prevents wasted recordings on pages where the server-side Chromium cannot proceed due to provider-side blocks.

## Browser login & persistent authentication

The `browser-login` command handles authenticated sites by launching a persistent Chromium profile on a virtual display (`:99`) and providing a loopback-only VNC/noVNC handoff URL for the user to complete login manually.

### How it works

1. **Profile persistence**: Browser profiles are created under a user-writable directory (e.g., `~/.hermes/profiles/heygen-review`). Cookies, localStorage, and sessionStorage persist across sessions.
2. **Loopback handoff**: A temporary VNC/noVNC server is started on `127.0.0.1`. The handoff URL contains a cryptographically secure token and is printed to stdout.
3. **User completes login**: The user opens the handoff URL in a browser or VNC client, completes any login flow (Google OAuth, 2FA, CAPTCHA, etc.) manually.
4. **Detection**: Hermes detects login completion via URL change or success selector visibility.
5. **Profile save**: Browser closes, profile (with cookies, localStorage) is saved for future runs.
5. **Result**: JSON result includes `profile_path`, `authenticated: true`, and any security warnings.

### Example: HeyGen authenticated demo

```bash
# 1. Initial login (once per profile)
python -m hermes_screencast.runner browser-login \
  https://app.heygen.com/ \
  --profile heygen-review

# Output includes handoff URL like:
# http://127.0.0.1:5901/vnc.html?path=websockify%3Ftoken%3Dabc123&autoconnect=1&resize=scale

# 2. Later demo-produce using authenticated profile
# Requires DemoScript with requires_auth=true and success criteria
python -m hermes_screencast.runner demo-produce \
  scenario.txt \
  --target-url https://app.heygen.com/ \
  --provider-command ./my-provider \
  --provider-arg=--model \
  --provider-arg=local-model \
  --output /tmp/product-final.mp4
```

**Security notes:**
- Handoff server binds to `127.0.0.1` only; no external exposure.
- Handoff URL contains ephemeral token (printed to stdout).
- Cookies/localStorage persist in profile; never exported.
- On `auth_provider_blocked` (Google unsafe browser, Cloudflare), recording does not start and no MP4 is created.

### Limitations

- The `browser-login` command does not automate form filling; it relies on the user to complete the login via the VNC/web UI.
- Binding the handoff server to `0.0.0.0` is prohibited and will be rejected.
- **Google OAuth, Cloudflare, and CAPTCHA may block server‑side automated Chromium.** Hermes does not attempt to bypass these protections.
- **Manual user confirmation is not proof of successful authentication.** The page state is verified after handoff; recording only proceeds if the session is authenticated.
- Server handoff and native Hermes Desktop browser transport are separate capabilities. The handoff provides loopback VNC access; native Desktop transport is not yet implemented.
- When `auth_provider_blocked` is detected (e.g., Google unsafe browser, Cloudflare challenge), recording does not start and no MP4 is created.
- **HeyGen dashboard selector not yet confirmed on real Windows** — selector `[data-testid='dashboard']` is a placeholder.

### Status

Backend handoff and persistent authentication are verified. Hermes Desktop transport remains unavailable until an embedded view or trusted loopback proxy is implemented. Remote Windows Transport is experimental and requires Windows E2E verification.

## Local Desktop Browser Transport — Local & Remote Modes

Hermes supports three transport topologies for running the browser on the user's desktop rather than the server:

| Mode | Use case | Connection |
|------|----------|------------|
| **LOCAL_DEVELOPMENT** | Same-machine development | Companion listens on 127.0.0.1, backend connects |
| **REMOTE_DESKTOP** | Windows desktop on separate machine | Companion initiates outbound TLS WebSocket to relay |
| **WINDOWS_LOCAL_E2E** | **First real SaaS screencast** — Windows only, no relay, no domain, no public WSS | Companion on 127.0.0.1, backend connects locally, real Chrome, manual login |

---

## First Real SaaS Screencast — Windows Local E2E (Recommended)

**This is the primary path for recording authenticated SaaS walkthroughs like HeyGen.**

### Why Windows Local E2E?

| Requirement | Windows Local E2E |
|-------------|-------------------|
| Domain / DNS | ❌ Not needed |
| Public WSS / relay | ❌ Not needed |
| Reverse proxy (Caddy/Nginx) | ❌ Not needed |
| Ubuntu server | ❌ Not needed |
| TLS certificates | ❌ Not needed |
| Pairing codes | ❌ Not needed |
| User manual steps | ✅ Login / CAPTCHA / 2FA only |
| Recording starts | ✅ Only after confirmed dashboard auth |
| Chrome profile | ✅ Persists locally (`%LOCALAPPDATA%\Hermes\Profiles\...`) |
| Recording output | ✅ Local MP4 (`%USERPROFILE%\Videos\Hermes\...`) |
| Transport | ✅ Localhost-only WebSocket (127.0.0.1) |

**Remote Windows Transport remains available as a separate experimental capability for multi-machine scenarios.**

### Prerequisites (Windows only)

- Windows 10/11 with Google Chrome installed
- Python 3.11+ (from `python.org` or Microsoft Store)
- ffmpeg + ffprobe in PATH (`winget install Gyan.FFmpeg`)
- Playwright Chromium (`playwright install chromium`)

### Quick Start

```powershell
# 1. Clone and setup
git clone https://github.com/yourorg/hermes-screencast-agent
cd hermes-screencast-agent

# 2. Create venv and install
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Install Playwright Chromium (for local browser)
playwright install chromium

# 4. Verify ffmpeg
ffmpeg -version
ffprobe -version
```

### Local Companion CLI (Canonical Entry Point)

The companion is available as a canonical Python package CLI:

```bash
python -m hermes_screencast.local_companion.cli \
  --host 127.0.0.1 \
  --port 0 \
  --chrome-path "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
```

**Startup contract:**
- Binds to **127.0.0.1 only** (enforced — `0.0.0.0` is rejected)
- Prints `COMPANION_PORT:<port>` exactly once (with `flush=True`) after successful `asyncio.start_server`
- Chrome is **NOT** launched at startup — it starts only after `START_SESSION` command
- Runs until Ctrl+C or termination
- Owned processes (Chrome, FFmpeg) are cleaned up on exit

**Compatibility:**
- PowerShell 7 is **not required** for this workflow
- Windows PowerShell 5.1 is fully supported
- No domain, relay, or pairing code needed for local mode

### Raw CDP Browser Startup

By default the local companion uses Playwright to launch Chrome. An alternative **raw CDP** mode dispatches Chrome via `subprocess.Popen` and connects through the raw Chrome DevTools Protocol endpoint, bypassing Playwright's browser lifecycle.

```bash
# Start companion with raw CDP browser startup (Playwright omitted)
python -m hermes_screencast.local_companion.cli \
  --host 127.0.0.1 \
  --port 0 \
  --chrome-path "/usr/bin/chromium-browser" \
  --browser-startup raw-cdp

# Or with the demo script
python scripts/demo_local_transport.py local \
  --chrome-path "/usr/bin/chromium-browser" \
  --browser-startup raw-cdp
```

**How it works:**
1. Companion launches Chrome with `--remote-debugging-port=<port>` and `--user-data-dir=<profile_dir>` via `subprocess.Popen(shell=False)`.
2. Chrome writes `DevToolsActivePort` to the profile directory.
3. Companion polls for `DevToolsActivePort`, reads the actual debugging port, then connects Playwright's `connect_over_cdp()` to reuse the externally-managed browser.
4. On close, the companion kills the tracked PID (no `pkill`).

**START_SESSION protocol contract:** The `SessionConfig` message now includes two fields specific to this mode:

| Field | Type | Description |
|-------|------|-------------|
| `browser_startup` | string | `"playwright"` (default) or `"raw-cdp"` |
| `auth_wait_seconds` | int | Maximum seconds to wait for login during handoff (default 300) |

**When to use raw CDP:**
- You want direct control over Chrome launch arguments
- Playwright's browser detection is unreliable on your platform
- You need the browser to survive Playwright upgrades
- Smoke-testing Chrome startup without Playwright in the loop

**Verification:**
```bash
# Dry run — validates args, parses parser, does not launch Chrome
python scripts/demo_raw_chrome_cdp.py --dry-run

# Full test: launches Chrome via raw CDP, connects Playwright, verifies, closes
python scripts/demo_raw_chrome_cdp.py

# Windows smoke-test script (PowerShell)
powershell -File scripts/test_raw_chrome_cdp_windows.ps1 -DryRun
```

### Inspect-Only Mode (Selector Discovery)

Run this first to manually log in and discover the authenticated dashboard selector:

```powershell
.\scripts\run_heygen_windows_e2e.ps1 -InspectOnly
```

**What happens:**
1. Opens your **local installed Chrome** (headful, persistent profile)
2. Navigates to `https://app.heygen.com/`
3. **You manually complete** login / CAPTCHA / 2FA
4. Hermes periodically polls SafePageState (URL, hostname, title, visible markers, auth classification)
4. **Never outputs** cookies, storage, form values, or passwords
5. When you confirm the dashboard is loaded, press Enter in the terminal
6. Use `--success-selector "<CSS>"` to probe a candidate selector
7. Result: `authenticated_selector_confirmed` only if selector exists, is visible, in authenticated UI (not login page), no provider blocks

**Default paths:**
- Profile: `$env:LOCALAPPDATA\Hermes\Profiles\heygen-review`
- Recording: `$env:USERPROFILE\Videos\Hermes`
- Output: `heygen-review-demo.mp4`

### Selector Probe (Inspect-Only with Selector)

```powershell
.\scripts\run_heygen_windows_e2e.ps1 -InspectOnly `
  -SuccessSelector "[data-testid='dashboard']"
```

**Probe checks:**
- ✅ Selector exists in DOM
- ✅ Selector is visible
- ✅ Page is authenticated (not `auth.heygen.com`, no login/sign-in markers)
- ✅ No Google unsafe-browser warning
- ✅ No Cloudflare challenge
- ✅ Result: `authenticated_selector_confirmed` (only on ALL passes)

**No default selector provided — you must confirm on real Windows.**

### Record Mode

```powershell
.\scripts\run_heygen_windows_e2e.ps1 `
  -Record `
  -SuccessSelector "[data-testid='dashboard']" `
  -RecordSeconds 10 `
  -OutputName "heygen-review-demo.mp4"
```

**What happens:**
1. Opens local Chrome with persisted profile (cookies from inspect step)
2. Navigates to `https://app.heygen.com/`
3. **Re-validates authenticated state** (fresh SafePageState + selector check)
4. If authenticated: starts FFmpeg (gdigrab on Windows) → MP4 in recording-dir
5. Shows recording indicator on screen
6. Records for `--record-seconds`
7. Runs `ffprobe` on output
8. Outputs: `artifact_name`, `size_bytes`, `duration`, `video_codec`, `width`, `height`
9. **Absolute path shown locally only** — never sent through remote API

**Failure conditions (non-zero exit, no MP4):**
- Selector not found / not visible
- Not authenticated (login page, auth.heygen.com, provider block)
- Profile dir / recording dir not writable
- FFmpeg / ffprobe not found
- Chrome not found (`chrome_not_found` error)

### Dry Run

```powershell
.\scripts\run_heygen_windows_e2e.ps1 -InspectOnly -DryRun
```

Shows what would execute without launching Chrome, companion, or FFmpeg.

### Debug Mode

```powershell
.\scripts\run_heygen_windows_e2e.ps1 -InspectOnly -HermesDebug
```

Enables verbose debug output from the Python CLI (`--debug`).

### Safe External Invocation (Recommended)

Use `try`/`catch` to detect launcher failures — do not rely on `$LASTEXITCODE` alone:

```powershell
# Dry-run verification
try {
    & .\scripts\run_heygen_windows_e2e.ps1 -InspectOnly -DryRun
    Write-Host "windows_e2e_dry_run=completed"
}
catch {
    Write-Host "windows_e2e_dry_run=failed"
    throw
}

# Real inspect-only run
try {
    & .\scripts\run_heygen_windows_e2e.ps1 -InspectOnly
    Write-Host "windows_e2e_launcher=completed"
}
catch {
    Write-Host "windows_e2e_launcher=failed"
    throw
}
```

**Note:** Do not use `Write-Error` inside the `catch` block when `$ErrorActionPreference = "Stop"` — it generates a new terminating exception that prevents subsequent lines from executing. Use `Write-Host` for status reporting, then `throw` to re-raise the original error.

---

## Using `demo_local_transport.py windows-e2e` Directly

You can also run the Windows E2E workflow directly via the Python script:

```bash
# Inspect-only mode (selector discovery)
python scripts/demo_local_transport.py windows-e2e \
  --profile-dir "$env:LOCALAPPDATA\Hermes\Profiles\heygen-review" \
  --recording-dir "$env:USERPROFILE\Videos\Hermes" \
  --target-url "https://app.heygen.com/" \
  --inspect-only

# Inspect with selector probe
python scripts/demo_local_transport.py windows-e2e \
  --profile-dir "$env:LOCALAPPDATA\Hermes\Profiles\heygen-review" \
  --recording-dir "$env:USERPROFILE\Videos\Hermes" \
  --target-url "https://app.heygen.com/" \
  --inspect-only \
  --success-selector "[data-testid='dashboard']"

# Record mode
python scripts/demo_local_transport.py windows-e2e \
  --profile-dir "$env:LOCALAPPDATA\Hermes\Profiles\heygen-review" \
  --recording-dir "$env:USERPROFILE\Videos\Hermes" \
  --target-url "https://app.heygen.com/" \
  --success-selector "[data-testid='dashboard']" \
  --record \
  --record-seconds 10 \
  --output-name "heygen-review-demo.mp4"

# Dry run
python scripts/demo_local_transport.py windows-e2e \
  --profile-dir "$env:LOCALAPPDATA\Hermes\Profiles\heygen-review" \
  --recording-dir "$env:USERPROFILE\Videos\Hermes" \
  --inspect-only \
  --dry-run
```

---

### Security & Cleanup

- Companion binds **only 127.0.0.1** (enforced in code)
- No relay, no TLS, no pairing codes
- Owned processes (Chrome, companion, FFmpeg) cleaned up on success, error, or Ctrl+C
- No `pkill` / `killall` — tracked PIDs only
- Profile directory stays local; cookies never exported
- SafePageState never contains secrets
- Safe filename validation on `output_name` (same rules as companion)
- MP4 written strictly inside `recording-dir` (path traversal prevented)

## Remote Windows Transport — Experimental

### Security & isolation

- Companion binds to **127.0.0.1 only** (enforced in code).
- Pairing codes: `secrets.token_urlsafe(24)`, TTL 5 min, single-use, fingerprint-only logging.
- Capability tokens: scoped to session, never logged, invalidated on `finish_session`/disconnect.
- **SafePageState** API returns only: URL, hostname, title, visible markers, viewport, auth status. **No cookies, localStorage, sessionStorage, or passwords.**
- TLS WebSocket with cert verification for remote mode.
- No external Chrome remote debugging port exposed.
- Windows companion initiates single outbound TLS WebSocket to relay; no inbound listeners except optional 127.0.0.1 for local mode.

### Comparison

| Feature | Server Handoff | Local Desktop Transport |
|---------|---------------|------------------------|
| Browser runs on | Server (Xvfb) | User's desktop |
| Google OAuth | Blocked (unsafe browser) | Requires real Windows E2E verification |
| Cloudflare | Blocked | Requires real Windows E2E verification |
| CAPTCHA | Blocked | Works (human) |
| Secrets (cookies) | Stored in server profile | Never leave local machine |
| Recording | Server-side ffmpeg | Local ffmpeg |
| Multi-user | Complex | Native (each user runs companion) |
| Status | Implemented | Implemented |

### Status

**LOCAL DESKTOP BROWSER TRANSPORT NOT READY: Requires real Windows E2E verification**

The implementation includes:
- ✅ Local companion with loopback-only binding
- ✅ Cryptographic pairing tokens with TTL and single-use
- ✅ Persistent local Chrome profile (never exported)
- ✅ Safe page state API (no secrets)
- ✅ Local screen recording with recording indicator
- ✅ Backend transport with async API
- ✅ Comprehensive unit tests (28 tests)
- ✅ Full pytest pass (390+ tests)

⚠️ **Known limitations awaiting Windows E2E:**
- Google OAuth unsafe browser detection needs real Windows Chrome verification
- Cloudflare challenge handling needs real Windows Chrome verification
- Local recording (gdigrab on Windows) needs real Windows verification
- Companion auto-discovery on Windows needs verification

The server-side Chromium approach has confirmed failures for Google OAuth (unsafe browser) and Cloudflare challenges. The local desktop transport architecture is implemented but requires actual Windows E2E testing to confirm Google OAuth and Cloudflare work with real user Chrome.

## Remote Windows Transport — Experimental

The Remote Windows Transport extends the Local Desktop Transport for scenarios where the Windows desktop is on a different machine than the Hermes backend. The Windows companion initiates an **outbound TLS WebSocket** connection to a relay server; no inbound ports are opened on the Windows machine.

### Architecture

```
┌──────────────────┐     TLS WebSocket (outbound)      ┌──────────────────┐
│  Windows Desktop │ ──────────────────────────────────► │  Relay Server    │
│                  │     Companion registers with        │  (Linux/Ubuntu)  │
│  • Companion     │     one-time pairing code           │                  │
│  • Chrome        │     then streams commands/          │  • Backend       │
│  • ffmpeg        │     responses over single WS        │  • Pairing admin │
└──────────────────┘                                     └──────────────────┘
        ▲                                                     ▲
        │ Local recording (gdigrab)                    Unix admin socket
        │ MP4 stays on Windows                         (create-pairing, doctor)
        └────────────────────────────────────────────────────┘
```

### Prerequisites

**Ubuntu (Relay + Backend):**
- OpenSSL certificates for TLS (or use reverse proxy like Caddy/Nginx for TLS termination)
- Python 3.11+ with dependencies (`pip install -r requirements.txt`)
- Relay admin socket directory: `/run/hermes-relay/` (mode 0700)
- Disk space for pairing state (minimal)

**Windows (Companion):**
- Windows 10/11 with Chrome installed
- Python 3.11+ with dependencies (`pip install -r requirements.txt`)
- Playwright Chromium (`playwright install chromium`)
- ffmpeg in PATH (`winget install Gyan.FFmpeg` or equivalent)
- Local profile directory (e.g., `C:\Users\<USER>\AppData\Local\Hermes\Profiles\<profile>`)

### Ubuntu Setup & Runbook

```bash
# 1. Prepare directories with safe permissions
sudo mkdir -p /run/hermes-relay /var/lib/hermes-relay
sudo chmod 700 /run/hermes-relay /var/lib/hermes-relay

# 2. Prepare TLS certificates (example with self-signed for testing)
# Production: use real certs from Let's Encrypt / your CA
openssl req -x509 -newkey rsa:2048 -nodes -keyout /etc/hermes/relay.key \
  -out /etc/hermes/relay.crt -days 365 -subj "/CN=relay.example.com"

# 3. Start relay server
python -m hermes_screencast.transport.relay_server \
  --host 127.0.0.1 \
  --port 8765 \
  --ssl-cert /etc/hermes/relay.crt \
  --ssl-key /etc/hermes/relay.key \
  --admin-socket /run/hermes-relay/admin.sock \
  --pairing-ttl 300 \
  --session-ttl 3600

# 4. Verify relay health via doctor
python -m hermes_screencast.transport.relay_server doctor \
  --admin-socket /run/hermes-relay/admin.sock \
  --ssl-cert /etc/hermes/relay.crt \
  --ssl-key /etc/hermes/relay.key \
  --expected-hostname relay.example.com

# 5. Create a one-time pairing code
python -m hermes_screencast.transport.relay_server create-pairing \
  --admin-socket /run/hermes-relay/admin.sock \
  --ttl 300 \
  --output /run/hermes-relay/pairing-code

# 6. Start backend remote demo (reads pairing code from file, no echo)
python scripts/demo_local_transport.py remote \
  --relay-url wss://relay.example.com:8765/desktop-relay \
  --pairing-code-file /run/hermes-relay/pairing-code \
  --profile heygen-review

# 7. Wait for Windows companion to connect and pair
# The demo will pair, start session, open HeyGen URL, wait for auth confirmation,
# then record upon user confirmation.
```

### Windows PowerShell Runbook

```powershell
# 1. Checkout or install package
git clone https://github.com/yourorg/hermes-screencast-agent
cd hermes-screencast-agent

# 2. Create venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright Chromium (required for real Windows E2E)
playwright install chromium

# 5. Verify ffmpeg is in PATH
ffmpeg -version

# 6. Save pairing code from Ubuntu step 5 to local file
#    (transfer securely, e.g., scp, USB, password manager)
$pairingCode = Get-Content C:\Hermes\pairing-code.txt -Raw

# 7. Launch remote companion (outbound TLS WebSocket to relay)
python scripts/launch_companion_windows.py remote `
  --relay-url wss://relay.example.com:8765/desktop-relay `
  --pairing-code $pairingCode `
  --profile-dir $env:LOCALAPPDATA\Hermes\Profiles\heygen-review `
  --recording-dir $env:USERPROFILE\Videos\Hermes `
  --companion-id WIN-HEYGEN-01

# 8. User completes Google OAuth in local Chrome window
#    (handles unsafe browser warning, Cloudflare challenge manually)

# 9. After dashboard loads, press Enter in Ubuntu demo to confirm auth
# 10. Recording starts, MP4 written to local Windows recording directory

# 11. Local profile persists at:
#     C:\Users\<USER>\AppData\Local\Hermes\Profiles\heygen-review\
#     Contains cookies for subsequent runs (no re-login needed)
#     MP4 location: C:\Users\<USER>\Videos\Hermes\heygen-review_demo.mp4
```

### Security Notes

- **Pairing code**: Shown **exactly once** to operator via `create-pairing --output`. Never logged by relay or companion.
- **Capability token**: Scoped to session, invalidated on `finish_session` or disconnect. Fingerprint only (first 12 chars) shown in logs.
- **Admin socket**: Unix domain socket (`/run/hermes-relay/admin.sock`), mode 0600. Never exposed over TCP.
- **TLS required** for non-loopback relay URLs. `ws://` only allowed for `127.0.0.1` with explicit `--allow-insecure-local-test`.
- **Windows profile**: Stays on Windows (`%LOCALAPPDATA%\Hermes\Profiles\<name>\`). Never uploaded.
- **MP4**: Written locally on Windows in `--recording-dir`, not streamed through relay.
- **Windows ACL pairing file**: Pairing code file should be protected with Windows ACL (e.g., only owner read/write). Full ACL validation is a future enhancement.

### Limitations

- **No HeyGen dashboard selector confirmed yet** — selector `[data-testid='dashboard']` is a placeholder; real Windows E2E needed to confirm.
- **Google OAuth / Cloudflare** handled by real Windows Chrome — no anti-bot bypass attempted.
- **Recording is local** (gdigrab on Windows). MP4 never leaves Windows unless explicitly copied.
- **Relay is experimental** — production deployment should use Caddy/Nginx TLS reverse proxy in front of `127.0.0.1:8765`.

---

## Security and cleanup

- **Loop‑only binding:** All local companions bind to `127.0.0.1` only; relay binds to `127.0.0.1` by default.
- **Ephemeral tokens:** Pairing codes expire (default 5 min), single-use. Capability tokens session-scoped, revoked on disconnect.
- **Token handling:** Pairing codes never logged; capability token fingerprints only.
- **No secret leakage:** Passwords, cookies, localStorage, sessionStorage never appear in logs, artifacts, or relay messages.
- **Lifecycle cleanup:** All owned processes (Xvfb, Chromium, x11vnc, websockify, ffmpeg) terminated on completion or interruption.
- **Persistent profiles:** Browser profiles retained locally for seamless re-authentication.

### Limitations

- The `browser-login` command does not automate form filling; it relies on the user to complete the login via the VNC/web UI.
- Binding the handoff server to `0.0.0.0` is prohibited and will be rejected.
- **Google OAuth, Cloudflare, and CAPTCHA may block server‑side automated Chromium.** Hermes does not attempt to bypass these protections.
- **Manual user confirmation is not proof of successful authentication.** The page state is verified after handoff; recording only proceeds if the session is authenticated.
- Server handoff and native Hermes Desktop browser transport are separate capabilities. The handoff provides loopback VNC access; native Desktop transport is not yet implemented.
- When `auth_provider_blocked` is detected (e.g., Google unsafe browser, Cloudflare challenge), recording does not start and no MP4 is created.
- **HeyGen dashboard selector not yet confirmed on real Windows** — selector `[data-testid='dashboard']` is a placeholder.

### Status

Backend handoff and persistent authentication are verified. Hermes Desktop transport remains unavailable until an embedded view or trusted loopback proxy is implemented. Remote Windows Transport is experimental and requires Windows E2E verification.