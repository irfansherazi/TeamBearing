---
legacy_id: FEAT-055
version: next
linked_tasks: []
status: planned
---

### FEAT-055: vQA Intelligence Evolution: The Playwright Feedback Loop
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Transform vQA from a tool that tests the codebase into an intelligent agent that learns from the codebase's behavior by leveraging the Playwright ecosystem (tests, infrastructure, and reporting artifacts). This feature establishes a bidirectional feedback loop between the Playwright "Ground Truth" and the vQA intelligence engine. Key pillars:
    1. **SELF-HEALING SELECTORS & AUTOMATED KB UPDATES**: Create a pipeline that parses failed Playwright tests (via LLM-optimized `error-context.md`) and successful traces. When a test fails due to a selector change (e.g., UI refactors or component migrations), vQA automatically updates the `SelectorRAG` and `knowledge/ui_paradigms.md`.
    2. **BLUEPRINT EXTRACTION**: Automatically convert complex E2E flows defined in Playwright "Playlists" (e.g., `qa-196-Files.test.ts`) into reusable `knowledge/blueprints/`. This allows vQA to "inherit" the expertise of manual QA engineers and standardized interaction patterns.
    3. **VISION SYSTEM CALIBRATION**: Use screenshots and traces from `playwright-report/` as a labeled dataset to "train" and calibrate the vQA vision and selector systems (e.g., `test_ac_parser_vision.py`). This improves the agent's ability to verify complex UI states like Toast messages or modal overlays using synthetic ground truth.
    4. **SPECULATIVE EXECUTION VIA MCP TOOLS**: Mature the `playwright/mcp-tools/` integration (using `@playwright/mcp`) to expose the Playwright environment as a first-class toolset for the vQA core agent. Enables "Test-Driven Development for Agents," where the agent can "try" interactions in a headless browser before committing to a strategy.
    5. **DIAGNOSTIC AGENT (RCA INTELLIGENCE)**: Leverage `playwright_index.json` to map failures to JIRA keys and business logic. A "Diagnostic Sub-Agent" analyzes failed test runs to determine root causes (Regression, Flake, or Environment Sync issues) using logs and traces, moving vQA from reporting to diagnosing.
- **Phased Implementation**:
    - **Phase 1: Ingestion (Q2 2026)**: Build `SyncPlaywright` tool to ingest `playwright_index.json` and `Playwright_Knowledge_Sharing.md`; link `error-context.md` generation to the vQA Reflection phase. ✅ (feat-055-phase-1-playwright-ingestion-and-reflection-loop)
    - **Phase 2: Synthesis (Q3 2026)**: Implement Auto-Heal for `SelectorRAG` based on trace comparisons; automate `vSuite-actions.md` updates when Playwright helpers are refactored.
    - **Phase 3: Autonomy (Q4 2026)**: Full integration of `@playwright/mcp` as a core vQA tool; "Zero-Shot" blueprint generation from Playwright test files.
- **Linked Tasks**: None
- **Branch**: feature/FEAT-055-playwright-feedback-loop
- **Created**: 2026-05-29
