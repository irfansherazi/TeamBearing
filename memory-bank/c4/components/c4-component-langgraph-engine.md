# C4 Component: LangGraph Engine

## Component Metadata

- **Component Name**: langgraph-engine
- **Run ID**: c4-2026-05-08-001
- **Generated**: 2026-05-08T00:00:00Z
- **Agent**: c4-component (Sonnet)
- **Constituent Code Docs**:
  - `memory-bank/c4/code/c4-code-backend-engine.md`
  - `memory-bank/c4/code/c4-code-backend-engine-tools.md`
  - `memory-bank/c4/code/c4-code-backend-engine-workers.md`
- **Source Directories**: `backend/engine`, `backend/engine/tools`, `backend/engine/workers`
- **Language**: Python 3.10+ (async/await)

---

## Overview

The LangGraph Engine is the core domain component of vQA. It implements an autonomous QA testing orchestrator as a multi-stage, stateful `StateGraph` (LangGraph). Each test run traverses a deterministic sequence of named nodes — jira fetch, AC parse, role setup, login, plan, execute, verify, evaluate, (optional human takeover), and report — while a single shared `VQAState` TypedDict propagates all context and accumulated results through the graph.

The engine embeds a Supervisor-Worker architecture on top of the base graph: a `supervisor_node` classifies intents and routes to one of six specialized `*_worker_node` functions (generic, form, table, navigate, auth, verify) before delegating DOM-level execution back to the `planner_node`. Each worker injects domain-specific system-prompt rules into planner guidance rather than reimplementing planner logic, keeping the execution model coherent while providing targeted expertise.

---

## Purpose

Drive fully autonomous AC (acceptance criteria) validation across one or more user roles by:

1. Fetching and parsing Jira tickets into structured, step-by-step test plans.
2. Executing See-Think-Act-Judge-Verify loops against a live browser session.
3. Detecting and escalating failures via HITL (Human-In-The-Loop) recovery.
4. Learning from human interventions and persisting knowledge back to the knowledge base.
5. Synthesizing an HTML audit report (with video, screenshots, RBAC violations, and bug registry) as the final artifact.

---

## Software Features

### 1. AC Parsing and Test Plan Compilation
Two-stage LLM pipeline converts raw Jira AC text into a machine-executable `TestPlan`. Stage 1 (BDD Normalizer) produces clean Given/When/Then from free-form acceptance criteria. Stage 2 (JSON Compiler) compiles BDD text into a strict `TestPlan` Pydantic model with structured `StructuredACStep` entries and typed `Verification` assertions. Dual-writes maintain backward compatibility with the legacy `acceptance_criteria_steps` string list consumed by 13+ downstream callers.

### 2. Multimodal See-Think-Act Execution Loop
The planner node grounds every planning decision in a dual-modal context: a base64 screenshot plus a full ARIA accessibility tree. Claude 3.5 Sonnet (via AWS Bedrock) reasons over this context and returns a strict `PlannerAction` JSON (exposed as a Bedrock `tool_use` tool). The executor node translates the action into a Playwright dispatch from a ten-action dispatch table (click, fill, select_option, check/uncheck, navigate, wait, verify, scroll, press_key, recipe). Post-action screenshots are captured and uploaded to S3 for the audit trail.

### 3. Supervisor-Worker Specialization
A supervisor classifies each AC step intent and routes to one of six domain-specialized worker nodes. Workers inject targeted system-prompt rule blocks (`<FORM_INTERACTION_RULES>`, `<TABLE_NAVIGATION_RULES>`, `<AUTH_RULES>`, `<NAVIGATION_RULES>`, `<VERIFY_ONLY_RULES>`) into the planner guidance before delegation. The table worker additionally executes `scoped_click` and `table_search` macros directly (bypassing the planner for deterministic table operations), resolving STRICT_MODE violations and infinite-scroll failure modes specific to the PrimeNG + Angular vSuite interface.

### 4. Dual-Tier Programmatic Verification
After each action the verifier node applies a two-tier verification strategy. Tier 1 performs fast, deterministic DOM checks: URL substring/regex match, element visibility or hidden state, element state (disabled/enabled/checked), PrimeNG toast message wait, and `aria-sort` assertion for table sort verification. Only when Tier 1 is insufficient does Tier 2 invoke a Claude Haiku screenshot-based LLM check (sub-2s latency). The verifier returns one of three verdicts — `satisfied`, `not_yet`, or `failed` — which gate progress to the next AC step.

### 5. RBAC Validation and Evaluator Routing
The evaluator node inspects action results, applies RBAC cross-checks against `role_context.permissions`, and logs any violations to `bug_log`. It then applies a six-way decision matrix to route the graph: self-heal retry to planner (failure #1), human takeover (failure #2+), fatal reporter route (failure #10+), advance to next AC step, advance to next role, or completion. RBAC violations are captured as first-class audit events in the final report.

### 6. Human-In-The-Loop (HITL) Recovery and Learning
When the evaluator routes to `human_takeover_node` after 2+ consecutive failures, the graph pauses and broadcasts the current screenshot plus AC step context over WebSocket to the operator UI. The user clicks directly on the screenshot (mouse injection via `POST /runs/{run_id}/interact`), then confirms via `POST /runs/{run_id}/human-takeover/done`. The node writes the learned action to the long-term knowledge base (`knowledge/blueprints/` and `human_guidance.md`), resets `retry_count`, and returns control to the planner. Every HITL event is a learning signal that improves future autonomous runs.

### 7. HTML Audit Report Generation
The reporter node synthesizes the full `detailed_execution_log` into a structured HTML audit report containing: header metadata (ticket ID, role, status, timestamp), embedded `.webm` session video (S3 URL), AC step pass/fail/skip table, step-by-step screenshot gallery with LLM reasoning, bug registry (`[UI]`, `[LOGIC]`, `[API]`, `[QA]`, `[MEM]` categories), RBAC violation log, UX friction log, and run metadata (duration, iterations, cost). The browser session is closed before upload to finalize the `.webm` recording, and both artifacts are uploaded to S3.

---

## Code Elements

### Source Directory: `backend/engine` (31 files, 26,324 LOC)

**LangGraph Node Functions (Primary Graph Nodes):**

| Node Function | Module | Role in Graph |
|---|---|---|
| `planner_node(state) → dict` | `planner.py` | SEE-THINK: multimodal prompt → `PlannerAction` |
| `executor_node(state) → dict` | `executor.py` | ACT: Playwright dispatch → `ExecutionStep` |
| `step_verifier_node(state) → dict` | `verifier.py` | VERIFY: DOM checks + LLM fallback |
| `evaluator_node(state) → dict` | `evaluator.py` | JUDGE: RBAC + routing decision |
| `human_takeover_node(state) → dict` | `human_takeover.py` | HITL recovery + KB learning |
| `reporter_node(state) → dict` | `reporter.py` | Synthesize audit report + S3 upload |
| `jira_fetch_node` | `graph.py` (inline) | Fetch Jira ticket into `state.jira_ticket` |
| `ac_parser_node` | `ac_parser.py` | Two-stage AC → `TestPlan` compiler |
| `setup_role_node` | `graph.py` (inline) | Load `RoleContext` from KB or env vars |
| `login_node` | `graph.py` (inline) | Playwright login + JWT verification |

**Conditional Edge (Routing) Functions:**

| Function | Module | Returns |
|---|---|---|
| `route_after_evaluator(state) → str` | `evaluator.py` | `"planner"` \| `"human_takeover"` \| `"setup_role"` \| `"reporter"` |
| `route_after_verifier(state) → str` | `verifier.py` | `"evaluator"` \| `"planner"` |

**Graph Assembly:**

| Function | Module | Purpose |
|---|---|---|
| `build_graph() → StateGraph` | `graph_orchestrator.py` | Assemble full LangGraph with all nodes + conditional edges |

**Core State Types (`backend/engine/state.py`):**

| Type | Kind | Key Fields |
|---|---|---|
| `VQAState` | TypedDict (graph contract) | `jira_ticket`, `role_context`, `current_screenshot_b64`, `current_accessibility_tree`, `planned_action`, `detailed_execution_log` (append-only), `screenshots` (append-only), `bug_log`, `test_plan`, `page_state`, `retry_count`, `ac_step_index`, `last_error`, `s3_report_url`, `s3_video_url` |
| `ExecutionStep` | TypedDict (audit entry) | `step_index`, `ac_step_index`, `timestamp`, `action_type`, `action_payload`, `locator_strategy`, `locator_value`, `screenshot_url`, `success`, `error_message`, `self_heal_attempt`, `llm_reasoning`, `llm_observation`, `llm_thought` |
| `RoleContext` | TypedDict | `role_name`, `role_key`, `login_email`, `login_password`, `permissions`, `constraints` |
| `JiraTicketContext` | TypedDict | `ticket_id`, `summary`, `description`, `acceptance_criteria_steps`, `issue_type` |

**Schema / Validation (`backend/engine/schemas.py`):**

| Type | Kind | Purpose |
|---|---|---|
| `TestPlan` | Pydantic | Compiled test plan (steps, preconditions, target_components) |
| `StructuredACStep` | Pydantic | One step in TestPlan (goal, preconditions, actions, verifications) |
| `Verification` | Pydantic | Typed assertion (element_visible, url_check, toast_message, table_sort, etc.) |
| `PlannerAction` | Pydantic | Strict Bedrock tool_use contract from planner (action, strategy, role, name, value, reasoning, recipe_name, recipe_params) |

**Supporting Modules:**

| Module | Purpose |
|---|---|
| `prompts.py` | System prompt templates (BDD_NORMALIZER, JSON_COMPILER, per-category rule blocks) |
| `roles.py` | `get_role_context()`, `resolve_credentials()` — KB-primary / env-fallback |
| `kb_client.py` | Bedrock Knowledge Base queries (`fetch_all_role_credentials`, `query_kb`) |
| `recipe_runner.py` | YAML-driven atomic recipe execution (`execute_recipe`, `fill_recipe`) |
| `state_tracker.py` | `PageStateTracker` — <15ms ground-truth DOM state snapshot |
| `failure_analyzer.py` | Post-mortem classification: `product_bug` vs. `agent_issue` |
| `validators.py` | `validate_ac_steps()`, `validate_planned_action()` |
| `metrics.py` | `RunMetrics` — per-run LLM usage, cost, timing |
| `step_classifier.py` | Rule-based AC step type + PrimeNG component detection |
| `auth_manager.py` | JWT + session management |
| `fixture_manager.py` | Test asset fixture registry for file uploads |
| `scheduler.py` | Execution scheduling/queueing |
| `supervisor.py` | Higher-order Supervisor-Worker orchestration |
| `webhooks.py` | External webhook integrations |

---

### Source Directory: `backend/engine/tools` (3 files)

Specialized Playwright interaction macros for the Angular + PrimeNG vSuite interface.

| Function | Module | Purpose |
|---|---|---|
| `execute_scoped_click(page, scope_text, target_text, ...) → dict` | `scoped_action.py` | Click an element scoped to a container row — resolves STRICT_MODE violations from duplicate button text across table rows |
| `execute_scoped_fill(page, scope_text, target_label, fill_value, ...) → dict` | `scoped_action.py` | Fill an ARIA-labelled input scoped to a container row |
| `execute_table_search(page, search_query, ...) → dict` | `table_search.py` | Trigger PrimeNG/vSuite table filter and wait for re-render — prevents infinite-scroll loops |
| `clear_table_search(page, ...) → dict` | `table_search.py` | Clear table filter and restore unfiltered state |

All tool functions return `dict[str, Any]` with consistent `{success: bool, error: str, ...context}` contract designed to provide LLM-friendly error messages for retry guidance.

---

### Source Directory: `backend/engine/workers` (8 files)

Supervisor-Worker specialized node functions dispatched by the supervisor based on intent classification.

| Worker Node | Module | Specialization |
|---|---|---|
| `generic_worker_node(state) → dict` | `generic_worker.py` | Fallback; reads SupervisorIntent and delegates to planner |
| `form_worker_node(state) → dict` | `form_worker.py` | Form filling, dropdowns, date pickers; injects `<FORM_INTERACTION_RULES>` |
| `table_worker_node(state) → dict` | `table_worker.py` | Table navigation, pagination, sorting; executes scoped_click / table_search directly |
| `navigate_worker_node(state) → dict` | `navigate_worker.py` | URL navigation, sidebar transitions; injects `<NAVIGATION_RULES>` |
| `auth_worker_node(state) → dict` | `auth_worker.py` | Login, logout, role switching; direct `auth_manager` delegation + planner fallback |
| `verify_worker_node(state) → dict` | `verify_worker.py` | Read-only verification; injects `<VERIFY_ONLY_RULES>`, no DOM mutation |

**Worker Registry:**

| Function | Module | Purpose |
|---|---|---|
| `get_worker_node(worker_type: str) → Callable` | `workers/__init__.py` | Resolve worker function by type; falls back to `generic_worker_node` |

**Variable Extraction:**

| Function | Module | Purpose |
|---|---|---|
| `extract_and_store_variable(page, variable_name, extraction_strategy, selector_or_pattern) → dict` | `variable_extractor.py` | Scrape dynamic value from live DOM (css_selector / text_pattern / aria_label); no LLM call |

---

## Interfaces

### Primary Interface: LangGraph StateGraph API

The engine is assembled by `build_graph()` in `graph_orchestrator.py` and exposed as a compiled LangGraph `StateGraph`. Callers invoke it via LangGraph's async streaming API.

```python
# Assembly
graph: CompiledGraph = build_graph()

# Invocation (from backend API layer)
result: VQAState = await graph.ainvoke(
    initial_state,          # VQAState TypedDict
    config={"run_id": str}  # LangGraph run config
)
```

**Initial state required fields:**
- `run_id: str` — unique run identifier
- `jira_ticket_id: str` — Jira ticket to test
- `roles: list[str]` — role keys to iterate

**Terminal state output fields:**
- `s3_report_url: str` — HTML audit report S3 URL
- `s3_video_url: str` — session recording S3 URL
- `bug_log: list[dict]` — classified bugs found during run
- `detailed_execution_log: list[ExecutionStep]` — full action trace

### HITL Interaction Interface

The human takeover node exposes two in-process callbacks injected from the API routing layer:

```python
# Inject WS broadcaster from routes.py at startup
set_ws_broadcaster(fn: Callable[[str, dict], Awaitable[None]]) -> None

# Resume after human completes interaction (called from POST /runs/{run_id}/human-takeover/done)
await complete_takeover(run_id: str, data: dict) -> None

# Persist human guidance to KB (called internally after takeover)
await persist_user_guidance(guidance_text: str, ac_step: str, ticket_id: str) -> None
```

### Worker Dispatch Interface

```python
from backend.engine.workers import get_worker_node

worker_fn: Callable = get_worker_node(worker_type="form")
result: dict = await worker_fn(state)
```

### Node Function Contract

Every LangGraph node function follows the same contract:

```python
async def <node_name>_node(state: VQAState) -> dict:
    """Returns a partial VQAState dict; LangGraph merges it back."""
    ...
    return {
        "field_to_update": new_value,
        # Annotated[list, operator.add] fields: return list to append
        "detailed_execution_log": [new_step],
        "screenshots": [new_s3_url],
    }
```

State merging semantics:
- Scalar fields: last-write wins
- `Annotated[list[T], operator.add]` fields (`detailed_execution_log`, `screenshots`, `bug_log`, `ac_steps_completed`): append-only, immutable history

---

## Dependencies

### Internal Components Used

| Component / Subsystem | Interface Used | Purpose |
|---|---|---|
| `browser-automation` (`backend/browser/`) | `capture_screenshot_b64()`, `extract_accessibility_tree()`, `BrowserManager.get_page()`, `wait_for_spinners_cleared()`, `wait_for_data_settled()` | Screenshot capture, ARIA tree extraction, Playwright Page registry, network/spinner sync |
| `knowledge-base` (`backend/kb/`) | `KBLoader` (TF-IDF RAG), `PlaywrightRAG.query()`, `SelectorRegistry.query()`, `UnifiedRegistry`, `TestMatcher`, `ComponentRegistry`, `build_global_context()` | RAG-driven planning fallback, selector hints, AC parser KB context |
| `jira-adapter` (`backend/jira/`) | `fetch_ticket_context()`, `post_jira_comment()` | Fetch ticket at run start; post completion comment |
| `storage` (`backend/storage/`) | `upload_report()`, `upload_video()`, `upload_screenshot()` | S3 artifact persistence |
| `persistent-memory` (`backend/memory/`) | `PersistentMemory.append()`, `SkillLibrary.query()` | HITL learning write-back; optional skill retrieval |
| `llm-provider` (`backend/llm.py`, `backend/config.py`) | `get_llm(model_id)`, `Settings` singleton | Bedrock model selection (Claude 3.5 Sonnet for planning; Haiku for verification/parsing) |
| `profiles` (`backend/profiles.py`) | `get_active_profile() → AppProfile` | Role definitions for active application |

### External Systems

| Library / Service | Version Constraint | Purpose |
|---|---|---|
| `langgraph` | `>=0.1.0` | StateGraph construction, node registration, conditional edges, `ainvoke()` / `astream()` |
| `langchain_aws` | `>=0.1.0` | `ChatBedrockConverse` — Claude invocation via AWS Bedrock |
| `langchain_core` | — | `HumanMessage`, `SystemMessage`, `ToolMessage` types |
| `playwright.async_api` | — | `Page`, `Browser`, `BrowserContext`, `TimeoutError` — live browser automation |
| `pydantic` | — | `BaseModel`, `Field`, validators — schema enforcement for `TestPlan`, `PlannerAction` |
| `boto3` | `>=1.26.0` | S3 artifact upload; Bedrock Agent Runtime for KB queries |
| `botocore` | — | AWS SDK config |
| `asyncio` | stdlib | `Event`, `Queue`, `gather` — HITL pause/resume coordination |
| `json` | stdlib | JSON parsing/serialization for LLM outputs |
| `logging` | stdlib | Structured diagnostic logging |
| `re` | stdlib | Regex for text extraction and error classification |

---

## Architecture Diagram

```mermaid
C4Component
    title LangGraph Engine — Component View

    Container(vqa_backend, "vQA Backend", "Python / FastAPI", "REST + WebSocket API layer") {

        Component(engine, "LangGraph Engine", "Python / LangGraph StateGraph", "Autonomous QA state machine: AC parsing, See-Think-Act-Verify loop, HITL recovery, audit reporting")

        Component(supervisor, "Supervisor / Workers", "Python / async", "Intent classifier + 6 domain-specialized worker nodes (form, table, navigate, auth, verify, generic)")

        Component(tools, "Engine Tools", "Python / Playwright", "Deterministic macro tools: scoped_click, scoped_fill, table_search, clear_table_search (PrimeNG-specific)")

        Rel(engine, supervisor, "Routes intents to worker nodes", "in-process")
        Rel(supervisor, engine, "Delegates to planner_node for DOM execution", "in-process")
        Rel(supervisor, tools, "Calls scoped_click / table_search macros", "in-process")
    }

    Container(browser_automation, "Browser Automation", "Python / Playwright", "Screenshot capture, accessibility tree, BrowserManager, network sync")
    Container(knowledge_base, "Knowledge Base", "Python / TF-IDF + Bedrock KB", "RAG: Playwright KB, selector registry, skill library, component registry")
    Container(storage, "Storage", "AWS S3", "Screenshots, session video, HTML report artifacts")
    Container(persistent_memory, "Persistent Memory", "Python / file system", "HITL learned blueprints, human_guidance.md")

    System_Ext(bedrock, "AWS Bedrock", "Claude 3.5 Sonnet (planning), Claude Haiku (verification, parsing)")
    System_Ext(jira, "Jira", "Ticket fetch + completion comment")

    Rel(engine, browser_automation, "Reads screenshots + a11y tree; dispatches Playwright actions", "async in-process")
    Rel(engine, knowledge_base, "RAG queries for unknown UI patterns; AC parser KB context", "async in-process")
    Rel(engine, storage, "Uploads screenshots, video, report", "AWS SDK / boto3")
    Rel(engine, persistent_memory, "Writes HITL learned actions", "async file I/O")
    Rel(engine, bedrock, "LLM inference: planning, verification, AC parsing", "HTTPS / langchain_aws")
    Rel(engine, jira, "Fetch ticket; post completion comment", "HTTPS / REST")
    Rel(tools, browser_automation, "wait_for_spinners_cleared, wait_for_data_settled", "async in-process")
```

---

## Architecture Patterns

### See-Think-Act-Judge-Verify Loop
The fundamental execution model is a stateful, deterministic loop:
1. **SEE** (`planner_node`): Screenshot + ARIA tree capture
2. **THINK** (`planner_node`): Multimodal LLM reasoning → `PlannerAction`
3. **ACT** (`executor_node`): Playwright dispatch
4. **JUDGE** (`evaluator_node`): RBAC check + routing
5. **VERIFY** (`step_verifier_node`): DOM-programmatic + LLM fallback assertion
6. **REPEAT or REPORT**: Loop for next step, or finalize

### Supervisor-Worker Delegation
`supervisor_node` classifies intent (form / table / navigate / auth / verify / generic), routes to the appropriate worker, which injects domain-specific rules into planner guidance and delegates back. Workers never reimplement planner logic — they only narrow the context. The table worker additionally short-circuits to deterministic macro tools (`scoped_click`, `table_search`) when the planned action type requires them.

### Append-Only State Merging (Reduce-on-Append)
`Annotated[list[T], operator.add]` fields in `VQAState` produce an immutable execution history. Nodes return partial dicts with list fields to append; LangGraph merges via `operator.add`. No node can overwrite a prior step's audit entry.

### Recipe System (Action Compounding)
Multi-step PrimeNG interactions (e.g., "open dropdown → wait → click option") are expressed as YAML recipes. The planner emits `action="recipe"`; the executor runs all sub-steps atomically without verifier interruption. Eliminates oscillation failures from intermediate state checks.

### Conditional Rule Injection (14 Rule Categories)
Instead of a monolithic 240-line system prompt, the planner assembles a targeted context by injecting only the relevant rule categories per AC step (TABLE_SORTING_RULES, MODAL_RULES, DROPDOWN_RULES, RECIPE_RULES, etc.), reducing token usage and improving planning coherence.

### Dual-Tier Verification (Fast-Path + LLM Fallback)
Tier 1 programmatic DOM checks (URL, element state, toast, aria-sort) are attempted first. Claude Haiku screenshot verification only fires when Tier 1 is insufficient. Keeps average verification latency well below 2 seconds.

### HITL as Learning Signal
Every human takeover is a knowledge-base write event. The system learns locator patterns, workflow sequences, and edge-case guidance from operator corrections, improving autonomous coverage over time.

---

## Notes for Higher-Level Synthesis

**Container placement**: The LangGraph Engine belongs entirely within the **vQA Backend** container. It has no direct external network exposure — all external I/O (Bedrock, Jira, S3) is routed through dedicated subsystem modules (`backend/llm.py`, `backend/jira/`, `backend/storage/`).

**Key component relationships for container-level diagram**:
- Engine → Browser Automation: tight coupling (same process, async in-process calls)
- Engine → Knowledge Base: async in-process RAG queries
- Engine → Storage: async S3 uploads via `boto3`
- Engine → Persistent Memory: async file I/O for HITL write-back
- Engine → Bedrock (external): HTTPS via `langchain_aws` / `ChatBedrockConverse`
- Engine → Jira (external): HTTPS via `backend/jira/client.py`

**Boundary notes**:
- The engine does NOT directly control the WebSocket connection; it receives an injected `ws_broadcaster` callback from the API routing layer (`routes.py`), keeping transport concerns out of the state machine.
- The `variable_extractor` in workers provides deterministic token interpolation (angle-bracket dynamic values) for the supervisor without requiring LLM inference.
- The `failure_analyzer` module performs post-mortem classification (`product_bug` vs. `agent_issue`) as a diagnostic overlay — it does not affect graph routing.
- Recipe atomicity (no verifier breakpoints mid-recipe) is the primary mechanism for preventing oscillation loops in compound PrimeNG interactions.

**Downstream consumers of `VQAState`**:
The state schema (`VQAState`, `TestPlan`, `ExecutionStep`) is the integration contract for the entire backend. 13+ modules consume `acceptance_criteria_steps`; any schema change must maintain dual-write backward compatibility.
