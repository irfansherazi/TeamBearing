---
legacy_id: FEAT-043
version: next
linked_tasks: [headful-playwright-execution-and-test-persistence]
status: complete
---

### FEAT-043: Headful Playwright Execution & Test Persistence
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Two related improvements to the vQA AI-driven testing system. (1) **Headful Playwright**: In the production environment, users cannot see the Playwright browser executing test steps. This fix configures Playwright to run in headful (visible) mode so users can observe the browser in real time as steps are executed. (2) **Test Persistence & Smart Replay**: When a user accepts a vQA test result, the approved run is serialized and saved as a reusable Playwright `.spec` test file. On subsequent runs against the same flow, vQA first checks whether a saved, accepted test exists; if so, it replays the deterministic Playwright script directly, bypassing the LLM/AI entirely. This makes re-execution faster (no LLM roundtrip), cheaper (no token consumption), and progressively smarter — the accumulated library of accepted tests becomes a reference corpus that the AI can learn from when generating new test plans for similar flows. Design decisions required: (1) Headful config — how to propagate `headless: False` to the Playwright launcher in production without affecting CI/headless environments (env-var toggle vs. per-run config flag); (2) Test serialization format — how to represent an accepted vQA run as a runnable Playwright spec (raw action log → Playwright API calls, or Playwright codegen-style recording); (3) Storage strategy — where accepted tests are stored (local filesystem organized by flow/URL/AC hash, or a lightweight DB index), and how to key them for fast lookup; (4) Replay orchestration — how vQA detects a matching saved test at run start, how it validates the test is still compatible with the current UI (version/selector hash check), and how it falls back to AI generation if replay fails; (5) LLM training feedback loop — how accepted tests are surfaced as few-shot examples or context to the planner when generating new tests for similar ACs. Phased implementation: Phase 1 — Headful mode toggle (env-var `VQA_HEADLESS=false`, propagate to Playwright launcher, update deploy/config docs); Phase 2 — Test serialization & storage (accepted-test writer, action-log-to-playwright-spec converter, filesystem index with flow/AC metadata); Phase 3 — Smart replay engine (accepted-test matcher, compatibility validator, replay executor with fallback to AI generation); Phase 4 — LLM feedback integration (accepted tests surfaced as few-shot examples in the planner prompt for matching AC domains). Success metrics: headful mode visible to user within 1s of run start, accepted tests replayed deterministically in ≤ 30% of the original AI-driven run time, replay success rate ≥ 95% when UI has not changed, LLM planner token usage reduced by ≥ 20% on flows with existing accepted tests (via few-shot injection).
- **Linked Tasks**: headful-playwright-execution-and-test-persistence (COMPLETE)
- **Branch**: feature/FEAT-043-headful-playwright-test-persistence
- **Created**: 2026-05-19
- **Completed**: 2026-05-19 ✅
