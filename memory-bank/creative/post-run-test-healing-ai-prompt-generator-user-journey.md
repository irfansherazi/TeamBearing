# User Journey Design: post-run-test-healing-ai-prompt-generator Post-Run Test Healing — AI Prompt Generator

**Created**: 2026-06-09
**Status**: DECIDED
**Decision Type**: User Journey
**Task**: post-run-test-healing-ai-prompt-generator / FEAT-110

---

## Journey Overview

**Feature**: FEAT-110: Post-Run Test Healing — AI Prompt Generator
**Primary Persona**: QA Automation Engineer, Automation Developer
**Journey Type**: Interactive Triage & Resolution Flow
**Orchestration Pattern**: Click to Compile + Modal Interaction + One-Click Clipboard Copying

### Success Statement
> A Test Developer triggers a 40-test regression suite, which finishes with 2 failures. Instead of context-switching to their editor, hunting down the test paths, opening logs in a separate tab, and copy-pasting code chunks into a chat interface, they click "🩹 Heal Tests" directly on the results dashboard. Within 2 seconds, a beautiful modal overlay renders containing a meticulously crafted, pre-truncated prompt with full framework and code context. Clicking "Copy Prompt" gives them a copy-ready payload to feed into Claude/Gemini, getting instant, perfectly-fitted code fixes in return.

---

## Persona Context

### Primary Persona: QA Automation Developer
- **Who**: Writes and maintains playwright scripts to cover intricate React/PrimeNG workflows.
- **Goal**: Rapidly resolve flaky or broken tests identified during regression suite runs.
- **Pain Points**:
  - Extracting the correct slice of failing test code can be tedious.
  - Raw assertion logs and stack traces are hard to decipher in isolation.
  - Manual assembly of AI prompt context wastes valuable dev time.
- **Needs**: An automated context bundler that bridges the gap between test execution failure and AI-guided test repair.

---

## Journey Maps

### Journey 1: Compiling the Healing Prompt

```
[Developer reviews failed Suite run in SuiteResultsPanel]
  │
  ├──► Identifies 2 failed tests at the top of the table list
  │
  ▼
[Click "🩹 Heal Tests" button in the upper header]
  │
  ├──(1) Button transitions to a loading state: "⏳ Generating..."
  ├──(2) Spinner overlay shows in-progress generation activity
  ├──(3) Backend parses suite-run state, resolves file paths, trims code (>300 lines)
  │
  ▼
[API success response received]
  │
  ├──(1) UI displays <HealTestsModal /> overlay with a smooth fade-in backdrop
  ├──(2) Monospace container displays the generated markdown prompt
  └──(3) Action controls ("Copy Prompt", "Close") light up at the footer
```

---

### Journey 2: One-Click Copying and State Restoration

```
[Developer reviews compiled prompt inside the Modal overlay]
  │
  ▼
[Click "📋 Copy Prompt" button]
  │
  ├──(1) UI executes navigator.clipboard.writeText with the prompt's content
  ├──(2) Button instantly updates to a green "✅ Copied!" state
  ├──(3) PlaywrightPage holds success state for 2 seconds (visual confirmation)
  ├──(4) After 2 seconds, button smoothly transitions back to "📋 Copy Prompt"
  │
  ▼
[Developer closes the Modal]
  │
  ├──► Clicking the close button [X] or "Close" footer button hides the modal
  └──► Focus returns seamlessly to the SuiteResultsPanel to allow further inspection
```

---

## State Transition Map

The frontend state machine governs the following visual states:

```
                          +-----------------------------------+
                          |            IDLE / HIDDEN          |
                          +-----------------------------------+
                                            │
                                            │ Click "Heal Tests" (visible only if report.failed > 0)
                                            ▼
                          +-----------------------------------+
                          |            GENERATING             |
                          |      (Spinner / Button Loader)    |
                          +-----------------------------------+
                                            │
                                            │ API Success: prompt received
                                            ▼
                          +-----------------------------------+
                          |            MODAL_OPEN             |◄────────┐
                          +-----------------------------------+         │
                                            │                           │
                                            │ Click "Copy Prompt"       │ 2-second timeout
                                            ▼                           │
                          +-----------------------------------+         │
                          |         COPY_CONFIRMATION         |─────────┘
                          |            (Copied! state)        |
                          +-----------------------------------+
                                            │
                                            │ Click "Close" / backdrop click
                                            ▼
                          +-----------------------------------+
                          |            IDLE / HIDDEN          |
                          +-----------------------------------+
```
