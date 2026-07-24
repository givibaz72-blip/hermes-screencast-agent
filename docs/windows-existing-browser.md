# Existing Windows Browser Mode

## Goal

Hermes must be able to use an already running Chrome started manually by the user.

User flow:

1. User starts Chrome normally.
2. User logs into HeyGen manually.
3. Hermes connects to the existing browser.
4. Hermes records and controls only the required tab.

No automatic login.
No profile management.
No Playwright profile bootstrapping.

## Requirements

- Existing Chrome only
- Remote debugging enabled
- Reuse authenticated session
- Raw CDP support
- Playwright support (optional)
- Windows first

## Future CLI

--browser existing
--browser-url http://127.0.0.1:9222
