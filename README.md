# Hermes Screencast Agent

AI-assisted browser screencast agent for Hermes.

It records polished website walkthroughs using Playwright, Xvfb, FFmpeg, cursor event logging, and automatic zoom processing.

## Status

MVP bootstrap.

## Goals

- Record website and SaaS walkthroughs.
- Use saved browser sessions.
- Support assisted login for CAPTCHA/2FA.
- Apply automatic cursor-centered zoom.
- Verify final MP4 output.
- Integrate with Hermes as a user-local skill.

## Safety

This project does not bypass CAPTCHA, Cloudflare, 2FA, SMS codes, email codes, or passkeys automatically.
