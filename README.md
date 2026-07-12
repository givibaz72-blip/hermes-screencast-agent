# Hermes Screencast Agent

AI-assisted browser screencast agent for Hermes.

It records polished website walkthroughs using Playwright, Xvfb, FFmpeg, cursor event logging, automatic zoom processing, and DemoScript execution.

## Status

MVP bootstrap.

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
  -> Playwright
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
