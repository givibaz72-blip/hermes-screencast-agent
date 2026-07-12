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
