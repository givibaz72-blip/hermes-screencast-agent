---
name: website-screencast
description: Use when the user asks to record a website screencast, browser walkthrough, SaaS demo, product demo, onboarding video, authenticated web app demo, or professional MP4 recording.
version: 1.5.0
author: Hermes User
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [screencast, browser, playwright, ffmpeg, video, demo, saas]
    related_skills: [computer-use, systematic-debugging]
---

# Website Screencast

## Overview

Use this skill to create professional browser screencasts from user scenarios.

Hermes converts a scenario into a structured DemoScript, executes it in Chromium, displays a smooth visual cursor, renders annotations, records the screen with FFmpeg, and verifies the resulting MP4.

The current output is a clean video recording intended for later editing, narration, music, and final assembly in tools such as CapCut.

## When to Use

Use this skill when the user asks to record:

- a website or SaaS walkthrough
- a product feature demonstration
- an onboarding process
- a browser workflow
- an authenticated dashboard
- a clean MP4 for later video editing

Do not use this skill to bypass CAPTCHA, Cloudflare challenges, 2FA, SMS codes, email codes, or passkeys.

## Information to Collect

Before recording, determine:

1. The website, application, or document URL.
2. The exact sequence of actions to demonstrate.
3. Whether authentication is required.
4. Preferred cursor speed, pacing, marker colors, and annotations.
5. The desired output path.

## DemoScript Workflow

1. Save the user's normal-language scenario to a UTF-8 text file.
2. Discover visible interactive elements before planning selectors:

    hermes-screencast demo-discover https://example.com \
      --headless \
      --profile product-discovery \
      --output discovery.json

   Review unresolved elements and duplicate role/name warnings. Discovery never
   records input values and redacts URL query values.

3. Generate a validated DemoScript with the configured provider adapter:

    hermes-screencast demo-generate scenario.txt \
      --target-url https://example.com \
      --discovery discovery.json \
      --provider-command /path/to/hermes-provider \
      --output scenario.json

   The adapter reads a prompt from standard input and writes only a DemoScript
   JSON object to standard output. Keep provider credentials in its environment,
   never in the scenario or generated JSON.

4. Confirm that generated selectors come from the discovery report and that
   `goto` is the first step.
5. Validate the scenario:

    hermes-screencast demo-validate scenario.json

6. Review the deterministic action plan:

    hermes-screencast demo-plan scenario.json

7. Record the professional MP4:

    hermes-screencast demo-record scenario.json \
      --output result.mp4 \
      --events-output result.events.json \
      --profile product-demo

8. Verify that the synchronized event sidecar exists. It must not contain form
   values or unredacted URL query values.
9. Create and validate a portable project when later editing is expected:

    hermes-screencast project-init product.hermes \
      --title "Product demo" \
      --video result.mp4 \
      --events result.events.json \
      --script scenario.json

    hermes-screencast project-validate product.hermes

10. Generate the editable automatic camera track when click geometry is
    available:

    hermes-screencast project-auto-zoom product.hermes

    This updates `project.json` only. It must not modify or re-encode the source
    MP4. Re-running it replaces the generated `auto-zoom` track.
11. Return the final absolute MP4, event-log, and project paths to the user.

## Recording Behavior

- Use natural cursor movement.
- Move the cursor to an element before clicking, hovering, or filling it.
- Use short pauses so the viewer can understand each action.
- Avoid unnecessary idle time.
- Use narration overlays only when they improve clarity.
- Use markers, boxes, arrows, and highlights sparingly.
- Stop and report the failed step when an expected element is missing.
- Keep the recording clean and suitable for import into CapCut.

## Authentication Rules

- `public`: no login required.
- `authenticated`: use an existing persistent browser profile.
- `assisted_login`: allow the user to complete login, CAPTCHA, or 2FA manually before recording continues.

Never claim to bypass CAPTCHA or 2FA.

## Verification Checklist

- [ ] The DemoScript has a non-empty title.
- [ ] The first step is `goto`.
- [ ] At least one recorded step follows `goto`.
- [ ] Browser actions completed without error.
- [ ] The final MP4 contains a readable video stream.
- [ ] The video has a positive duration and valid dimensions.
- [ ] No Xvfb or FFmpeg recording process remains running.
