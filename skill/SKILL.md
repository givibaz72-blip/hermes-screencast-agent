---
name: website-screencast
description: Use when the user asks to record a website screencast, browser walkthrough, SaaS demo, product demo, onboarding video, authenticated web app demo, or polished MP4 recording with cursor movement and automatic zoom.
version: 1.0.0
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

Use this skill to create polished browser screencasts from natural-language user requests.

The local recording stack uses Playwright, persistent Chromium profile, Xvfb, FFmpeg x11grab, cursor event logging, automatic zoom processing, and MP4 verification.

## When to Use

Use this skill when the user asks to record a website demo, SaaS walkthrough, browser workflow, authenticated dashboard, onboarding flow, or MP4 screencast.

Do not use this skill to bypass CAPTCHA, Cloudflare challenges, 2FA, SMS codes, email codes, or passkeys.

## Workflow

1. Convert the user request into a task JSON.
2. Use one of three modes: `public`, `authenticated`, or `assisted_login`.
3. Save the task JSON.
4. Run `hermes-screencast <task.json>`.
5. Return the final `_zoomed.mp4` path.

## Authentication Rules

- `public`: no login required.
- `authenticated`: use the persistent Chrome profile.
- `assisted_login`: user manually completes CAPTCHA/2FA/login, then recording continues.

Never claim to bypass CAPTCHA or 2FA.

## Verification Checklist

- [ ] Task JSON includes `url`, `title`, `mode`, and `steps`.
- [ ] Recorder finishes without error.
- [ ] Final `_zoomed.mp4` exists.
- [ ] Final MP4 is not empty.
