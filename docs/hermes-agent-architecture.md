# Hermes Agent Architecture

Hermes is an autonomous screencast agent that turns a user-written scenario into a polished video walkthrough of a SaaS product, website, document, or productivity tool.

The final output is an MP4 screencast that is ready to upload to YouTube without manual post-production.

## Product Goal

Hermes transforms user input into a finished video demonstration.

User input includes:

- a written scenario
- a target application, website, document, or local tool
- optional credentials
- presentation preferences such as cursor speed, marker style, highlight colors, and pacing

Hermes output includes:

- a finished 1080p or 4K MP4 video
- visible cursor movement
- precise clicks
- vertical and horizontal scrolling
- form filling
- zoomed detail views
- annotations
- colored highlights
- timing synchronized with the scenario

## Core Principle

Hermes is not only a screen recorder.

Hermes is a screencast director.

It must understand what should be demonstrated, plan how to show it clearly, execute the interaction, validate that the expected screen state is visible, and record the result as a coherent video.

## High-Level Flow

User Scenario
-> Scenario Parser
-> Structured Demo Plan
-> Validation / Dry Run
-> Browser or App Runtime
-> Visual Direction Layer
-> Recording Layer
-> MP4 Export

## Main Architecture Layers

### 1. Scenario Layer

The Scenario Layer converts a natural-language user script into a structured demo plan.

Responsibilities:

- parse the user's scenario
- identify scenes and steps
- identify required user actions
- identify narration or explanatory text
- identify visual emphasis points
- detect missing information
- produce a deterministic plan that can be validated and executed

Example scenario text:

    Open the dashboard, show the revenue chart, highlight the conversion rate,
    then scroll down to the customer table and filter by active users.

Example structured plan:

    {
      "scenes": [
        {
          "title": "Dashboard overview",
          "steps": [
            {
              "action": "open_url",
              "target": "https://example.com/dashboard"
            },
            {
              "action": "highlight",
              "target": "Revenue chart",
              "style": "outline"
            },
            {
              "action": "zoom",
              "target": "Conversion rate"
            },
            {
              "action": "scroll",
              "direction": "down",
              "target": "Customer table"
            },
            {
              "action": "fill",
              "target": "Status filter",
              "value": "Active"
            }
          ]
        }
      ]
    }

### 2. Planning Layer

The Planning Layer turns the structured demo plan into executable operations.

Responsibilities:

- decide the order of browser or application actions
- estimate timing
- insert pauses where the viewer needs time to understand the screen
- speed up repetitive or low-value operations
- attach visual effects to actions
- prepare fallback behavior when an element cannot be found

The planner should preserve the user's intent, but it may make small improvements for clarity.

Acceptable improvements:

- slow down near an important button
- add a short pause after a key result appears
- zoom into a dense table cell
- use a highlight before clicking an important control
- speed up a long scroll

### 3. Runtime Control Layer

The Runtime Control Layer performs the actual interaction with the target environment.

For web applications, this layer is expected to use a browser automation runtime.

Responsibilities:

- open URLs
- wait for pages to load
- locate interface elements
- move the cursor to elements
- click elements
- type text into fields
- submit forms
- scroll vertically or horizontally
- read the current page state
- detect navigation changes
- collect screenshots or frame state for validation

The runtime must never blindly assume that an action succeeded. It should validate important state transitions.

### 4. Visual Direction Layer

The Visual Direction Layer makes the screencast understandable and polished.

Responsibilities:

- render a visible cursor
- move the cursor naturally
- synchronize cursor motion with the scenario
- show clicks clearly
- show drag actions clearly
- add highlights
- add colored markers
- add outlines
- add arrows
- add callouts
- add zoom effects
- add temporary annotation overlays
- remove annotations at the correct time

Required visual primitives:

- cursor_move
- cursor_click
- cursor_double_click
- cursor_drag
- scroll_vertical
- scroll_horizontal
- zoom_region
- highlight_region
- outline_region
- underline_region
- draw_arrow
- draw_box
- draw_circle
- show_label
- hide_label
- clear_annotations

The default style should feel like a professional human-led product demo.

### 5. Recording Layer

The Recording Layer captures the screen and visual overlays.

Responsibilities:

- record the target viewport
- record visual annotations
- preserve cursor visibility
- keep a stable resolution
- keep a stable frame rate
- synchronize video timing with the execution timeline
- produce raw video segments when needed
- pass recordings to the export pipeline

Target formats:

- 1080p MP4
- 4K MP4 where supported

### 6. Synchronization Layer

The Synchronization Layer aligns actions, annotations, pauses, and narration timing.

Responsibilities:

- ensure that visual actions happen at the intended moment
- wait before moving to the next step when the viewer needs context
- keep clicks aligned with the visible cursor
- keep highlights aligned with the UI element they refer to
- support future voiceover or generated narration timing

Hermes should treat timing as part of the demo plan, not as an accidental side effect of execution speed.

### 7. Validation Layer

The Validation Layer checks whether Hermes is still on the correct path.

Responsibilities:

- verify that a target element exists before clicking
- verify that input fields were filled
- verify that navigation completed
- verify that expected content is visible
- stop when the scenario references a missing or ambiguous element
- request clarification when the next safe action is unclear

Hermes should stop and ask for clarification when:

- a required element cannot be found
- multiple matching elements exist and the intended one is unclear
- credentials are missing
- login fails
- the application state does not match the scenario
- a destructive or irreversible action is requested without explicit confirmation

### 8. Export Layer

The Export Layer prepares the final deliverable.

Responsibilities:

- combine recorded segments
- normalize resolution
- normalize frame rate
- encode MP4
- include overlays and annotations
- produce a video ready for upload
- store metadata about the run

Expected output metadata:

    {
      "format": "mp4",
      "resolution": "1920x1080",
      "duration_seconds": 180,
      "source_scenario": "demo-script.json",
      "status": "completed"
    }

## Input Contract

Hermes should request or accept the following input.

Required:

- scenario
- target application, URL, document, or local tool

Optional:

- credentials
- preferred resolution
- cursor speed
- click style
- marker colors
- highlight style
- zoom style
- pacing preference
- sections to skip
- sections to speed up

## Output Contract

A completed Hermes run should produce:

- MP4 screencast
- execution log
- structured demo plan used for execution
- validation report
- optional screenshots or debug artifacts

## Demo Plan Concepts

### Scene

A scene is a logical section of the video.

Examples:

- login
- dashboard overview
- feature walkthrough
- report export
- final summary

### Step

A step is one user-visible operation inside a scene.

Examples:

- click a button
- fill a field
- scroll to a table
- highlight a chart
- zoom into a metric

### Action

An action is an executable primitive.

Examples:

- open_url
- wait_for_text
- move_cursor
- click
- type_text
- scroll
- highlight
- zoom
- annotate
- clear_annotations
- record_segment

### Assertion

An assertion verifies that the expected state exists.

Examples:

- assert_text_visible
- assert_url_contains
- assert_element_visible
- assert_field_value
- assert_table_row_visible

## Error Handling Philosophy

Hermes should prefer safe interruption over incorrect execution.

If Hermes cannot confidently execute the next step, it should stop and explain:

- what it expected
- what it found
- why the step is unsafe
- what clarification is needed

Hermes should not fabricate successful execution.

## CLI Relationship

The existing demo CLI should evolve toward the Hermes pipeline.

Current CLI concepts:

- demo-init
- demo-validate
- demo-run

Future relationship:

- demo-init creates a demo scenario template
- demo-validate validates scenario structure and required inputs
- demo-run executes the validated plan and produces demo artifacts

Long-term Hermes CLI:

- hermes init
- hermes validate
- hermes plan
- hermes run
- hermes record
- hermes export

The current demo commands can remain as the early implementation path while the architecture matures.

## Suggested Implementation Milestones

### Milestone 1: Scenario Schema

Introduce a structured schema for demo scenarios.

Output:

- demo script schema
- validation rules
- examples

### Milestone 2: Dry-Run Planner

Convert a script into a deterministic execution plan without controlling a browser.

Output:

- plan JSON
- validation report
- readable dry-run summary

### Milestone 3: Browser Executor

Execute basic browser actions.

Output:

- open URL
- click
- type
- scroll
- wait
- assert visible text

### Milestone 4: Cursor and Timing

Add human-like cursor movement and timing.

Output:

- visible cursor path
- click timing
- natural pauses

### Milestone 5: Annotation Layer

Add visual emphasis tools.

Output:

- highlights
- outlines
- labels
- zoom regions
- clear annotation timing

### Milestone 6: Recording

Capture the browser session.

Output:

- recorded video segment
- stable viewport
- cursor and overlays included

### Milestone 7: MP4 Export

Produce final video.

Output:

- final MP4
- run metadata
- export report

### Milestone 8: End-to-End SaaS Demo

Run a complete scenario against a real or fixture SaaS interface.

Output:

- scenario
- plan
- recording
- final MP4
- validation report

## Non-Goals for the Early Version

The early version does not need to support:

- arbitrary native desktop applications
- fully automatic voice generation
- complex video editing timelines
- multi-user collaboration
- destructive production workflows
- bypassing authentication or security controls

## Security and Credential Handling

Credentials must be handled carefully.

Hermes should:

- avoid storing raw credentials in scenario files
- support environment variables or secret references
- mask sensitive values in logs
- avoid showing passwords in the recording
- stop if credentials are missing or invalid
- never attempt to bypass authentication

Example:

    {
      "login": {
        "username_env": "HERMES_DEMO_USERNAME",
        "password_env": "HERMES_DEMO_PASSWORD"
      }
    }

## Professional Demo Defaults

When the user does not specify style preferences, Hermes should use:

- natural cursor speed
- visible but not distracting cursor
- short pauses after important UI changes
- subtle highlights
- clear zoom for dense details
- accelerated long scrolls
- no unnecessary visual clutter

## Design Constraint

Every implementation PR should add one complete capability.

Good PR boundaries:

- add scenario schema
- add dry-run planner
- add browser open URL action
- add click action
- add scroll action
- add annotation primitive
- add recording command
- add MP4 export command

Bad PR boundaries:

- add schema, browser automation, recording, and export together
- refactor unrelated modules while adding a feature
- change CLI behavior without tests or documentation
- add visual effects without validation or examples

## Summary

Hermes should become an autonomous screencast production system.

The architecture should evolve from the existing demo CLI into a pipeline that can:

1. accept a user scenario
2. validate required inputs
3. plan the screencast
4. execute browser or application actions
5. direct the visual presentation
6. record the screen
7. export a polished MP4 video

The system should prioritize clarity, safety, validation, and professional presentation quality.
