# Browser Runtime

Browser Runtime is the reusable browser automation layer for Hermes Screencast Agent.

## Layers

Hermes Skill -> Planner -> Browser Runtime -> Recorder -> Output.

## Core Components

BrowserFactory:
- launches Chromium
- uses persistent profiles
- configures viewport
- prepares future Xvfb integration

BrowserSession:
- goto(url)
- wait(seconds)
- click(selector)
- hover(selector)
- scroll(...)
- expose page content for detectors
- coordinate navigation and authentication

SessionManager:
- maps logical profile names to persistent profile directories
- legacy profile uses /root/HermesWorkspace/screencast/chrome-profile
- named profiles use /root/HermesWorkspace/screencast/profiles/<name>

AuthDetector:
- detects whether login is required

ChallengeDetector:
- detects CAPTCHA, Cloudflare, hCaptcha, reCAPTCHA, Turnstile, 2FA, passkeys, email codes, and SMS codes
- never bypasses these checks

AuthPipeline:
- opens page
- detects auth state
- logs in only when credentials are provided
- pauses for assisted login when challenges appear
- continues only after user confirmation

## Safety Rules

- Do not bypass CAPTCHA.
- Do not solve reCAPTCHA or hCaptcha automatically.
- Do not bypass Cloudflare challenges.
- Do not bypass 2FA, SMS, email codes, passkeys, or WebAuthn.
- Use saved sessions or assisted login.

## Target API

with BrowserSession(profile="heygen") as session:
    session.goto("https://app.heygen.com")
    session.ensure_authenticated()
    session.hover("button")

## Recorder Boundary

The Recorder should not own browser logic long-term.

Current MVP bridges to /root/HermesWorkspace/screencast/record_saas.py.

Future versions should split browser control and video capture.
