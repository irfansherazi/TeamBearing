# System Patterns

## Guiding Principles

| Principle | Description |
|---|---|
| **Multimodal Grounding** | Every action decision combines a screenshot (visual) with an ARIA accessibility tree (structural) — neither alone is sufficient |
| **Session Context** | High-priority `<session_context>` block grounds the planner in the current URL, page heading, and last 3 navigation actions (FEAT-028). |
| **Semantic Locators First** | `get_by_role`, `get_by_label`, `get_by_text` preferred over CSS selectors to survive UI reshuffle |
| **Failure Diary Pattern** | Track per-locator failure counts to prevent infinite retry loops on the same broken selector |
| **Programmatic Tier 1 Verification** | DOM checks via Playwright are fast and deterministic; LLM visual verification is fallback only |
| **Config in Environment** | All credentials, URLs, and feature flags via `.env` / environment variables — nothing hardcoded |
| **12-Factor App** | Dev/prod parity; configuration from environment; stateless processes |
| **HITL as Learning Signal** | Every human takeover writes to `knowledge/human_guidance.md` and syncs to Bedrock KB — the agent improves over time |
| **Early Import Pre-caching** | Pre-import `numpy` and `sklearn` in main entrypoints to resolve Python 3.13 import ordering bugs with `pydantic` |
| **Secret Environment Injection** | Resolve secrets via SSM/Vault then inject into `os.environ` to support legacy `os.getenv` consumers consistently |

## Architecture Overview

vQA is a **LangGraph state machine** wrapped in a FastAPI HTTP/WebSocket server. The frontend dashboard connects via WebSocket to stream real-time execution logs. The core execution logic is a see-think-act loop where Claude 3.5 Sonnet reasons multimodally about the live browser state.

### LangGraph Node Graph

```
START
  └── jira_fetch_node          # Fetch ticket + AC from Jira REST API
        └── ac_parser_node     # Two-stage AC → structured test plan
              └── setup_role_node  # Load role credentials + inject constraints
                    └── login_node # Playwright login + JWT verification
                          └── planner_node ◄──────────────┐
                                └── executor_node          │
                                      └── evaluator_node ──┤ (retry)
                                            ├── verifier_node ──┘
                                            ├── human_takeover_node (stuck)
                                            └── reporter_node (done/fatal)
                                                  └── END
```

### See-Think-Act Loop (Per Action)

```
SEE:   screenshot (full-page PNG, base64) + ARIA tree snapshot
THINK: Claude 3.5 Sonnet multimodal call → JSON action
       { "action": "click", "strategy": "get_by_role",
         "role": "button", "name": "Submit", "reasoning": "..." }
ACT:   Playwright dispatches → page.get_by_role("button", name="Submit").click()
       Post-action screenshot → S3 upload → ExecutionStep appended to audit log
```

### Execution Mode Split

| Mode | Transport | Display | Use Case |
|---|---|---|---|
| **Interactive** | Docker + Xvfb + x11vnc + noVNC | Live browser in React dashboard | PM/QA visual confirmation |
| **Headless** | Playwright headless | None | CI/CD deployment gating |

## Reliability & Prompt Engineering

### Prompt Hardening Standards
- **Anchoring**: Critical rules are anchored at both the START (Primacy) and END (Recency) of system prompts to mitigate "lost in the middle" syndrome.
- **Structural Delimiters**: XML-style tags (e.g., `<RULES>`, `<CONTEXT>`, `<EXAMPLES>`) are used to strictly isolate instructions from dynamic context.
- **Few-Shot Grounding**: Domain-specific failure modes (e.g., PrimeNG sorting re-renders, word fusion) are addressed through curated few-shot examples.
- **Prompt Audit Checklist**: All prompt modifications must pass the checklist in `knowledge/prompt_audit_checklist.md`.

### Execution Reliability
- **Verification Tiering**: Two-tier verification (Programmatic Playwright + LLM-as-a-Judge) ensures high confidence without excessive LLM costs.
- **Fail-Fast Loops**: Circuit breakers on `verifier_not_yet_count` and `retry_count` prevent infinite loops.
- **Deterministic Timing (FEAT-058)**: Supports `post_action_wait_ms` in the structured test plan to allow framework re-renders (Angular/PrimeNG) to settle before verification begins.
- **Anti-Loop Circuit Breaker (FEAT-058)**: Implements `goal_satisfiable_check` which skips an AC step (verdict: `SKIPPED`) if verification fails 3 times consecutively despite successful actions, preventing infinite iteration budget burn.
- **Ambiguity Pre-Check (FEAT-058)**: Runs a grounding analysis on raw Jira AC before execution. Flags vague requirements (e.g., "Sorts correctly") that lack specific UI targets, preventing untestable runs.
- **Amnesic Loop Circuit Breaker (FEAT-062)**: Monitors URL and DOM element count for stagnation. If the agent issues 3 consecutive actions without semantic progress, a circuit breaker trips and escalates to `human_takeover_node` to prevent budget waste.
- **Visual Delta CV Verification (FEAT-062)**: Integrates pixel-level screenshot diffing (PIL ImageChops) into coordinate-based interactions. A 0.5% pixel change threshold acts as the ground truth for success on Canvas/SPA elements where the DOM is opaque.
- **Multi-Signal Delta Verification (FEAT-064)**: Replaces DOM-only stagnant UI checks with a composite delta of URL, element count, DOM snapshot, and visual changes. This prevents amnesic loops on subtle UI transitions (e.g., list updates) where the DOM structure remains identical.
- **Portal-Aware DOM Culling (FEAT-064)**: Implements explicit guards for PrimeNG/Material portal components (e.g., `.p-connected-overlay-visible`). Ensures that active overlays are never pruned during aggressive DOM culling, preserving critical interactive elements in the accessibility tree.
- **State-Aware Model Escalation (FEAT-066)**: Automatically switches to high-reasoning models (Claude 3.5 Sonnet) when `retry_count >= 1` and the previous state was a verifier rejection. This ensures that complex failures are met with maximum reasoning power rather than cycling on cheaper models.
- **Selector Integrity Guardrails (FEAT-066)**: Enforces a strict ban on dynamic IDs (matching `\d+`) and fragile deep-DOM chains (`nth-child`) within the planner's system prompts. Mandates the use of semantic roles and `vqa_id` attributes to ensure long-term test stability.
- **Verifier Guardrails (FEAT-063)**: Implements mechanical success gating between evaluator and verifier. The verifier is only invoked if the executor reports success, and it MUST perform a standalone `capture()` to ensure decisions are grounded in fresh post-action state.
- **Human-in-the-Loop Correction (FEAT-063)**: Provides a "False Positive" button in the frontend `StepTable`. Human corrections are injected as high-priority grounding signals into the next planner iteration, overriding agent hallucinations and forcing a detour.
- **AST-Based Semantic DOM Culling (FEAT-071 / TASK-094)**: Compresses the indented accessibility tree snapshot bottom-up by pruning layout boilerplate, presentation containers, and deeply nested interactive-free wrappers while preserving interactive roles, safety landmarks, and their structural ancestor tree. Achieves ≥50% character count reduction to optimize prompt token limits.
- **Split-Execution Local Coordinate Resolution (FEAT-071 / TASK-094)**: Separates high-level action intent (multimodal VLM planner outputs semantic descriptions like `semantic_click` or `semantic_fill` on a clean screenshot) from coordinate calculations. A local resolver evaluates element bounds and matches text properties via weighted Jaccard word token similarity, avoiding slow and cluttered Set-of-Marks overlay generation.
- **AI-to-Code Test Synthesis (FEAT-072 / TASK-095)**: Translates successful execution logs containing JSON action sequences into valid, compileable, type-safe Playwright TypeScript integration tests (`.spec.ts`). Saves synthesized files to `playwright/tests/`, registers metadata in `playwright/playwright_index.json`, and automates branch creation and PR opening using git and GitHub CLI.
- **Predictive State Verification (FEAT-072 / TASK-095)**: Intercepts action completion in `executor.py` with a lightweight, low-latency DOM/URL verification check (`PredictiveVerifier`) matching the planner's output `state_expectation` field. If a mismatch is detected, it raises a `PredictiveVerificationError` immediately, short-circuiting to the self-healing recovery path and bypassing standard 30-second Playwright timeouts.

## Key Design Patterns

### Reducer-Based LangGraph State
`VQAState` uses `operator.add` reducers for list fields (execution log, screenshots) and `_merge_dicts` for dicts. LangGraph automatically appends rather than overwrites across parallel branches.

### Two-Stage AC Parsing
`ac_parser.py` runs two sequential LLM calls:
1. BDD Normalizer — raw Jira AC text → Given/When/Then format
2. JSON Compiler — BDD steps → structured `{ steps: [...], roles: [...] }` test plan

This separation of concerns makes each stage independently testable and debuggable.

### HITL Pause via asyncio.Event
`human_takeover_node` calls `asyncio.Event.wait()` to pause the LangGraph execution without blocking the FastAPI HTTP server. The WebSocket broadcasts `WAITING_FOR_HUMAN`. When the user clicks "Done" on the dashboard, `POST /runs/{run_id}/human-takeover/done` sets the event, resuming the graph.

### Dynamic Takeover UI Pattern (Phase 1)
In interactive mode, static screenshot-based takeover is replaced by a live, interactive "Command Center".
- **Backend**: `VncUrlBuilder` constructs a dynamic URL using the incoming `Host` and `X-Forwarded-Proto` headers. For non-VNC environments, `human_takeover_node` attaches a CDP session and streams live JPEG frames via `Page.startScreencast` to the `hitl_screenshot_update` WebSocket channel (TASK-085).
- **Action Echoing**: Human interactions captured by JS listeners are broadcast back to the frontend in real-time, populating a `HitlRecordingFeed` to confirm knowledge capture (TASK-085).
- **Dialog Interception**: Native browser dialogs (`alert`, `confirm`, `prompt`) are intercepted via `page.on("dialog")` and rendered as custom UI overlays, preventing session hangs (TASK-085).
- **Frontend**: `TakeoverPanel` is implemented as a global modal with backdrop blur, ensuring high visibility. A `GlobalHitlBanner` provides cross-tab notifications for active interventions (TASK-085).
- **State Persistence**: `VQAState` stores `request_host` and `request_protocol` from the initial execution request to ensure VNC consistency throughout the run.

### Blueprint YAML Runner
`recipe_runner.py` executes YAML blueprint templates (e.g., `login.yaml`, `p_calendar_single.yaml`) for known multi-step interactions. The executor dispatches a `recipe` action type that runs the entire YAML sequence as a unit.

### Proactive Overlay Dismissal
The executor implements a pre-action gate to prevent oscillation loops caused by blocking overlays (modals, dropdowns, dialogs). 
- **Problem**: The LLM planner may try to interact with an element that is visually or functionally blocked by an open overlay, leading to repeated failures or "stuck" states.
- **Solution**: Before dispatching any action, the executor consults the `PageStateTracker`. If an overlay is detected and the target element is "outside" that overlay's scope, the executor proactively sends an `Escape` keypress to dismiss the blocker and refreshes the page state before proceeding with the original action.

### RAG-Based KB Retrieval
`backend/kb/playwright_rag.py` uses TF-IDF vectorization over `human_guidance.md` and `vSuite-actions.md` to retrieve the most relevant passages for each AC step before the planner call. Retrieved passages are appended to the planner system prompt.

### Atomic Step Decomposition (FEAT-057)
Instructs the BDD Normalizer (Stage 1) to split compound Jira actions joined by "then", "and", "followed by" into separate atomic steps. This ensures the See-Think-Act loop remains focused on single interactions, increasing execution reliability for complex requirements.

### Deferred Sub-step Verification (FEAT-057)
Uses `current_sub_step_index` in `VQAState` to manage mechanically inseparable compound actions (e.g., fill+Enter). The evaluator defers full verifier-node checks until the final sub-step completes, allowing a sequence of actions to be treated as a single AC step without intermediate verification noise.

### Failure Classifier → Router
`evaluator.py` classifies failures into typed categories: `STRICT_MODE`, `TIMEOUT`, `DISABLED`, `INVISIBLE`, `STALE_LOCATOR`, etc. The router uses retry count + failure type to decide: retry (planner), escalate (human_takeover), or abort (reporter with FATAL status).

### Identical-Action Circuit Breaker
The `evaluator_node` maintains an `action_repeat_counts` tracking mechanism to prevent infinite see-think-act loops where the agent repeatedly issues the exact same action. If an identical action is logged 5 times, a circuit breaker trips and escalates the run to `human_takeover_node`, preventing `GraphRecursionError` timeouts.

### Automated Registry Sync
Bridges the gap between frontend framework templates (e.g., Angular p-dropdown) and the agent's Knowledge Base via scanner scripts. This pattern ensures the agent has up-to-date knowledge of valid UI options without manual maintenance.

### State-Driven Reporting
Downstream consumers (Reporter, Frontend) rely on explicit `VQAState` fields (e.g., `ac_steps_coverage_gap`) rather than parsing logs. This pattern ensures that reporting is robust to log formatting changes and makes the state the single source of truth for execution outcomes.

### AST-Based Semantic DOM Culling (FEAT-071 / TASK-094)
Implements `SemanticDOMCuller` in `backend/engine/culler.py`. It:
1. Parses indented accessibility tree snapshots bottom-up.
2. Recursively marks interactive nodes (roles like `button`, `textbox`, `combobox`) and safety landmarks (roles like `dialog`, `navigation`, `alert`).
3. Retains structural parent nodes to keep tree integrity, while pruning non-interactive layout wrappers.
4. Serializes the compressed AST to text, cutting token sizes by over 50% on large Angular/PrimeNG pages.

### Split-Execution Local Coordinate Resolution (FEAT-071 / TASK-094)
Separates intent from mechanical execution.
1. The planner outputs high-level actions: `{"action": "semantic_click", "target": "Submit button"}`.
2. `LocalObjectDetector` evaluates a viewport-relative element query.
3. The detector scores candidates using a hybrid substring match and Jaccard word token similarity check against text content, aria-label, placeholder, title, and name.
4. The executor clicks the center coordinates of the best match, falling back to a CSS selector locator or standard role-based Playwright locator if resolution fails.

### CV Fallback Layer (FEAT-037 / TASK-028)
An **executor-side recovery path** that activates after DOM failure exhaustion and before HITL escalation — covering Shadow DOM, Canvas, and iFrame elements with no accessible DOM locator.

**Architecture**: Option A (Executor-side recovery) — CV fallback is self-contained inside `executor_node`'s `_dispatch_action` failure path. No LangGraph node additions, no planner changes.

**Activation chain**:
1. `_dispatch_action()` returns `success=False` for a `click`/`coordinate_action`
2. `CvFallbackResolver.should_activate()` checks: feature flag + action type + fail_count ≥ threshold + no prior CV attempt this step
3. `CvFallbackResolver.resolve()` captures SoM screenshot → invokes vision LLM (Claude via Bedrock) → returns `mark_id`
4. Executor maps `mark_id → (x, y)` and fires `page.mouse.click(x, y)`
5. **Phase 3**: `cv_fallback_state_change_check()` waits 2 s then checks URL/ARIA/element-count delta
   - State changed → `CV_CLICK_SUCCESS`, result overridden to `success=True`
   - No change → `CV_CLICK_FAILED`, HITL escalation with rich context

**Cost gate**: Vision LLM never invoked on first attempt. Threshold: `ac_step_action_fail_count >= CV_FALLBACK_MIN_DOM_FAILURES` (default: 3). `cv_fallback_eligible: true` on action lowers threshold to 1.

**State fields**: `cv_fallback_invocations: int`, `cv_fallback_results: list[dict]` (LangGraph reducer appends).

**Key files**: `backend/browser/cv_resolver.py` (resolver + cost gate), `backend/engine/verifier.py::cv_fallback_state_change_check` (state change detection), `backend/engine/executor.py` (wiring).

**Tests**: `tests/test_cv_fallback_cost_gate.py`, `tests/test_cv_fallback_resolver.py`, `tests/test_cv_fallback_verifier.py`

### AC Quality Gate (FEAT-001)
`ac_quality_gate.py` runs a **zero-LLM-cost rule-based scorer** on raw AC text before it enters Stage 1 BDD normalization. Evaluates 5 quality dimensions (Specificity, Observable Outcome, Actionability, Precondition Clarity, Scope Atomicity) on a 0–2 scale each (max 10). The gate enforces a three-tier response:

- **POOR (0–3)**: Hard-reject. `ac_parser.py` sets `parse_quality="rejected"` and returns without invoking any LLM call. The user must refine the AC text before re-submitting. (`ac_parser.py:1117-1145`)
- **FAIR (4–6)**: HITL pause via `asyncio.Event`. The run blocks and broadcasts a `PRE_PARSE_GUIDANCE_REQUIRED` WebSocket event, waiting for the operator to either provide clarifying guidance or click "Proceed Anyway" to bypass. (`ac_parser.py:992-1034`)
- **GOOD (7–10)**: Proceeds immediately to Stage 1 BDD normalization with no pause or intervention.

**Note:** The gate is entirely rule-based — it runs before any LLM call and incurs zero LLM cost.

### Vision-Assisted AC Enrichment (FEAT-045)
`VisionAnalyzer` (`backend/engine/vision_analyzer.py`) uses Claude 3.5 Sonnet Vision (Bedrock) to extract **visual grounding context** from Jira image attachments before BDD normalization. The `ac_parser_node` fetches all image attachments from the Jira ticket, runs them through `VisionAnalyzer.analyze_image()`, and injects the resulting `{visual_context}` into the `BDD_NORMALIZER_PROMPT`. This grounds the test plan in visual reality (e.g., field labels, button text) visible in wireframes or screenshots attached to the Jira card.

**Pipeline addition** (executes before Stage 1):
```
jira_fetch_node → [attachment fetch + VisionAnalyzer] → ac_parser_node (Stage 1 BDD)
```

### COVERAGE_GAP Priority Override in Reporter (TASK-048)
`reporter.py` extracts a `coverage_gap_indices` set from `bug_log` entries where `type == "COVERAGE_GAP"`. These indices take priority over `ac_steps_completed` in both `_render_header` and `_render_ac_table`:
- **Header**: `all_passed` is `False` if any gap index exists; pass count subtracts gap count.
- **AC table**: gap indices render as ✗ (fail class) even if the index also appears in `completed`.

This is a **priority override pattern** — `bug_log` annotation beats completion state, ensuring coverage gaps are never silently reported as passing.

### Triage Panel Pattern
`TriagePanel.tsx` displays after a failed run. It shows an overall failure classification badge (Product Bug / Jira Unclear / Mixed), an executive summary, per-step breakdowns with color-coded badges, and a guidance input field. This gives PM/QA users actionable context without requiring them to parse raw execution logs.

### Execution Engine Routing
Uses a router node at the beginning of the LangGraph to branch execution based on the `execution_engine` state field. This allows the system to switch between the autonomous AI Agent and static Playwright test execution paths within the same graph structure.

### Subprocess Log Streaming
Executes static tests as subprocesses and captures stdout/stderr line-by-line. These logs are streamed in real-time to the frontend via WebSockets using `WSTerminalLogMessage`, providing immediate user feedback for long-running static tests.

### Test Library Registry
Maintains a JSON-backed registry (`playwright_index.json`) that maps discovered Playwright test files to metadata (IDs, descriptions, jira_keys, step_names). This registry is the source of truth for the frontend `PlaywrightLibrary` component and the backend executor.

**Product-scoped filtering** (TASK-124/Phase5): `PlaywrightRegistry.list_tests_for_product(playwright_tests_dir)` filters the index by the path prefix derived from the product's `playwright_tests_dir` config field (e.g., `"playwright/tests/vpromedia"` → prefix `"tests/vpromedia/"`). The `GET /playwright/tests?product=<slug>` and `GET /playwright/match/{id}?product=<slug>` endpoints accept an optional `product` query param; when present, only tests under that product's directory are returned. Callers without a `product` param receive the full unfiltered index for backwards compatibility.

### Mode-Centric Progressive Disclosure (TASK-065)
The main execution dashboard uses a 4-mode state machine (SELECT → REVIEW → RUNNING → COMPLETE) to manage the test lifecycle. 
- **SELECT**: Initial test configuration (Jira ticket, persona, environment).
- **REVIEW**: Pre-run step analysis and editing.
- **RUNNING**: Live execution monitoring with real-time status badges.
- **COMPLETE**: Post-run analysis and triage.
This pattern reduces cognitive load by hiding irrelevant controls and focusing the user on the current task.

### Component-Driven State Display (TASK-065)
Reusable UI components (e.g., `StepTable`) are designed to be mode-aware, using a single data structure to drive display across different workflow phases. This ensures that the visual representation of a "test step" remains consistent whether it is being edited, monitored, or analyzed after completion.

### Dual Execution Engine Pattern (FEAT-051 / TASK-059)
vQA supports two mutually exclusive execution engines selectable at run time:
- **AI Agent** (default): LangGraph See-Think-Act loop via `executor.py` and `planner.py`
- **Static Playwright**: Deterministic spec execution via `playwright_executor.py` — discovers, runs, and streams output from `.spec.ts` files in `playwright/tests/{product-slug}/` (product-scoped since TASK-124/Phase5)

The `PlaywrightLibrary` frontend component lists registered tests from the backend `GET /playwright/tests` endpoint. Running a static test goes through `POST /playwright/run/{test_id}`, with real-time log streaming via the same WebSocket channel. This lets QA engineers access both regression (static) and exploratory (AI) test modes from a single dashboard.

### Independent React Auth System (FEAT-048 / TASK-053)
The frontend uses a self-contained auth subsystem under `src/auth/` that handles JWT/RS256 token lifecycle independently from the backend session model:
- **AuthProvider** wraps the app and manages token state, refresh intervals, and silent re-auth
- **ProtectedRoute** implements an auth guard HOC — unauthenticated requests redirect to `/login`
- **authStorage** persists tokens in `localStorage` with expiry-aware retrieval
- **realAuthApi** calls the vcAPI SSO endpoints directly (not the vQA backend)
- **MFA support**: `MfaPage` handles the TOTP/SMS challenge step before issuing a session token

This pattern decouples auth state from the test execution state, allowing the dashboard to authenticate via vcAPI SSO (RS256) while the backend uses an independent API key (`X-API-Key`) for service-to-service calls.

### Prompt Budget Trimmer (TASK-054)
`prompt_budget.py` enforces a maximum token ceiling on LLM prompts before every Bedrock call. When the assembled prompt (system + context + user) exceeds the budget, it progressively trims lower-priority sections (KB passages, ARIA tree depth, history buffer) while preserving the AC step and screenshot. This prevents context-overflow errors on long-running runs without changing the planner's logic.

### Merge-and-Protect Ingestion (FEAT-055)
Bridges the gap between external automation suites (Playwright) and the vQA Knowledge Base using a "Merge-and-Protect" strategy.
- **Source of Truth**: Playwright test files are treated as the primary source for UI selectors.
- **Protection**: Specific registry entries can be marked with `"protected": true` to prevent automated overrides of human-optimized or vQA-specific selectors.
- **Safety**: Every sync operation (`make sync-playwright`) generates a timestamped backup of the registry before applying changes.

### Structured Failure Reflection (FEAT-055)
Failed runs produce machine-readable artifacts that drive the intelligence feedback loop.
- **Analyzer Node**: The `failure_analyzer.py` classifies the failure and generates a `Lesson` object containing a diagnosis and suggested selector fix.
- **Artifact Persistence**: Both `error-context.json` (machine) and `error-context.md` (human) are uploaded to S3 by the `reporter_node`.
- **Feedback Loop**: These artifacts enable both immediate Jira feedback for developers and future automated knowledge base updates (Self-Healing).

### Product Registry Pattern (FEAT-115 / TASK-124)

vQA is architected as a multi-product platform where a single YAML file drives all product-scoped behaviour without code changes.

**Single source of truth**: `backend/config/products.yaml` maps each product slug to:
- `environments: {name: url}` — named URL map with `default_environment` key
- `jira_board_ids: [...]` — which Jira boards to query for tickets
- `roles: [...]` — which role keys (from `ROLE_REGISTRY`) belong to this product
- `playwright_tests_dir` / `personas_dir` — filesystem prefixes for test and persona scoping

**Backend enforcement**:
- `backend/config/product_registry.py` — `ProductRegistry` / `ProductContext` loader (singleton, cached)
- `backend/api/schemas.py` — `ExecuteRequest.validate_role_product_match` model_validator cross-checks role↔product and auto-resolves `target_url` from `product_ctx.resolve_target_url()` when the client omits it
- Startup validation asserts every `ROLE_REGISTRY` key appears in exactly one product (mutual exclusivity)

**Frontend propagation**:
- `frontend/src/context/ProductContext.tsx` — React context provider persists the active product slug to `localStorage['vqa_product']`; `setProduct()` also clears `localStorage['vqa_targetUrl']` so stale URLs from prior products never bleed through
- `frontend/src/components/ProductSelector.tsx` — dropdown in the Dashboard header; reads from `ProductContext`
- `frontend/src/components/SelectView.tsx` — environment select renders `activeProduct.environments` dynamically; role dropdown filtered to `activeProduct.roles`; `useEffect` syncs `targetUrl` to the product's default URL on product switch

**Extensibility rule**: Adding a new product requires ONLY a new `products.yaml` entry + `playwright/tests/<slug>/` + `knowledge/personas/<slug>/` directories. Zero Python or TypeScript code changes. For cross-domain products (app on a separate domain), also add `playwright_base_url` to `products.yaml` and `productUrl` to `users.json` — see *Cross-Domain Product Auth Pattern* below.

**Key files**:
- `backend/config/products.yaml` — registry (schema_version: 1); `playwright_base_url` field for cross-domain products
- `backend/config/product_registry.py` — `ProductRegistry`, `ProductContext`, `load_product_registry()`
- `backend/api/routes.py` — `GET /products` endpoint; `POST /run/{id}/save-as-test` reads `playwright_base_url` for codegen
- `backend/api/playwright_routes.py` — `GET /playwright/tests?product=` and `GET /playwright/match/{id}?product=`
- `backend/storage/playwright_registry.py` — `PlaywrightRegistry.list_tests_for_product()`
- `frontend/src/context/ProductContext.tsx` — `ProductProvider`, `useProductContext()`
- `frontend/src/components/ProductSelector.tsx` — header selector UI
- `playwright/tests/{product-slug}/` — per-product test subdirectories
- `playwright/fixtures/users/users.json` — user roster per product including `productUrl` for cross-domain users

---

### Cross-Domain Product Auth Pattern

**Context**: Some vCreative products (vPPO, vPromotions) run on a completely separate domain from the Angular SSO gateway (`*.vcreative.net`). After the user selects the product from the product chooser, the browser is redirected to a legacy PHP app or RC environment on a different hostname.

**Problem this causes without the pattern**:
1. `generateStorageStates.mjs` saves cookies only for the SSO domain — the PHP app's session cookie is missing, so every test fails auth silently
2. `assumeUser` navigates to `BASE_URL` (SSO domain), not the app domain — session is never established
3. CSS auth indicators (`#top-navbar`, `.layout-topbar`) don't exist in the legacy PHP DOM — auth detection hangs forever
4. `page.goto('/')` in tests sends the browser back to the product chooser, not the app
5. Computer-use codegen emits the SSO gateway URL instead of the app URL in `page.goto()`

**Solution**:

| Layer | Change | File |
|-------|--------|------|
| Product registry | Add `playwright_base_url: {env: url}` | `backend/config/products.yaml` |
| User fixture | Add `"productUrl": "<app url>"` per user entry | `playwright/fixtures/users/users.json` |
| Storage state capture | After login, navigate to `productUrl` before saving — captures PHP-domain cookies | `playwright/utils/generateStorageStates.mjs` |
| Auth verification | URL-based check (on PHP domain and not on login page) instead of CSS selectors | `playwright/utils/loginHelper.mjs` (`assumeUser`) |
| Test setup | Navigate to `PRODUCT_BASE_URL` constant, not `'/'` | every cross-domain test file |
| Codegen | Reads `playwright_base_url` from registry; emits named constant import | `backend/api/routes.py` + `test_codegen.py` |
| `setup.ts` | Exports `VPPO_BASE_URL` (and future `PRODUCT_BASE_URL` constants) | `playwright/utils/setup.ts` |

**Auth detection strategy for cross-domain (Type B) products**:
```typescript
// In loginHelper.mjs assumeUser — URL-based, no CSS selectors:
const isVppo = userProduct === 'vppo' || navigationUrl.includes('mytlc');
if (isVppo) {
    const onDashboard = currentUrl.includes('mytlc_logged') && !currentUrl.includes('login');
    // ✅ Confirmed authenticated — return
    // ❌ Not on dashboard — fall back to live login via ghost_login flow
}
```

**Canonical products using this pattern**: `vppo` (PHP app at `hotfixes.sandbox.internal.vcreative.net`), `vpromotions` (RC environment)

**Key files for this pattern**:
- `backend/config/products.yaml` — `playwright_base_url` + `ghost_login_environments` fields
- `playwright/fixtures/users/users.json` — `productUrl` field on cross-domain user entries
- `playwright/utils/generateStorageStates.mjs` — post-login navigation to `productUrl`
- `playwright/utils/loginHelper.mjs` — `assumeUser` URL-based auth detection branch
- `playwright/utils/setup.ts` — `VPPO_BASE_URL` export

## Anti-Patterns & Failure Modes

These patterns were identified through systematic reliability analysis of the vQA execution engine. They represent **proven architectural mistakes** that caused 0/10 benchmark completion. All new design work must explicitly avoid these.

### ❌ The Stateless LLM on Stateful SPA Anti-Pattern

**What it is**: Using a zero-shot LLM planner on a 1-second tick loop to navigate a highly stateful, animation-driven Angular/PrimeNG Single Page Application.

**Why it fails**: PrimeNG autocompletes and overlays are latency-heavy. The planner issues a `fill()` action, but before the network response renders the dropdown, the Verifier tick fires, sees no change, returns `NOT_YET`, and the Evaluator loop re-plans — forgetting it was waiting for a dropdown. The agent then scrolls to re-find the input and re-breaks it.

**Rule**: Real-time LLM DOM traversal is prohibited as the primary execution path on Angular/PrimeNG SPAs. Use deterministic Playwright `waitForSelector` + `expect(locator).toBeVisible()` chains first. LLM planning is only valid as a CV fallback after DOM exhaustion.

---

### ❌ The Visual Delta Trust Signal Anti-Pattern

**What it is**: Treating a change in DOM element count (`document.querySelectorAll('*').length`) or ARIA tree snapshot as confirmation that an action succeeded.

**Why it fails**: False positive rate is exceptionally high. A loading spinner rendering, a toast notification, or a cursor blink changes DOM count and ARIA tree. The Evaluator advances to the next step; that step expects a fully-loaded page, can't find its target, and hard-fails.

**See**: `backend/engine/verifier.py` lines 560–580 for the current implementation.

**Rule**: Visual delta (DOM count + ARIA diff) MUST NOT be used as the sole success signal. Use explicit deterministic state assertions:
```python
# ✅ Correct
await expect(page.locator('.p-autocomplete-panel')).to_be_visible()

# ❌ Wrong — high false-positive rate
dom_count_changed = new_count != old_count  # do not trust
```

---

### ❌ The Unproven Fallback Anti-Pattern

**What it is**: Proposing a fallback mechanism (e.g., "if recipe fails, LLM catches it") without first measuring the fallback's success rate on the target failure mode.

**Why it fails**: If the LLM fallback has a 0% success rate on PrimeNG components, proposing it as a "safety net" creates false confidence. When the recipe fails and the fallback fires, it is a guaranteed crash with extra steps, not self-healing. Real-time self-healing via zero-shot LLM on dynamic SPAs is a fundamentally broken premise.

**Rule**: Any fallback path proposed in a design doc MUST include: (1) the fallback's empirically measured success rate, or (2) an explicit `[UNMEASURED — estimated ~0%]` label if no data exists. The offline recovery path (halt → dump artifacts → offline coding agent rewrites recipe → runs unit tests → commits fix) is the only validated recovery pattern.

---

### ❌ The Compounding Pipeline Depth Anti-Pattern

**What it is**: Building a deep sequential pipeline (e.g., 4+ nodes per execution loop: Planner → Executor → Verifier → Evaluator) where every node transition involves full LangGraph state serialization and an LLM round-trip.

**Why it fails**: Over a 25-step run at 4 nodes per step, even a theoretical 95% per-node success rate produces `0.95^(4×25) = 0.28%` completion probability [THEORETICAL]. Real-world correlated failures (a corrupted DOM state at step 3 guarantees 100% failure at step 4) make the actual reliability worse than the naive Bernoulli model predicts.

**Rule**: Minimize live-loop nodes. The Verifier should be a synchronous Python function called *inside* the executor, not a separate LangGraph node. Target: **≤2 LangGraph nodes per execution loop** (Executor + Evaluator). Separate nodes are only justified for async operations or graph branching logic.

---

### ❌ The Implicit Backbone Coverage Anti-Pattern

**What it is**: Relying on end-to-end Playwright tests as the only coverage for a critical utility helper (e.g., `SearchHelper.ts`) that is promoted to the primary fast-path for execution.

**Why it fails**: When `SearchHelper.ts` breaks due to a PrimeNG component update, the failure manifests as a cryptic step-12 browser test failure rather than a clear signal pointing to the broken helper. Root cause analysis time is maximized; MTTR is maximized.

**Rule**: Any utility elevated to backbone/fast-path status MUST have a dedicated unit test suite with the following minimum contract:
1. Happy path execution
2. Already-open / idempotency guard
3. Catch block / fallback path
4. At least one PrimeNG-specific failure mode (e.g., overlay not visible, strict mode violation)
5. Timeout behavior

---

### ❌ The Borrowed Metric Anti-Pattern

**What it is**: An agent echoing a reliability figure supplied conversationally (e.g., "couldn't hit 10% reliability") without verifying it against actual benchmark or log data, then using that figure as the basis for an architectural recommendation.

**Why it fails**: The number may be wrong or directionally misleading. In the vQA case, the actual figure was `0/10 = 0%` — a qualitatively different failure mode than "struggling to reach 10%." Architectural recommendations built on a wrong baseline produce wrong pivot strategies.

**Rule**: All reliability claims in analysis, post-mortems, or design docs must cite their source:
- `[EMPIRICAL: benchmark_report.json, run 2026-06-03, 0/10]`
- `[EMPIRICAL: golden_10_results.json, run 2026-06-05, 51/221 = 23.1% AC-step pass rate, 0/10 cards]`
- `[EMPIRICAL: session-*.jsonl, Planner→Executor, 3/47 transitions]`
- `[THEORETICAL: assumed 95% per-node, no empirical data]`
- `[UNMEASURED: data not yet collected]`

Never use `[CONVERSATIONAL]` as a source for a metric in a design decision.

---

## Directory Structure Philosophy

```
backend/engine/    # LangGraph nodes — one file per node/concern
backend/browser/   # All Playwright infrastructure isolated here
backend/kb/        # All knowledge retrieval isolated here
backend/storage/   # All persistence isolated here (S3, run history)
backend/adapters/  # Pluggable test source adapters (Jira, GitHub, raw text)
knowledge/         # Human-readable KB files — edited by humans and synced to Bedrock
```

## Code Organization Patterns

- **Primary language**: TypeScript / Python
- **Default extensions**: `.ts`, `.tsx` (frontend), `.py` (backend)
- **Directory → extension map**:
  | Directory | Extension(s) |
  |-----------|-------------|
  | `frontend/src/components/` | `.tsx` |
  | `frontend/src/hooks/` | `.ts` |
  | `frontend/src/context/` | `.tsx` |
  | `frontend/src/auth/` | `.ts`, `.tsx` |
  | `backend/` | `.py` |
  | `backend/api/` | `.py` |
  | `backend/engine/` | `.py` |
  | `backend/jira/` | `.py` |
  | `backend/kb/` | `.py` |

## Testing Patterns

- **Framework**: pytest (backend), no frontend tests currently
- **Test location**: `tests/` directory, separate from source
- **Naming**: `test_*.py` convention
- **Scope emphasis**: Unit-heavy for KB matching logic; no integration tests against live browser/AWS
- **Benchmarking (Baseline Accuracy)**: 
  - `scripts/benchmark_pipeline.py` provides a quantitative baseline for AC parsing and E2E execution success.
  - Uses a "Golden 10" dataset (`tests/benchmarks/golden_10_data.json`) to track accuracy regressions.
  - Supports component-level success breakdown (dropdowns, calendars, etc.).
- **What is NOT tested**: LangGraph node execution end-to-end, Playwright interactions, AWS integrations (all require live environment)
- **Mocking approach**: Standard `unittest.mock` for external dependencies (Jira, Bedrock, Playwright).
- **Test-runtime artifacts (DO NOT STAGE)**: pytest regenerates several storage locations on every run. These MUST NOT be staged for commit — run `git restore memory/chroma_rag/ memory/selector_rag/ storage/learned_workflows.json` before any commit or commit guard. Recurring `_learned/` reflections show this is a per-phase friction point in multi-phase Level 3-4 builds.

## Workflow Execution Discipline

### Mandatory Step Compliance (`/vc-build`)

The `/vc-build` workflow defines Steps 0 through 11. **Every step must be executed — no exceptions.** This is a hard constraint enforced by agent rules and validated through execution state auditing.

| Anti-Pattern | Why It Fails |
|---|---|
| "This phase is trivial, skip code review" | Trivial changes contain the most insidious bugs because they bypass scrutiny |
| "Only metadata changed, skip docs" | Metadata errors cascade silently into downstream tooling and memory bank corruption |
| "Tests pass, so quality is fine" | Tests validate correctness, not code quality, security, or documentation completeness |
| "Sub-agent dispatch unavailable, skip step" | Unavailable dispatch ≠ optional step; execute inline instead |

### Inline Sub-Agent Fallback Rule

When the `/vc-build` workflow's prescribed sub-agent dispatch mechanism (Gemini CLI) is unavailable, the orchestrating agent **MUST** execute every sub-agent's full methodology inline. This means:

1. **Read** the agent's methodology file from `.agent/workflows/agents/`
2. **Execute** every step the methodology prescribes
3. **Log** the results to the task's Execution State identically to sub-agent output
4. **Iterate** on feedback loops (e.g., code review blocking issues → re-implement → re-review)

"Inline" is a dispatch strategy, not a permission to skip work.

### Execution State Audit Trail

Every step executed (including sub-agent steps performed inline) must appear in the `## Execution State` section of `tasks/[task_id].md`. A gap in step numbering (e.g., Step 7 → Step 10) is evidence of a skipped step and constitutes a workflow violation. The audit trail enables:

- **Crash recovery**: Resume from the last completed step
- **Quality assurance**: Verify all quality gates were passed
- **Post-mortem**: Trace where a defect was missed in the pipeline


## API Structure

| Endpoint | Method | Purpose |
|---|---|---|
| `/execute` | POST | Start single-ticket test run |
| `/execute-batch` | POST | Start batch test run |
| `/status/{run_id}` | GET | Poll run status + artifact URLs |
| `/batch-status/{batch_id}` | GET | Poll batch status |
| `/health` | GET | Liveness check (Bedrock, S3, Jira) |
| `/runs/{run_id}/interact` | POST | Inject mouse click during HITL |
| `/runs/{run_id}/human-takeover/done` | POST | Signal HITL completion |
| `/ws/{run_id}` | WS | Real-time execution log stream |

## Artifact Storage Layout (S3)

```
vcreative-deployments/vSuitePlatform/Buildartif/vqa-results/
├── screenshots/step-{N}-{action}-{timestamp}-{run_id_prefix}.png
├── videos/session-{run_id}-{timestamp}.webm
└── reports/audit-{ticket}-{role}-{timestamp}.html
```

<!-- AUTO-MANAGED: c4-architecture-start -->
## C4 Architecture

<!--
  This section is auto-managed by /vc-c4. Run /vc-c4 to refresh.
  Do not hand-edit between the AUTO-MANAGED markers — edits are overwritten.
-->

This project's architecture is documented at four progressively zoomed-in C4 levels:

| Level | Audience | Document |
|-------|----------|----------|
| 1. Context | Everyone | [memory-bank/c4/c4-context.md](./c4/c4-context.md) — system purpose, personas, externals |
| 2. Container (index) | Tech-aware stakeholders | [memory-bank/c4/c4-container.md](./c4/c4-container.md) — one-line-per-container index |
| 2. Container (diagram) | Tech-aware stakeholders | [memory-bank/c4/c4-container-relationships.md](./c4/c4-container-relationships.md) — system-wide topology + cross-container matrix |
| 2. Container (detail) | Developers | [memory-bank/c4/containers/](./c4/containers/) — per-container deep-dive (always-on) |
| 3. Component (index) | Developers | [memory-bank/c4/c4-component.md](./c4/c4-component.md) — components grouped by container |
| 3. Component (diagram) | Developers | [memory-bank/c4/c4-component-relationships.md](./c4/c4-component-relationships.md) — cross-component dependency graph |
| 3. Component (detail) | Developers | [memory-bank/c4/components/](./c4/components/) — per-component deep-dive |
| 4. Code | Developers maintaining specific code | [memory-bank/c4/code/](./c4/code/) — per-directory docs |

**Entry point**: [memory-bank/c4/c4-index.md](./c4/c4-index.md)

### How Agents Should Use the C4 Docs

- **Planning agents** (`/vc-plan`): read `c4-context.md` and `c4-container.md` to ground plans in the existing system shape. Drill into specific components only when the task affects them.
- **Coding Agent** (`/vc-build`): when introducing or modifying a component, read its `components/c4-component-<name>.md` first. Update the affected component doc as part of the build (or rerun `/vc-c4` after the build).
- **Test Writer**: use `c4-component.md` (the lean index) to find which component owns the code under test, then read its `components/c4-component-<name>.md` detail doc for interface signatures and integration points worth covering.
- **Reflection Agent**: cite C4 levels when reflecting on architectural drift ("This task added cross-container traffic not yet in c4-container.md").
- **UAT Walker**: use `c4-container.md` to identify which container's UI surface a journey is walking.

### Refresh Cadence

`/vc-c4` is idempotent. Re-run when:
- A new component, service, or container is introduced
- Deployment topology changes (split, merge, new datastore, new external integration)
- Before a major release that needs current architecture artifacts
- After significant refactors

It only re-walks subtrees whose source-directory hashes have changed.

**Last refreshed**: 2026-05-27
**Plugin version**: gemini-cli-4-6

<!-- AUTO-MANAGED: c4-architecture-end -->
\n## Knowledge Base Synchronization Cadence (vQA Rewrite)\n\nTo ensure the LLM's context window (Context Library) remains accurate, the BM25/RAG Knowledge Base must be synchronized with the codebase.\n\n- **Trigger:** Automated via GitHub Actions CI/CD pipeline on every merge to `main`.\n- **Mechanism:** A dedicated sync script (e.g., `scripts/sync_kb.py`) will parse all exported Playwright helper functions, component interfaces, and `data-vqa-id` mappings, and update the vector store/BM25 index.\n- **Fail-safe:** If the KB is detected to be > 48 hours out of sync with the `main` branch commit hash during a test generation run, the pipeline will issue a `STALE_CONTEXT` warning and halt generation.
