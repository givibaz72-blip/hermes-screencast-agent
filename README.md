# Hermes Screencast Agent

AI-assisted browser screencast agent for Hermes.

It records polished website walkthroughs using Playwright, Xvfb, FFmpeg, cursor event logging, automatic zoom processing, and DemoScript execution.

## Status

MVP bootstrap.

## What Hermes can do now

Hermes can execute browser demo scenarios through DemoScript.

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

## Quick start: DemoScript CLI

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

Run the validated DemoScript in headless browser mode:

```bash
hermes-screencast demo-run /tmp/hermes_demo.json --headless --profile demo-cli
```

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
zoom
highlight
draw_box
draw_arrow
narration
auth_check
assert_text_visible
assert_element_visible
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
