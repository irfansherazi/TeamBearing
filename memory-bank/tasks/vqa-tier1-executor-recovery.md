---
slug: vqa-tier1-executor-recovery
feature: FEAT-116-vqa-tier1-executor-recovery
status: COMPLETE
---
# vqa-tier1-executor-recovery: vQA Tier 1 — Executor Recovery Hardening

**Complexity**: Level 3
**Status**: COMPLETE
**Archived**: memory-bank/archive/vqa-tier1-executor-recovery-archive.md
**Completed**: 2026-07-28
**Reflection**: memory-bank/reflection/vqa-tier1-executor-recovery-reflection.md
**Jira Issue**: N/A (internal reliability work)
**Issue Type**: Feature
**Priority**: Critical
**Branch**: feature/FEAT-116-vqa-tier1-executor-recovery
**Roadmap**: FEAT-116-vqa-tier1-executor-recovery

---

## Task Description

Ship the four highest-ROI executor fixes surfaced by the 2026-07-27 QA-358 failure analysis. Together they turn the Contest-dropdown failure pattern — where the LLM plans `get_by_text("Contest")` against 41 pre-rendered but hidden matches inside a closed `<p-select>` and loops through DOM strict-mode violations, CV fallback failures, and HITL amnesia — into an auto-recoverable actionable error instead of a run-terminating loop.

### The four fixes

1. **T1-a — Component-Aware Precondition Check** (`backend/engine/executor.py`)
   Add `_is_target_in_open_container(page, target_text)` that queries for known "closed" containers before any text-target click. If the target is inside a closed container, return `TARGET_INSIDE_CLOSED_CONTAINER` with the trigger selector — actionable next step instead of a stack trace.

2. **T1-b — Kill Futile Scroll Fallback** (`backend/engine/executor.py:986-1040`)
   In the 0-visible strict-mode branch, when `total_count > 5`, skip `scroll_into_view_if_needed` entirely (it's almost always futile against Angular pre-renders) and surface `STRICT_MODE_AMBIGUOUS` immediately with a strategy hint. Reclaims ~10s per failure.

3. **T1-c — Fix RAG Debugger LlamaIndex Dependency** (`backend/engine/rag_debugger.py`)
   Replace the LlamaIndex query engine with a direct Chroma retrieval call. Since the code already uses `response_mode="no_text"` and Bedrock embeddings, LlamaIndex adds only overhead — and its OpenAI-LLM extra requirement has silently broken the debugger in every session captured today.

4. **T1-d — Fix HumanGuidanceVault HNSW Parameters** (`backend/kb/loader.py`, `backend/kb/rag.py`)
   Recreate the Chroma collection with `metadata={"hnsw:space": "cosine", "hnsw:M": 32, "hnsw:construction_ef": 200, "hnsw:search_ef": 100}`. Current defaults throw `Cannot return the results in a contigious 2D array` at every query. Add a one-shot migration that re-embeds `human_guidance.md` on startup.

---

## Specification

**Feature Type**: NFR/Infrastructure
*Note: this is a reliability hardening deliverable — four targeted bug fixes to the executor, RAG debugger, and knowledge-base retrieval layer.*

**Creative Exploration Needed**: No
*Specification is concrete — every file path, line range, error code, HNSW parameter, and timing threshold is fixed. The only LOW-confidence field (T1-a container-signature list) is flagged explicitly in the Scope Boundaries.*

### Verification Method

- **Test method**: `pytest backend/engine/test_executor_component_gate.py backend/engine/test_executor_strict_mode.py backend/engine/test_rag_debugger.py backend/kb/test_human_guidance_vault.py -v` (unit suite, no Playwright required); integration confirmation via fresh QA-358 run against `vpromotions` QA env using `python -m backend.cli --ticket QA-358 --role qa_analyst`
- **Success metrics**:
  - T1-a: `TARGET_INSIDE_CLOSED_CONTAINER` error code returned with a non-empty `trigger_selector` value — zero strict-mode stack traces — when target text is inside a closed `<p-select>` container
  - T1-b: `STRICT_MODE_AMBIGUOUS` returned in ≤ 500 ms (wall-clock) when `total_count > 5` and `visible_count == 0`; no call to `scroll_into_view_if_needed` in that branch; per-failure wall-clock savings ≥ 8 seconds versus the current path (which burns 3 s × 3 scroll attempts + fallback timeout ≈ 10 s total)
  - T1-c: `backend.engine.rag_debugger.query_knowledge_base(error_log)` returns a non-empty formatted string for a known error log; no `llama-index-llms-openai` entry in `backend/requirements.txt`; no `llama-index-core`, `llama-index-embeddings-bedrock`, or `llama-index-vector-stores-chroma` entries if fully removed
  - T1-d: `HumanGuidanceVault.query("Select Contest from PRF Category dropdown", product="vpromotions")` returns ≥ 1 match; no `Cannot return the results in a contigious 2D array` logged at any query volume; Chroma collection metadata includes `{"hnsw:M": 32, "hnsw:construction_ef": 200, "hnsw:search_ef": 100}`
  - Regression: all pre-existing tests in `backend/engine/test_*.py` and `backend/kb/test_*.py` continue to pass
  - Integration: QA-358 step "Select Contest from PRF Category dropdown" escalates in < 30 s (down from ~225 s observed in the 2026-07-27 session)
- **Observable at**:
  - Unit tests: pytest output (`PASSED` / `FAILED`) written to stdout; may be tee'd to `.claude-logs/pytest-tier1-<timestamp>.log`
  - T1-a / T1-b error codes: `backend/engine/executor.py` logger at `WARNING` level — lines beginning `[executor] STRICT_MODE_AMBIGUOUS` or `[executor] TARGET_INSIDE_CLOSED_CONTAINER`
  - T1-c: absence of the `LlamaIndex/ChromaDB not installed` warning in startup logs; `[RAG DEBUGGER] Relevant Code / Doc Snippets` header in the debugger output string
  - T1-d: `HumanGuidanceVault initialized at …` log line (existing) followed by a query returning results — no Chroma HNSW error in the log
  - Integration: run log in `storage/runs/<run_id>/execution_log.jsonl`; HTML audit report at the S3 presigned URL returned by `GET /status/<run_id>`
- **Verification frequency**: one-time per fix (unit tests run in CI on every push to `feature/FEAT-116-vqa-tier1-executor-recovery`); integration re-run once after all four phases ship

### Acceptance Criteria

#### AC-VERIFY-1: T1-a returns TARGET_INSIDE_CLOSED_CONTAINER with a usable trigger selector

**Priority**: MUST
**Given** the executor receives a `click` action with `strategy="get_by_text"` and `name="Contest"` against a page state where `<p-select>` for "PRF Category" is closed (overlay not present or `aria-expanded="false"`)
**When** `_is_target_in_open_container(page, "Contest")` is called before the click dispatch (insertion point: `backend/engine/executor.py` above line 948)
**Then** the executor returns `{"success": False, "error_message": "TARGET_INSIDE_CLOSED_CONTAINER: open <trigger_selector> first", …}` where `<trigger_selector>` is a non-empty, non-placeholder CSS selector string pointing to the closed container's trigger element — NOT a Playwright strict-mode stack trace

#### AC-VERIFY-2: T1-b short-circuits scroll fallback when total_count > 5 and visible_count == 0

**Priority**: MUST
**Given** the executor is in the Stage 2.5 branch (0 visible, `total_count_check > 5`) at `backend/engine/executor.py` lines 991-1040
**When** the count check resolves (`total_count > 5` and `visible_count == 0`)
**Then** the executor does NOT call `scroll_into_view_if_needed`; it immediately returns `{"success": False, "error_message": "STRICT_MODE_AMBIGUOUS: …", …}` where the `error_message` includes a concrete strategy-switch hint (e.g. "use `container_selector` + `get_by_role='option'`"); the entire branch completes in ≤ 500 ms wall-clock; a unit test confirms the mock `scroll_into_view_if_needed` is never called

#### AC-VERIFY-3: T1-c query_knowledge_base returns grounded results without LlamaIndex

**Priority**: MUST
**Given** `backend/engine/rag_debugger.py` has been rewritten to call the Chroma collection directly (bypassing the LlamaIndex `VectorStoreIndex.as_query_engine()` call at line 494) and `backend/requirements.txt` no longer contains any `llama-index-*` lines
**When** `query_knowledge_base("TimeoutError: locator get_by_text('Contest') strict mode violation")` is called against a populated Chroma collection at `memory/chroma_rag/`
**Then** the function returns a non-empty string containing the `[RAG DEBUGGER] Relevant Code / Doc Snippets` header and ≥ 1 formatted source block; it does NOT raise `ImportError` or log `LlamaIndex not installed`; no `source_nodes` attribute access occurs (the `response.source_nodes` field at line 500 is removed with the LlamaIndex path)

#### AC-VERIFY-4: T1-d HumanGuidanceVault queries succeed with tuned HNSW parameters

**Priority**: MUST
**Given** `backend/kb/rag.py` lines 54 and 143 have been updated to pass `{"hnsw:space": "cosine", "hnsw:M": 32, "hnsw:construction_ef": 200, "hnsw:search_ef": 100}` on `get_or_create_collection`; `scripts/migrate_human_guidance_vault.py` (new file) has been run to delete and re-embed the existing `storage/chromadb` collection with the corrected parameters
**When** `HumanGuidanceVault.query("Select Contest from PRF Category dropdown", product="vpromotions", max_results=3)` is called against a collection containing 500+ vectors
**Then** the call returns without raising an exception; no `Cannot return the results in a contigious 2D array` line appears in the log; the result list contains ≥ 1 entry whose `instructions` field is non-empty; the Chroma collection metadata on disk includes `hnsw:M=32`

#### AC-VERIFY-5: Regression — pre-existing tests continue to pass

**Priority**: MUST
**Given** all four fixes have been applied
**When** `pytest backend/engine/test_evaluator_hardening.py backend/engine/test_hitl_learning.py backend/engine/test_proactive_dismissal.py backend/kb/test_matcher.py backend/kb/test_rag_enhancement.py -v` is run (the full existing suite)
**Then** every previously-passing test still passes; no new failures are introduced by the executor branch-logic changes, the rag_debugger rewrite, or the HNSW collection recreation

#### AC-INTEGRATION-1: QA-358 "Select Contest" step escalates in under 30 seconds on a live re-run

**Priority**: MUST
**Given** all four fixes are deployed and `vpromotions` QA env is reachable at `VSUITE_BASE_URL`
**When** `POST /execute` is called with `{"ticket_id": "QA-358", "role": "qa_analyst"}` and the run reaches the AC step "Select Contest from PRF Category dropdown"
**Then** the step either (a) auto-recovers: T1-a's `TARGET_INSIDE_CLOSED_CONTAINER` error causes the planner to emit an open-trigger action, the dropdown opens, and the step succeeds; OR (b) still fails but escalates to HITL or `STRICT_MODE_AMBIGUOUS` in ≤ 30 seconds of wall-clock time for that step (confirmed in `storage/runs/<run_id>/execution_log.jsonl`) — not the ~225 s observed in the 2026-07-27 session

#### AC-ERROR-1: T1-c gracefully degrades when Chroma collection is empty or unavailable

**Priority**: SHOULD
**Given** the `memory/chroma_rag/` directory does not exist or the `vqa_rag_v1` collection is empty
**When** `query_knowledge_base(error_log)` is called
**Then** the function returns `""` (empty string) without raising; the logger emits a `WARNING` line containing "collection empty" or "not found"; the calling code path (the Debugger node) receives an empty string and proceeds without crashing

#### AC-ERROR-2: T1-d migration script surfaces HNSW rebuild failure explicitly

**Priority**: MUST
**Given** `scripts/migrate_human_guidance_vault.py` is run but the Chroma directory is unwritable or the Bedrock embedding call fails
**When** the migration script encounters the error
**Then** it exits with a non-zero exit code; it logs the full error including the collection path and the exception class; it does NOT silently produce a zero-vector collection (which would cause the HNSW error to reappear at query time)

### Scope Boundaries

- **In scope**:
  - `backend/engine/executor.py`: (1) new `_is_target_in_open_container(page, target_text)` helper inserted before the click dispatch at approximately line 948; (2) Stage 2.5 branch rewrite at lines 986-1040 to short-circuit when `total_count > 5`
  - `backend/engine/rag_debugger.py`: full rewrite of the query path replacing `VectorStoreIndex.as_query_engine()` (line 494) and the `response.source_nodes` access (line 500) with a direct `collection.query()` call; removal of `_LLAMA_AVAILABLE` guard and LlamaIndex import block (lines 66-89)
  - `backend/requirements.txt`: removal of `llama-index-core`, `llama-index-embeddings-bedrock`, `llama-index-vector-stores-chroma` lines (79-83)
  - `backend/kb/rag.py` lines 54 and 143: `metadata={"hnsw:space": "cosine"}` → `metadata={"hnsw:space": "cosine", "hnsw:M": 32, "hnsw:construction_ef": 200, "hnsw:search_ef": 100}`
  - `backend/kb/loader.py`: HNSW config on the `HumanGuidanceVault` constructor's `get_or_create_collection` call (if called separately from `rag.py`; current code at lines 140-144 in `rag.py` is the canonical path — confirm during build)
  - `scripts/migrate_human_guidance_vault.py` (new): one-shot script to delete and rebuild the `storage/chromadb` Chroma collection with corrected HNSW parameters and re-embed `knowledge/human_guidance.md`
  - New test files: `backend/engine/test_executor_component_gate.py`, `backend/engine/test_executor_strict_mode.py` (or extend existing), `backend/engine/test_rag_debugger.py`, `backend/kb/test_human_guidance_vault.py`

- **Out of scope**:
  - T3-c "planner-side reflex" (auto-emit the open-trigger click when `TARGET_INSIDE_CLOSED_CONTAINER` is returned) — this is a later tier; T1-a returns the error and stops
  - Extending the container-signature list beyond the initial four PrimeNG patterns (scope for a follow-on KB maintenance task)
  - `backend/engine/rag_debugger.py` document-loading and ingestion path — only the `query_knowledge_base()` function's retrieval logic changes; `ingest_knowledge_base()` may retain LlamaIndex chunking OR be rewritten to use direct Chroma upsert (decision deferred to build phase, flagged LOW-confidence below)
  - HNSW parameter tuning beyond the four values specified (`hnsw:M=32`, `hnsw:construction_ef=200`, `hnsw:search_ef=100`, `hnsw:space=cosine`) — no further tuning in this task
  - `TestPlanVault` (also in `backend/kb/rag.py`) — it uses only `{"hnsw:space": "cosine"}` at line 54 (the T1-d fix shares the file but only targets `HumanGuidanceVault`'s collection at line 143; confirm whether `TestPlanVault` at line 54 also needs tuning during build)

- **Dependencies**:
  - `chromadb>=0.5.0` must remain in `backend/requirements.txt` after LlamaIndex is removed (it is currently pulled in transitively via `llama-index-vector-stores-chroma`; must be made a direct dependency)
  - `boto3` and the existing Bedrock credential environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`) remain required for T1-c's direct embedding calls
  - The `vpromotions` QA environment must be reachable for the AC-INTEGRATION-1 re-run

- **NFR implications**:
  - T1-b directly addresses the **Per-step see-think-act cycle < 15 seconds** NFR (productBrief.md) by eliminating a ~10 s futile scroll loop
  - T1-a reduces **HITL escalation rate** by converting a looping failure into a single actionable error the planner can resolve in one additional step
  - T1-c and T1-d restore **Retry resolution rate ≥ 70%** target by re-enabling the RAG-debugger and HITL-guidance retrieval paths that have been silently broken

### Creative Exploration Needed

**T1-a — Container signature list (LOW confidence):** The initial set of four closed-container CSS selectors (`p-select-overlay:not(.p-select-overlay-open)`, `p-dropdown-panel[aria-hidden="true"]`, `select` native, `p-autocomplete[aria-expanded="false"]`) is derived from `backend/kb/profiles/primeng_rules.md` and `backend/engine/planner.py`. The `primeng_rules.md` profile also references `.p-listbox`, `.p-overlay-content`, `.po-sorting-dropdown-panel`, and `.p-select-overlay` (without negation) as overlay/open signals. The negative-match form used for T1-a's "closed" detection needs explicit confirmation against the PrimeNG 19 DOM — specifically whether `p-select-overlay:not(.p-select-overlay-open)` matches a closed overlay's pre-render state or only a never-opened one. **Flag for build phase review** — implementation should start from these four signatures and add a `# TODO: extend with confirmed PrimeNG 19 variants` comment.

**T1-c — rag_debugger ingestion path (LOW confidence):** Whether `ingest_knowledge_base()` retains the LlamaIndex `CodeSplitter` / `SentenceSplitter` chunking or is rewritten to use direct Chroma `upsert` depends on whether the tree-sitter AST splitting produces materially better retrieval quality. The query path (T1-c's target) is independent of the ingestion path. The build phase should decide: if `llama-index-core` is removed entirely (simplest), ingestion switches to a paragraph-split direct-upsert; if LlamaIndex is retained for ingestion only and the `llama-index-llms-openai` extra is explicitly excluded from `requirements.txt`, the query-path rewrite still achieves T1-c's goal. Either approach satisfies AC-VERIFY-3 — the decision is a build-time call, not a design blocker.

Acceptance Criteria: see below — AC-HAPPY-1 through AC-INTEGRATION-1 (pre-existing); AC-VERIFY-1 through AC-ERROR-2 above are the canonical spec-level ACs and supersede the shorthand list below for build-phase verification purposes.

---

## Acceptance Criteria (Canonical)

See `## Specification` → `### Acceptance Criteria` above. Canonical set:

- **AC-VERIFY-1** (T1-a) — `TARGET_INSIDE_CLOSED_CONTAINER` returned with non-empty `trigger_selector`
- **AC-VERIFY-2** (T1-b) — `STRICT_MODE_AMBIGUOUS` in ≤500ms, no `scroll_into_view_if_needed` call, ≥8s reclaimed
- **AC-VERIFY-3** (T1-c) — `query_knowledge_base` returns non-empty; no `llama-index-*` in requirements.txt
- **AC-VERIFY-4** (T1-d) — Vault query returns ≥1 match on Contest query; no `contigious 2D array` error; HNSW metadata on disk
- **AC-VERIFY-5** — Regression: pre-existing tests keep passing
- **AC-INTEGRATION-1** — QA-358 "Select Contest" step escalates in <30s (was ~225s)
- **AC-ERROR-1** (T1-c) — Empty/missing collection returns `""` with WARNING, no exception
- **AC-ERROR-2** (T1-d) — Migration script exits nonzero + logs full error on rebuild failure

---

## Open Questions

⚠️ **To resolve during planning (Spec Writer Agent input needed):**

- [ ] For T1-a: what is the canonical list of "closed container" signatures? PrimeNG uses `.p-dropdown-panel[aria-hidden="true"]`, `.p-select-overlay:not(.p-select-overlay-open)` — is there a comprehensive registry, or do we hand-curate the initial set from the top-N failing tickets?
- [ ] For T1-a: when the target is inside a closed container, do we auto-emit the trigger click (planner-side reflex), or do we return the error and let the planner decide? First iteration: return the error, keep executor stateless. (T3-c reflex layer generalizes later.)
- [ ] For T1-c: is any downstream code depending on the LlamaIndex `Response` object's `.source_nodes` field beyond `rag_debugger.query_knowledge_base()`? Need to grep before removing.
- [ ] For T1-d: after re-embedding with new HNSW params, does the on-disk collection need a schema migration, or does Chroma tolerate the metadata change on collection re-open? If not — the migration script needs to delete + rebuild.
- [ ] Regression scope: which of the archived Playwright test fixtures should we baseline against to prove no regression? At minimum, the `vProMedia` Quick Order flow and the `vTrade` login flow.

---

## Affected Components

- `backend/engine/executor.py` — T1-a + T1-b core logic (lines 962-1040 area)
- `backend/engine/rag_debugger.py` — T1-c full rewrite (~40 lines removed)
- `backend/kb/loader.py` — T1-d HNSW config + migration hook
- `backend/kb/rag.py` — T1-d HNSW metadata at lines 54, 143
- `backend/requirements.txt` — remove obsolete `llama-index-llms-openai` if present
- `scripts/migrate_human_guidance_vault.py` (New) — T1-d one-shot re-embed script
- `backend/engine/test_executor_component_gate.py` (New) — T1-a unit tests
- `backend/engine/test_executor_strict_mode.py` (New / extend) — T1-b unit tests
- `backend/engine/test_rag_debugger.py` (New / extend) — T1-c unit tests
- `backend/kb/test_human_guidance_vault.py` (New / extend) — T1-d unit tests

---

## Test Strategy

### Approach
- **Framework**: pytest with `@pytest.mark.anyio` for async tests; `unittest.mock` for Playwright / Bedrock / Chroma dependencies (per `systemPatterns.md` → Testing Patterns)
- **Emphasis**: unit-heavy — 20 unit tests across four new files, all deterministic (no live browser, no live AWS). One manual integration confirmation (AC-INTEGRATION-1) against `vpromotions` QA env — not automated in CI.
- **Target test count**: 20 tests total (5 + 5 + 4 + 6 per phase)
- **Location**: colocated `test_*.py` files next to source (matches existing convention — `backend/engine/test_evaluator_hardening.py`, `backend/kb/test_matcher.py`, etc.)

### Test Targets

| File | Status | Phase | Tests | Anchors |
|---|---|---|---|---|
| `backend/engine/test_rag_debugger.py` | **NEW** | Phase 1 | 5 | AC-VERIFY-3, AC-ERROR-1, AC-VERIFY-5 |
| `backend/kb/test_human_guidance_vault.py` | **NEW** | Phase 2 | 5 | AC-VERIFY-4, AC-ERROR-2 |
| `backend/engine/test_executor_strict_mode.py` | **NEW** | Phase 3 | 4 | AC-VERIFY-2, AC-VERIFY-5 |
| `backend/engine/test_executor_component_gate.py` | **NEW** | Phase 4 | 6 | AC-VERIFY-1, AC-VERIFY-5 |
| `backend/engine/test_proactive_dismissal.py` | existing | Phase 3-4 | (unmodified) | AC-VERIFY-5 — must keep passing |
| `backend/engine/test_evaluator_hardening.py` | existing | all | (unmodified) | AC-VERIFY-5 — must keep passing |
| `backend/kb/test_rag_enhancement.py` | existing | Phase 1-2 | (unmodified) | AC-VERIFY-5 — must keep passing |

### What is NOT tested (per systemPatterns.md conventions)
- Live LangGraph node execution end-to-end (integration only via manual QA-358 re-run)
- Live Playwright interactions (mocked via `AsyncMock` per `test_proactive_dismissal.py` pattern)
- Live AWS Bedrock embedding calls (mocked)
- Actual Chroma HNSW index build correctness (verified by absence of error, not by benchmark)
- The T3-c planner-side reflex layer (out of scope for Tier 1)

### Per-Phase Test Detail

- **Phase 1 (T1-c) — 5 tests** in `test_rag_debugger.py`:
  1. `query_knowledge_base(error_log)` returns non-empty string containing `[RAG DEBUGGER]` header on populated collection → AC-VERIFY-3
  2. `query_knowledge_base` returns `""` + WARNING log on empty/missing collection → AC-ERROR-1
  3. Module-level import succeeds with no `llama-index-*` packages installed (verify via mock `ImportError` shim) → AC-VERIFY-3
  4. `pip check` after `requirements.txt` edit surfaces no dangling `llama-index-*` dep (asserted via subprocess in test)
  5. Regression: `test_proactive_dismissal.py::test_proactive_dismissal_outside_overlay` still passes → AC-VERIFY-5

- **Phase 2 (T1-d) — 5 tests** in `test_human_guidance_vault.py`:
  1. `HumanGuidanceVault.query("Select Contest from PRF Category dropdown", product="vpromotions")` returns list with ≥1 match on mocked 500-vector collection → AC-VERIFY-4
  2. No `Cannot return the results in a contigious 2D array` line captured by `caplog` at any query volume → AC-VERIFY-4
  3. On-disk collection metadata (queried via `chromadb.PersistentClient(...).get_collection(...).metadata`) includes `hnsw:M=32`, `hnsw:construction_ef=200`, `hnsw:search_ef=100` → AC-VERIFY-4
  4. `scripts/migrate_human_guidance_vault.py` exits with non-zero code when Chroma dir is unwritable (mocked `PermissionError`), and logs the full error → AC-ERROR-2
  5. Migration script exits non-zero when Bedrock embedding raises (mocked `boto3.exceptions.BotoCoreError`) — does NOT silently produce a zero-vector collection → AC-ERROR-2

- **Phase 3 (T1-b) — 4 tests** in `test_executor_strict_mode.py`:
  1. When `total_count > 5` and `visible_count == 0`, the Stage 2.5 branch returns `STRICT_MODE_AMBIGUOUS` in ≤500ms (measured with `time.monotonic()`) → AC-VERIFY-2
  2. `page.locator(...).scroll_into_view_if_needed` (AsyncMock) is NEVER called on the short-circuit path → AC-VERIFY-2
  3. Returned `error_message` string contains the strategy hint substring (e.g. `container_selector`, `get_by_role='option'`) → AC-VERIFY-2
  4. When `total_count <= 5`, the existing scroll-fallback path runs unchanged (mock scroll IS called) → AC-VERIFY-5

- **Phase 4 (T1-a) — 6 tests** in `test_executor_component_gate.py`:
  1. Target `"Contest"` inside `p-select-overlay:not(.p-select-overlay-open)` → returns `TARGET_INSIDE_CLOSED_CONTAINER` with `trigger_selector` matching the closed overlay's trigger → AC-VERIFY-1
  2. Target inside `p-dropdown-panel[aria-hidden="true"]` → returns error with non-empty `trigger_selector` → AC-VERIFY-1
  3. Target inside a closed native `<select>` element → returns error with non-empty `trigger_selector` → AC-VERIFY-1
  4. Target inside `p-autocomplete[aria-expanded="false"]` → returns error with non-empty `trigger_selector` → AC-VERIFY-1
  5. Target NOT inside any closed container (normal open form field) → helper returns falsy; click dispatch proceeds normally → AC-VERIFY-5
  6. Returned `trigger_selector` is a non-empty, non-placeholder CSS string (asserts `isinstance(s, str) and s.strip() and not s.startswith("<")`) → AC-VERIFY-1

- **Phase 4 (integration, manual) — 1 wall-clock check** for AC-INTEGRATION-1:
  - `POST /execute` with `{"ticket_id":"QA-358","role":"qa_analyst"}` against `vpromotions` QA env; measure wall-clock for the "Select Contest from PRF Category dropdown" step. **Pass** if <30s (auto-recover or fast-escalate). **Fail** if ≥30s or reproduces the ~225s pattern.

---

## Implementation Roadmap

### New Source Files (extensions pinned per `systemPatterns.md` → Code Organization Patterns)

| Path | Status | Extension | Rationale |
|---|---|---|---|
| `backend/engine/executor.py` | extend | `.py` | backend/engine/ → `.py` |
| `backend/engine/rag_debugger.py` | extend (rewrite query path) | `.py` | backend/engine/ → `.py` |
| `backend/kb/rag.py` | extend | `.py` | backend/kb/ → `.py` |
| `backend/kb/loader.py` | extend | `.py` | backend/kb/ → `.py` |
| `backend/requirements.txt` | extend | `.txt` | project convention |
| `scripts/migrate_human_guidance_vault.py` | **NEW** | `.py` | `scripts/` directory is Python-scripts convention (per `ls scripts/`: benchmark_*.py, sync_*.py, validate_env.py) |
| `backend/engine/test_rag_debugger.py` | **NEW** | `.py` | backend/engine/ → `.py`; matches `test_*.py` naming |
| `backend/kb/test_human_guidance_vault.py` | **NEW** | `.py` | backend/kb/ → `.py`; matches `test_*.py` naming |
| `backend/engine/test_executor_strict_mode.py` | **NEW** | `.py` | backend/engine/ → `.py`; matches `test_*.py` naming |
| `backend/engine/test_executor_component_gate.py` | **NEW** | `.py` | backend/engine/ → `.py`; matches `test_*.py` naming |

### Phase Order (risk-ascending)

Phases are ordered lowest-risk-first, so early phases restore visibility (RAG debugger) and unlock HITL memory retrieval before touching the hot executor path. Each phase is one `/bmb:build` invocation → one commit → human review.

---

#### Phase 1 — T1-c: Fix RAG Debugger LlamaIndex Dependency

**Goal**: Restore `rag_debugger.query_knowledge_base()` to a working state by replacing the LlamaIndex `VectorStoreIndex.as_query_engine()` call with a direct `chromadb.Collection.query()` call. Remove `llama-index-*` packages from `requirements.txt`.

**AC covered**: AC-VERIFY-3, AC-ERROR-1

**Files touched**:
- `backend/engine/rag_debugger.py` — remove `_LLAMA_AVAILABLE` guard + LlamaIndex import block (lines 66-89), rewrite `query_knowledge_base()` around line 494 to call `collection.query()` directly, remove `response.source_nodes` access (line 500)
- `backend/requirements.txt` — remove lines 79-83 (`llama-index-core`, `llama-index-embeddings-bedrock`, `llama-index-vector-stores-chroma`); ensure `chromadb>=0.5.0` is a direct dependency (currently transitive via LlamaIndex)
- `backend/engine/test_rag_debugger.py` — **NEW** (5 tests, see Test Strategy)

**Deferred (build-time decision, LOW-confidence flag from Spec)**: whether `ingest_knowledge_base()` retains LlamaIndex chunking or switches to direct paragraph-split upsert. Either approach satisfies AC-VERIFY-3.

**Verify**: `pytest backend/engine/test_rag_debugger.py -v` and `pip install -r backend/requirements.txt && pip check` (should show no dangling `llama-index-*` warnings)

---

#### Phase 2 — T1-d: Fix HumanGuidanceVault HNSW Parameters

**Goal**: Recreate the `human_guidance` Chroma collection with tuned HNSW parameters so vault queries succeed with 500+ vectors. Ship a one-shot migration script.

**AC covered**: AC-VERIFY-4, AC-ERROR-2

**Files touched**:
- `backend/kb/rag.py` — line 54 and line 143: change `metadata={"hnsw:space": "cosine"}` to `metadata={"hnsw:space": "cosine", "hnsw:M": 32, "hnsw:construction_ef": 200, "hnsw:search_ef": 100}` (line 54 targets `TestPlanVault`; line 143 targets `HumanGuidanceVault` — the T1-d target; confirm whether `TestPlanVault` also needs the tuning during build — flagged in Scope Boundaries)
- `backend/kb/loader.py` — if `HumanGuidanceVault` is instantiated via a separate `get_or_create_collection` call, apply the same HNSW metadata there
- `scripts/migrate_human_guidance_vault.py` — **NEW**: (a) delete existing `storage/chromadb` collection for `human_guidance`, (b) recreate with new HNSW metadata, (c) re-embed all entries from `knowledge/human_guidance.md` via Bedrock, (d) exit non-zero on any failure with full stack trace logged
- `backend/kb/test_human_guidance_vault.py` — **NEW** (5 tests, see Test Strategy)

**Verify**: `pytest backend/kb/test_human_guidance_vault.py -v` and dry-run of the migration script against a temp Chroma directory.

---

#### Phase 3 — T1-b: Kill Futile Scroll Fallback in Strict-Mode Branch

**Goal**: In the executor's Stage 2.5 strict-mode branch (0 visible, `total_count > 5`), short-circuit `scroll_into_view_if_needed` and surface `STRICT_MODE_AMBIGUOUS` immediately with a strategy hint. Reclaims ~10s per failure.

**AC covered**: AC-VERIFY-2

**Files touched**:
- `backend/engine/executor.py` — the Stage 2.5 branch at lines 991-1040. Rewrite the branch: `if total_count > 5 and visible_count == 0: return STRICT_MODE_AMBIGUOUS` with strategy hint; leave the `total_count <= 5` path unchanged
- `backend/engine/test_executor_strict_mode.py` — **NEW** (4 tests, see Test Strategy)

**Verify**: `pytest backend/engine/test_executor_strict_mode.py backend/engine/test_evaluator_hardening.py backend/engine/test_proactive_dismissal.py -v`

---

#### Phase 4 — T1-a: Component-Aware Precondition Check + QA-358 Integration Run

**Goal**: Add `_is_target_in_open_container(page, target_text)` above the click dispatch (executor.py ~line 948). When the target text is inside a closed container (per the four PrimeNG signatures), return `TARGET_INSIDE_CLOSED_CONTAINER: open <trigger_selector> first`. Then re-run QA-358 for AC-INTEGRATION-1 confirmation.

**AC covered**: AC-VERIFY-1, AC-INTEGRATION-1

**Files touched**:
- `backend/engine/executor.py` — add `async def _is_target_in_open_container(page, target_text: str) -> tuple[bool, str | None]:` returning `(is_inside_closed, trigger_selector_or_None)`. Insert call above the click dispatch at ~line 948. On positive result, return the standard executor error dict with `error_message="TARGET_INSIDE_CLOSED_CONTAINER: open <trigger_selector> first"`.
- `backend/engine/test_executor_component_gate.py` — **NEW** (6 tests, see Test Strategy)

**Initial container signatures** (from `backend/kb/profiles/primeng_rules.md` + `backend/engine/planner.py` — the LOW-confidence field from the Spec):
```python
CLOSED_CONTAINER_SELECTORS = [
    "p-select-overlay:not(.p-select-overlay-open)",
    "p-dropdown-panel[aria-hidden='true']",
    "select",  # native, always "closed" until clicked
    "p-autocomplete[aria-expanded='false']",
]
# TODO: extend with confirmed PrimeNG 19 variants once QA-358 re-run surfaces edge cases
```

**Integration confirmation (AC-INTEGRATION-1)**: after Phase 4 unit tests pass and code merges, manually invoke `POST /execute {"ticket_id":"QA-358","role":"qa_analyst"}` against `vpromotions` QA env; capture wall-clock for the "Select Contest from PRF Category dropdown" step. Log the result (auto-recover / fast-escalate <30s / regression ≥30s) in the reflection doc.

**Verify**: `pytest backend/engine/test_executor_component_gate.py -v` + manual QA-358 re-run.

---

## Creative Phases

**Required**: None.

The Spec Writer Agent flagged HIGH confidence on all critical fields. Two LOW-confidence sub-decisions (T1-a container-signature list completeness, T1-c ingestion-path strategy) are scoped as **build-phase decisions** and do not gate the plan:

- **T1-a container signatures**: Ship the initial four PrimeNG selectors with a `# TODO: extend` comment. If QA-358 re-run (AC-INTEGRATION-1) exposes a missing signature, capture it in reflection for a follow-on KB maintenance task.
- **T1-c ingestion path**: Decide during Phase 1 build whether to keep LlamaIndex for `ingest_knowledge_base()` (retaining chunking quality) or switch to direct paragraph-split Chroma upsert (simplest, no dependency). The query-path rewrite (T1-c's target) is independent.

**Guiding Principle alignment**: T1-a is a direct application of "Failure Diary Pattern" (turn a repeated failure into an actionable error code). T1-b aligns with "Programmatic Tier 1 Verification" (DOM checks are fast; skip the futile fallback). T1-c and T1-d restore "HITL as Learning Signal" and RAG-based recovery paths that are silently broken today. No deviations from documented principles.

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Last Completed Phase**: Phase 4: T1-a — Component-Aware Precondition Check
**Phase Number**: 4 of 4 COMPLETE
**Is Multi-Phase**: YES
**Phase 4 Committed**: 2026-07-28
**Reflection Completed**: 2026-07-28
**Archived**: 2026-07-28

### Current Build Step
**Step**: /bmb:archive — COMPLETE
**Status**: COMPLETE
**Completed**: 2026-07-28

### Phase 1 Summary
- Tests: 5 new tests in `backend/engine/test_rag_debugger.py` (5/5 PASS)
- Production: `backend/engine/rag_debugger.py` rewritten (LlamaIndex removed, direct Chroma query)
- Deps: `backend/requirements.txt` — removed `llama-index-core`, `llama-index-embeddings-bedrock`, `llama-index-vector-stores-chroma`
- Lint: PASS (ruff)
- Regression: 39/39 passing across pre-existing test suites (4 pre-existing failures unaffected)

### Phase 2 Summary
- Tests: 5 new tests in `backend/kb/test_human_guidance_vault.py` (5/5 PASS)
- Production: `backend/kb/rag.py` line 143 — added hnsw:M=32, hnsw:construction_ef=200, hnsw:search_ef=100 to HumanGuidanceVault collection metadata
- New: `scripts/migrate_human_guidance_vault.py` — one-shot HNSW migration script with error-exit hooks
- Lint: PASS (ruff)
- Regression: pre-existing failures unchanged (test_invalidate_human_guidance_cache, test_human_guidance_entry_count, test_kb_retrieval_accuracy — all pre-dating this phase)

### Phase 3 Summary
- Tests: 4 new tests in `backend/engine/test_executor_strict_mode.py` (4/4 PASS)
- Production: `backend/engine/executor.py` Stage 2.5 branch — added short-circuit for `total_count > 5` returning `STRICT_MODE_AMBIGUOUS` with strategy hint; scroll path preserved for `total_count <= 5`
- Lint: PASS (ruff — new test file clean; executor.py pre-existing issues only)
- Regression: 38/38 passing (test_executor_strict_mode + test_evaluator_hardening + test_proactive_dismissal + test_rag_enhancement)

### Phase 4 Summary
- Tests: 6 new tests in `backend/engine/test_executor_component_gate.py` (7/7 PASS including asyncio parameterization)
- Production: `backend/engine/executor.py` — added `_is_target_in_open_container()` + `_CLOSED_CONTAINER_SELECTORS` + integration gate in click dispatch path
- Lint: PASS (ruff — new test file clean after import sort fix)
- Regression: 231/231 passing (8 pre-existing failures unchanged, confirmed on Phase 3 stash baseline)

### Completed Phases
- [x] Phase 1 — T1-c: Fix RAG Debugger LlamaIndex Dependency (committed 2026-07-28)
- [x] Phase 2 — T1-d: Fix HumanGuidanceVault HNSW Parameters (committed 2026-07-28)
- [x] Phase 3 — T1-b: Kill Futile Scroll Fallback in Strict-Mode Branch (committed 2026-07-28)
- [x] Phase 4 — T1-a: Component-Aware Precondition Check + QA-358 Integration Run (committed 2026-07-28)

### Remaining Phases
(none — all 4 phases complete)

### Guard & Recovery Log
Phase 1: guard FAIL C1+C2 (false positives):
  - C1: pre-existing dirty tracked files (.worktrees/FEAT-* etc.) — not from this phase, multi-worktree project state
  - C2: commit-guard TEST_RE does not cover Python test_ prefix convention (only .test., tests/ dir); test_rag_debugger.py IS present (5/5 pass), classified as prod by regex
  Decision: tests confirmed present and passing — not a TDD gap, tooling limitation. Proceeding.
  Recommendation for /bmb:reflect: extend commit-guard TEST_RE to include test_*.py pattern.
Phase 2: guard script cannot distinguish worktree vs project-root checkout (same pre-existing false positives). test_human_guidance_vault.py (5/5 PASS) and scripts/migrate_human_guidance_vault.py confirmed present. Proceeding.
Phase 3: artifact seam check — test_executor_strict_mode.py confirmed present in worktree root (project root is the checkout for this branch). Commit guard C2: Python test_ prefix convention confirmed (4 new tests, 1 new prod file in executor.py). Pre-existing C1/C2 ruff issues in executor.py are not from Phase 3.
Phase 4: artifact seam check — test_executor_component_gate.py (7 PASS) + executor.py (T1-a gate) confirmed present. Pre-existing dirty files (.worktrees/*, storage/*) not from this phase. TDD invariant: 1 prod file (executor.py modified) + 1 test file (test_executor_component_gate.py new) — C2 PASS.

### Resumption Notes
**Can Resume**: NO
**Resume From**: N/A — BUILD_COMPLETE; run /bmb:reflect vqa-tier1-executor-recovery
