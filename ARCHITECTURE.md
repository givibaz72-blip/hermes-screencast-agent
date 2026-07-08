# Architecture

Hermes Screencast Agent is built as a small Python package plus a Hermes Skill.

## Components

- Runner: CLI entrypoint.
- Recorder bridge: calls `/root/HermesWorkspace/screencast/record_saas.py`.
- Verifier: validates final MP4.
- Skill: teaches Hermes when and how to use the CLI.

## Existing dependencies

The MVP reuses the existing screencast stack:

- `/root/HermesWorkspace/screencast/record_saas.py`
- `/root/HermesWorkspace/screencast/apply_zoom.py`
- `/root/HermesWorkspace/screencast/chrome-profile`
