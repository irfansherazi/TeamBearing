---
version: next
status: completed
priority: high
complexity: 2
linked_tasks: [nightly-scheduled-playwright-test-suite-run]
created: 2026-08-11
completed: 2026-08-11
---

# Nightly Scheduled Playwright Test Suite Run

Wire the existing headless suite runner into a nightly automated schedule so a two-test regression subset runs unattended every night and posts pass/fail results to Slack. Every underlying piece already ships and runs 24/7 — only the schedule + notification path are missing.

**What already exists (not in scope to build):**

- `POST /playwright/run-suite` — runs the full suite or a caller-selected subset headlessly on the vQA container
- Fargate deployment (`deploy.sh`) — the vQA container runs 24/7, so the endpoint is always reachable
- `scripts/benchmark_pipeline.py` — deterministic benchmark harness; explicitly flagged in a reflection doc as "wire into CI as a nightly job — do this regardless of everything else"

**What this feature adds:**

- A **nightly schedule** (cron trigger) that fires once per 24h at a fixed time, cheapest available option using vendors already in the stack — **EventBridge Scheduler → Fargate** or **k8s CronJob**, whichever costs less on our current infra footprint. Decide during `/bmb:plan`.
- The scheduled trigger invokes `POST /playwright/run-suite` with a **two-test subset** (the smallest meaningful regression signal — exact tests chosen during planning).
- **Slack notification** with pass/fail summary + link to full report. Slack is the only destination for now (Jira comment / dashboard are out of scope).
- **Failure semantics**: any test failing counts as a run failure; the Slack post distinguishes green vs red at a glance.

**Open decisions (resolve in `/bmb:plan`):**

1. EventBridge Scheduler + Fargate task vs. k8s CronJob — pick the cheaper path given current infra utilization
2. Which two tests form the subset — should be the shortest-cycle, highest-signal pair currently in the suite
3. Slack incoming webhook vs. Slack Bot token — driven by which channel we post to and current secret-management posture
4. Time of day for the run (US/Eastern), avoiding overlap with other scheduled jobs on the Fargate cluster

**Out of scope:**

- Results routing beyond Slack (Jira comments, dashboards, per-team routing)
- Historical result storage / trend visualization
- Alerting escalation (paging, retries)
- Expanding beyond the two-test subset (a follow-up can broaden coverage once the schedule is proven stable)

**Complexity rationale**: Level 2. Requirements are clear (schedule + POST + notify), but there is one small design decision (EventBridge vs k8s cron) plus secondary decisions (which two tests, webhook vs bot). Solution is bounded to a handful of files: one workflow/module for the schedule, one thin notification handler, one config entry for the test subset. No design exploration warranted — `/bmb:plan → /bmb:build` is the right shape.
