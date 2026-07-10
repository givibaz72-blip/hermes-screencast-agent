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
  -> DemoRunner
  -> DemoExecutor
  -> BrowserDemoExecutor
  -> BrowserRuntime
  -> BrowserSession
  -> Playwright
