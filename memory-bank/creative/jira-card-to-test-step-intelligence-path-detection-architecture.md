# Architecture Decision: Navigation Path & Ambiguity Detection — PreviewStepsResponse Schema

**Created**: 2026-07-14
**Status**: DECIDED
**Decision Type**: Architecture

## Context

### System Requirements

- `GET /preview-steps` must return `detected_paths: list[str]` and `ambiguities: list[str]` alongside the existing `steps` list
- `detected_paths` must enumerate the distinct navigation paths found in the Jira AC text (e.g., `["HDah > Module Abilities > Edit Module", "HDah > Report Access > Edit"]`)
- `ambiguities` must surface vague terms, undefined values, or missing test data that the user should resolve before running
- The `ClarificationWizardModal.tsx` (Phase 3) must be able to read these two fields and conditionally render based on their contents
- Must not break existing single-path ticket flows — single-path tickets must still produce a valid response with empty or minimal `detected_paths` and `ambiguities`
- `PreviewStepsResponse` in `backend/api/schemas.py` and the corresponding TypeScript type in `frontend/src/types/index.ts` must be extended consistently

### Technical Constraints

- `GET /preview-steps` has a < 30 second total latency budget (including existing two-stage LLM calls to Bedrock via Claude 3.5 Sonnet)
- The existing two-stage pipeline in `ac_parser_node` is already near the latency ceiling for some tickets with large ACs and visual context — adding a new synchronous LLM call risks exceeding the budget
- The raw AC text (`raw_ac`) arrives at `ac_parser_node` before Stage 1; the BDD text and compiled `TestPlan.steps` are available after Stage 1 and Stage 2 respectively
- An existing `_detect_step_ambiguity()` function already performs heuristic ambiguity detection on the post-Stage-1 BDD text (FEAT-058) — it returns `list[str]` warnings but this result is currently only logged, not returned to the API
- The `ac_parser_node` result dict is read by `preview_steps()` in `routes.py` and mapped directly to `PreviewStepsResponse` fields
- AWS Bedrock costs are a concern: every additional LLM call adds ~$0.01–$0.05 per request at current token volumes

### Non-Functional Requirements

- Performance: detection must add < 3s to preview latency in the median case; must not push total latency above 30s
- Accuracy: must correctly identify paths in the canonical `>` delimited notation used by vProMedia PMs; implicit navigation descriptions are a secondary concern
- False positive rate: `detected_paths` must not fabricate paths that aren't in the AC — the wizard UI will present these to users as real toggleable choices, and spurious paths would confuse users
- Backward compatibility: single-path tickets with no ambiguities must receive `detected_paths: []` (or a one-element list) and `ambiguities: []` without wizard activation
- Security: no AC text content should appear in metric labels (high cardinality violation)

## Component Analysis

### Core Components

| Component | Purpose | Responsibilities |
|-----------|---------|------------------|
| `PreviewStepsResponse` (schemas.py) | API response schema | Carry `detected_paths` and `ambiguities` fields; validate and serialize the response |
| `preview_steps()` (routes.py) | API endpoint handler | Map detection output from `ac_parser_node` result dict to `PreviewStepsResponse` |
| `ac_parser_node` (ac_parser.py) | LangGraph node | Run path/ambiguity detection at the appropriate pipeline stage and include results in returned state dict |
| Detection Logic (new or extended) | Core algorithm | Produce `detected_paths` and `ambiguities` from AC text and/or pipeline intermediates |
| `frontend/src/types/index.ts` | TypeScript contract | Mirror `detected_paths: string[]` and `ambiguities: string[]` on the frontend type |

### Component Interactions

```
GET /preview-steps
    │
    ▼
routes.py: preview_steps()
    │
    ├── jira_fetch_node()   → fetches raw_ac
    │
    └── ac_parser_node()
            │
            ├── (Stage 0 LLM call — Option B only)
            │
            ├── Stage 1: _stage_1_normalize()  → bdd_text
            │       └── Path/ambiguity from BDD (Option C/D)
            │
            ├── Stage 2: _stage_2_compile()    → TestPlan.steps
            │       └── Path extraction from compiled steps (Option D)
            │
            └── Returns: { ..., detected_paths: [...], ambiguities: [...] }
                                │
                                ▼
            routes.py maps to PreviewStepsResponse(detected_paths=..., ambiguities=...)
                                │
                                ▼
            frontend ClarificationWizardModal reads fields
```

## Options Explored

### Option 1: Pre-Stage-1 Regex Scan of Raw AC Text

- **Description**: Before the Stage 1 LLM call, scan `raw_ac` with a compiled regex for `>` delimited navigation sequences (e.g., `\b(\w[\w\s]+(?:\s*>\s*\w[\w\s]+)+)` or similar). Each match produces one entry in `detected_paths`. For `ambiguities`, extend the existing `_detect_step_ambiguity()` result (currently post-Stage-1) by also running a lightweight keyword scan on `raw_ac` for patterns like "correct total", "appropriate value", "etc.", "TBD", or other vague-test-data markers. Both scans run in pure Python with no I/O, completing in microseconds.

- **Architecture Diagram**:
  ```
  raw_ac
    │
    ├── regex_detect_paths(raw_ac)     → detected_paths (O(n) time, no I/O)
    ├── keyword_detect_ambiguities(raw_ac) → ambiguities (O(n) time, no I/O)
    │
    ▼
  Stage 1: _stage_1_normalize()
    │
    ▼
  Stage 2: _stage_2_compile()
    │
    ▼
  ac_parser_node returns { detected_paths, ambiguities, ... }
  ```

- **Pros**:
  - Zero added latency — regex runs in under 1ms on any realistic AC text
  - Zero added cost — no LLM calls
  - Does not alter the existing two-stage pipeline at all — detection is a pure side computation on the input
  - High precision for explicit `>` notation, which is the canonical vProMedia PM format as evidenced by the spec examples (`HDah > Module Abilities > Edit Module`)
  - Deterministic and unit-testable without mocking Bedrock
  - Aligns with the "Programmatic Tier 1 Verification" guiding principle — use deterministic checks first, LLM as fallback only
  - Immediately reusable for Phase 3 wizard without any Phase 1 changes to the pipeline itself

- **Cons**:
  - Only detects explicit `>` notation — misses implicit navigation descriptions like "navigate to the Reports section, then open Production Orders" (no `>` in the text)
  - Ambiguity detection on raw AC text is limited to pattern matching (vague keywords) and cannot reason about missing test data the way an LLM would
  - Regex must be carefully tuned: `>` is used in Markdown blockquotes and comparison operators, so the pattern must exclude those cases (e.g., require word characters on both sides, no leading `>` at line start in isolation)

- **Technical Fit**: High — pure Python added before `_stage_1_normalize()`; no pipeline structure changes
- **Complexity**: Low
- **Scalability**: High — O(n) text scan, no external dependencies

---

### Option 2: Dedicated Stage 0 LLM Call for Path/Ambiguity Detection

- **Description**: Add a new Stage 0 LLM call in `ac_parser_node` that runs before Stage 1. The Stage 0 prompt asks the model to identify (a) all navigation paths in the AC and (b) all ambiguous or under-specified items. The response is a small JSON payload `{ "paths": [...], "ambiguities": [...] }`. Stage 0 uses Claude Haiku (cheaper, faster) rather than Claude 3.5 Sonnet to minimize cost and latency.

- **Architecture Diagram**:
  ```
  raw_ac
    │
    ├── Stage 0 LLM (Haiku): detect_paths_and_ambiguities(raw_ac)
    │       → { paths: [...], ambiguities: [...] }   (~3–8s)
    │
    ▼
  Stage 1: _stage_1_normalize()                      (~5–15s)
    │
    ▼
  Stage 2: _stage_2_compile()                        (~5–15s)
    │
    ▼
  ac_parser_node returns { detected_paths, ambiguities, ... }
  ```

- **Pros**:
  - Higher accuracy: the LLM can recognize implicit navigation descriptions, table-embedded paths, and context-dependent ambiguities that regex cannot
  - Can detect ambiguities that require domain understanding, e.g., "correct total" (undefined expected value) or "the appropriate module" (no specific module named)
  - More robust to varied PM writing styles

- **Cons**:
  - Adds 3–8 seconds of latency per preview call (Haiku is faster than Sonnet but still adds a serial LLM round-trip)
  - Total latency for a ticket with MP4 attachments (Stage 0 + ffmpeg + Stage 1 + Stage 2) could exceed the 30s budget
  - Adds $0.005–$0.02 per preview call depending on token count (significant at scale if PMs iterate frequently)
  - Stage 0 runs serially before Stage 1 — it cannot be parallelized with Stage 1 because Stage 1 needs the raw AC, not the Stage 0 output, so there is no benefit to pipelining
  - The Compounding Pipeline Depth anti-pattern documented in systemPatterns.md explicitly warns against adding LLM nodes in sequence: "Minimize live-loop nodes... separate nodes are only justified for async operations or graph branching logic"
  - Adds another LLM prompt to maintain, including anchoring, structural delimiters, and prompt audit checklist compliance
  - UNMEASURED accuracy advantage over regex for the explicit `>` format used by vProMedia PMs

- **Technical Fit**: Medium — requires a new async function, new prompt string, and careful integration to avoid exceeding the latency budget
- **Complexity**: High
- **Scalability**: Medium — cost and latency scale linearly with every preview call; frequent ticket iteration by PMs amplifies the impact

---

### Option 3: Post-Stage-2 Extraction from Compiled TestPlan

- **Description**: After Stage 2 compiles the `TestPlan`, extract `detected_paths` from the structured `step.goal` strings in `compiled_plan.steps` by re-running the regex on the BDD-normalized goals (which are cleaner than the raw AC). For `ambiguities`, reuse the existing `_detect_step_ambiguity(bdd_text)` result (currently computed and logged at line 1204 of ac_parser.py) and surface it in the returned state dict rather than discarding it.

- **Architecture Diagram**:
  ```
  raw_ac
    │
    ▼
  Stage 1: _stage_1_normalize()  → bdd_text
    │
    ├── _detect_step_ambiguity(bdd_text) → ambiguity_warnings (already computed!)
    │
    ▼
  Stage 2: _stage_2_compile()    → compiled_plan.steps
    │
    ├── _extract_paths_from_goals([step.goal for step in compiled_plan.steps])
    │       → detected_paths (regex on goal strings)
    │
    ▼
  ac_parser_node returns { detected_paths, ambiguities: ambiguity_warnings, ... }
  ```

- **Pros**:
  - `ambiguities` detection requires NO new code — `_detect_step_ambiguity(bdd_text)` is already computed at line 1204 and already returns the exact `list[str]` format needed; it just needs to be included in the returned state dict
  - The BDD-normalized goal strings from Stage 2 are cleaner than raw AC text — less noise from Markdown formatting, blockquotes, and Jira-specific markup
  - Zero added latency — all the required data is already produced by the existing pipeline
  - Zero added cost
  - `ambiguities` surface through the LLM's normalization lens (Stage 1 is designed to detect vague terms per RULE 2 in `BDD_NORMALIZER_PROMPT`)

- **Cons**:
  - Path detection still requires regex on goal strings — shares the "only catches explicit `>` notation" limitation with Option 1
  - Slightly later in the pipeline: if Stage 1 or Stage 2 fails, neither `detected_paths` nor `ambiguities` is available (unlike Option 1 which runs before both stages and could return partial data even on LLM failure)
  - Path extraction from BDD goal strings is less reliable than from raw AC: Stage 1 may rewrite navigation paths (e.g., "Navigate to HDah > Module Abilities > Edit Module" might become "Navigate to the Edit Module screen under Module Abilities"), losing the exact `>` string if the LLM paraphrases it

- **Technical Fit**: High — builds on existing code; `_detect_step_ambiguity` output is already being discarded; routing it to the return dict is a 2-line change
- **Complexity**: Low — for ambiguities (already computed); Medium — for path extraction from goals (new regex, but simple)
- **Scalability**: High — O(n) on goal strings; no external calls

---

### Option 4: Hybrid — Pre-Stage-1 Regex for Paths + Reuse Existing Post-Stage-1 Ambiguity Detection (Recommended)

- **Description**: Combine the strongest parts of Options 1 and 3. Run path detection as a pure regex scan of `raw_ac` before Stage 1 (Option 1's approach), because raw AC text reliably preserves the `>` notation that PMs write. Reuse the already-computed `_detect_step_ambiguity(bdd_text)` result from after Stage 1 (Option 3's approach), because Stage 1 normalizes the text into clean BDD format that the existing heuristic was designed to analyze. The two concerns are thus sourced from the most appropriate pipeline stage for each: raw text for structural path markers, BDD-normalized text for semantic ambiguity.

- **Architecture Diagram**:
  ```
  raw_ac
    │
    ├── _detect_nav_paths(raw_ac)          → detected_paths (regex, ~0ms)
    │
    ▼
  Stage 1: _stage_1_normalize()            → bdd_text
    │
    ├── _detect_step_ambiguity(bdd_text)   → ambiguities (already computed!)
    │
    ▼
  Stage 2: _stage_2_compile()              → compiled_plan
    │
    ▼
  ac_parser_node returns {
      detected_paths: detected_paths,   # from raw_ac scan
      ambiguities: ambiguity_warnings,  # from existing FEAT-058 logic
      ...
  }
  ```

- **Pros**:
  - Zero added latency — both detections complete in under 1ms total
  - Zero added LLM cost
  - Maximizes precision for `detected_paths`: scans raw AC before Stage 1 can paraphrase navigation sequences
  - `ambiguities` leverages the existing `_detect_step_ambiguity()` which was already hardened for the BDD output format (not raw text) — the function checks `bdd_text` line-by-line for the patterns the BDD normalizer produces
  - Degrades gracefully on Stage 1/2 failure: `detected_paths` is still available from the raw scan even if the LLM pipeline fails; `ambiguities` defaults to `[]` on pipeline failure (acceptable — ambiguity warnings are advisory, not blocking)
  - Minimal code surface: `_detect_nav_paths()` is ~15 lines of regex; wiring `ambiguity_warnings` into the return dict is 2 lines
  - Does not alter the existing two-stage pipeline structure — fully consistent with the "Two-Stage AC Parsing" pattern in systemPatterns.md
  - Consistent with the "Programmatic Tier 1 Verification" guiding principle: deterministic rule-based detection before any LLM fallback
  - No new prompts to maintain, no prompt audit checklist items needed

- **Cons**:
  - `detected_paths` misses implicit navigation descriptions (no `>` in text) — acceptable risk because vProMedia PMs consistently use `>` notation per the spec examples; implicit navigation is a future enhancement
  - `ambiguities` is limited to the three heuristic categories in `_detect_step_ambiguity()` (vague sort, missing subject, generic verification) — does not cover every possible form of under-specification; also acceptable because ambiguity detection is advisory and the wizard provides a free-text field for users to surface additional concerns
  - The existing `_detect_step_ambiguity()` was not originally designed for external consumption — its warning strings are verbose (e.g., `"Vague Sort Goal: 'when sort the table correctly' needs a specific direction (e.g., 'ascending')"`) and may need minor formatting cleanup to be appropriate for the wizard UI

- **Technical Fit**: High — builds on existing patterns, respects pipeline structure
- **Complexity**: Low
- **Scalability**: High

## Evaluation Matrix

| Criteria | Option 1: Pre-Stage-1 Regex | Option 2: Stage 0 LLM | Option 3: Post-Stage-2 Extraction | Option 4: Hybrid (Chosen) |
|----------|----------------------------|-----------------------|----------------------------------|--------------------------|
| Latency impact | None | +3–8s per call | None | None |
| LLM cost | None | +$0.005–$0.02/call | None | None |
| Path detection precision | High (explicit `>`) | High (explicit + implicit) | Medium (post-normalization) | High (raw text, explicit `>`) |
| Ambiguity detection quality | Medium (raw text keyword scan) | High (LLM reasoning) | High (reuses FEAT-058 on BDD text) | High (reuses FEAT-058 on BDD text) |
| Implementation effort | Low | High | Low | Low |
| Pipeline structure compliance | High | Low (violates depth anti-pattern) | High | High |
| Maintainability | High | Medium (new prompt to maintain) | High | High |
| Observability | High | Medium (new span/log surface) | High | High |
| Fallback robustness | High | Medium | Low | High |
| 30s latency budget safety | High | Low (at risk) | High | High |

## Observability Architecture

This decision does not introduce new services or new network hops. All detection logic is synchronous Python within the existing `ac_parser_node` function. The observability strategy extends the existing patterns.

### Logging

- **Library**: Python `logging` module (existing `logger = logging.getLogger(__name__)` in `ac_parser.py`)
- **Format**: Structured log lines via the existing logger; in production these are captured by the container logging driver as structured JSON
- **New log events to add**:
  - `INFO [run_id] Path detection: found N navigation paths in raw AC` — logged after `_detect_nav_paths()` runs
  - `INFO [run_id] Ambiguity detection: N warning(s) surfaced from BDD text` — replaces the existing `WARNING` log for ambiguity_warnings (demote to INFO since warnings are now surfaced to the UI; reserve WARNING for actual parsing failures)
  - `DEBUG [run_id] detected_paths: [...]` — logged at DEBUG to avoid log volume in production
- **Configuration**: Controlled by existing `LOG_LEVEL` environment variable

### Distributed Tracing

- **SDK**: The existing Bedrock call spans in `ac_parser_node` are already instrumented. Path/ambiguity detection runs synchronously within the same `ac_parser_node` execution span — no new spans required for sub-millisecond operations.
- **Propagation**: No new service boundaries are crossed. The existing `run_id` acts as the correlation identifier propagated through log statements.
- **Sampling**: Inherits from existing `OTEL_TRACES_SAMPLER_ARG` configuration.

### Metrics

- **Standard Metrics**: The existing `http_requests_total` and `http_request_duration_seconds` for `GET /preview-steps` already capture end-to-end latency. No change needed.
- **Custom Business Metrics** (new):
  - `vqa_preview_paths_detected_total{has_paths}` — Counter, labels: `has_paths=true/false`. Tracks how often multi-path tickets are detected. Enables monitoring of wizard trigger frequency without high-cardinality labels.
  - `vqa_preview_ambiguities_detected_total{has_ambiguities}` — Counter, labels: `has_ambiguities=true/false`.
  - Labels deliberately avoid ticket IDs and path content (cardinality violation risk).

### Configuration Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `LOG_LEVEL` | Controls whether `DEBUG` path lists appear in logs | `info` |
| `LOG_FORMAT` | JSON or text format | `json` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Trace collector endpoint | None (dev: console) |
| `OTEL_SERVICE_NAME` | Service identifier in traces | `vqa-backend` |
| `OTEL_TRACES_SAMPLER_ARG` | Sampling ratio | `1.0` (dev) |

## Decision

**Chosen**: Option 4 — Hybrid (Pre-Stage-1 regex for paths + reuse existing post-Stage-1 ambiguity detection)

### Rationale

Option 4 is the correct architecture because it assigns each detection concern to the pipeline stage where its data source is most reliable:

1. **Navigation paths from raw AC**: The `>` operator in vProMedia PM writing is a structural marker, not prose. It survives regex scanning of raw AC text precisely because PMs write it as a structured shorthand. By scanning `raw_ac` before Stage 1, we capture the exact path strings as the PM wrote them — `HDah > Module Abilities > Edit Module` — which are also the strings the wizard should display to the user as toggle labels. Stage 1 may normalize these into prose ("Navigate to the Edit Module screen"), which would produce less readable wizard labels and potentially lose the path boundary information.

2. **Ambiguities from BDD text**: The existing `_detect_step_ambiguity(bdd_text)` function was built in FEAT-058 specifically to analyze BDD-normalized output. It checks for vague sort directions, missing click subjects, and generic verification phrases — patterns that are expressed cleanly in the BDD `When`/`Then` format that Stage 1 produces. Running the same heuristics on raw AC text would produce false positives because raw Jira text mixes prose, bullet points, and structured data in ways the heuristics don't account for. The FEAT-058 function on BDD text already has the correct calibration.

3. **Zero latency and cost impact**: The 30-second budget is already under pressure from Stage 1 (5–15s), Stage 2 (5–15s), and potentially ffmpeg frame extraction (Deliverable 2). Adding a Stage 0 LLM call (Option 2) risks exceeding the budget on complex tickets. The hybrid approach adds < 1ms regardless of AC complexity.

4. **Alignment with guiding principles**: The systemPatterns.md "Programmatic Tier 1 Verification" principle mandates deterministic checks before LLM fallback. Option 4 is the programmatic tier. The Compounding Pipeline Depth anti-pattern explicitly warns against adding sequential LLM nodes — Option 2 would violate this.

5. **Minimal code surface**: The `_detect_nav_paths()` function is approximately 15 lines. The `ambiguity_warnings` variable is already computed at line 1204 — it only needs to be added to the return dict and the `PreviewStepsResponse` schema. This is the lowest-risk implementation path.

### Trade-offs Accepted

- **Implicit navigation descriptions are not detected**: If a PM writes "navigate to the Reports section, then open Production Orders" without using `>`, it will not appear in `detected_paths`. This is acceptable because (a) the spec examples all use `>` notation, (b) vProMedia PMs are trained on this convention, and (c) the wizard still shows whatever paths are detected — zero detected paths means the wizard does not appear, which is the correct behavior for tickets without explicit multi-path notation.

- **Ambiguity detection is heuristic, not exhaustive**: The three heuristics in `_detect_step_ambiguity()` do not cover every possible form of ambiguity. This is acceptable because the wizard provides a free-text resolution field for users to surface additional concerns that the system did not detect. The system catches common, high-frequency ambiguity patterns; users resolve the rest manually.

- **`ambiguities` defaults to empty list on Stage 1/2 failure**: If the LLM pipeline fails and the fallback legacy parser runs, `ambiguity_warnings` will be unavailable. The `PreviewStepsResponse` will have `ambiguities: []` in this case. This is correct behavior — if the pipeline failed, we cannot trust any ambiguity analysis anyway.

## Exact Schema Fields to Add to PreviewStepsResponse

```python
class PreviewStepsResponse(BaseModel):
    """
    Response for ``GET /preview-steps``.

    Returns the Jira ticket summary and the LLM-parsed AC steps so the
    product team can review and correct them before triggering execution.
    """

    ticket_id: str
    summary: str
    acceptance_criteria: str  # raw AC text from Jira
    steps: list[str]  # LLM-parsed steps (editable before execution)
    parse_quality: str | None = None  # "rejected", "poor", "fair", "good"
    parse_quality_reason: str | None = None  # explanation for rejection/low score
    ac_quality: ACQualityResultSchema | None = None  # FEAT-001 detailed feedback
    # New fields for jira-card-to-test-step-intelligence Clarification Wizard (Phase 3)
    detected_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Navigation paths found in the Jira AC text using '>' delimiter notation. "
            "Example: ['HDah > Module Abilities > Edit Module', 'HDah > Report Access > Edit']. "
            "Empty list for single-path or non-navigation tickets."
        ),
    )
    ambiguities: list[str] = Field(
        default_factory=list,
        description=(
            "Vague terms, undefined values, or missing test data detected in the AC. "
            "Each entry is a human-readable warning string. "
            "Example: [\"Vague Sort Goal: 'when sort the table correctly' needs a specific direction\"]."
        ),
    )
```

**TypeScript mirror** (to add to `frontend/src/types/index.ts`):

```typescript
interface PreviewStepsResponse {
  ticket_id: string;
  summary: string;
  acceptance_criteria: string;
  steps: string[];
  parse_quality?: string | null;
  parse_quality_reason?: string | null;
  ac_quality?: ACQualityResult | null;
  detected_paths: string[];   // NEW
  ambiguities: string[];      // NEW
}
```

## Implementation Guidelines

1. **Add `_detect_nav_paths(raw_ac: str) -> list[str]` to `ac_parser.py`**: The function should apply a regex that matches sequences of word-and-space tokens joined by `>` (with optional surrounding whitespace), filtering out standalone `>` characters (Markdown blockquote openers) and arithmetic comparisons. A conservative pattern: `r'\b[\w][\w\s]{1,50}(?:\s*>\s*[\w][\w\s]{1,50}){1,}(?:\s*>\s*[\w][\w\s]{1,50})*\b'` applied with `re.findall()` on `raw_ac`. Deduplicate results with `list(dict.fromkeys(matches))`. Return empty list if no matches. Log at INFO the count found.

2. **Call `_detect_nav_paths()` at the top of the `ac_parser_node` function**, immediately after `raw_ac` is read from state and before the quality gate check. Store result as `detected_paths` in local scope. This ensures the result is always available regardless of which pipeline branch executes (LLM pipeline, fallback parser, or override-steps path).

3. **Wire `ambiguity_warnings` into the return dict**: At line 1204, `ambiguity_warnings = _detect_step_ambiguity(bdd_text)` is already computed. Add `"ambiguities": ambiguity_warnings` to the `result` dict at line 1308. For the fallback parser and override-steps paths, default `ambiguities` to `[]` (no BDD text available).

4. **Add `detected_paths` and `ambiguities` to all return paths in `ac_parser_node`**: There are five return paths in the node (override steps, cache hit, empty AC fallback, poor quality rejection, successful parse, and exception fallback). All must include `detected_paths` (available from the pre-stage scan). Only the successful parse path will have `ambiguities`; all others return `[]`.

5. **Update `routes.py preview_steps()`**: Add `detected_paths=parsed.get("detected_paths", [])` and `ambiguities=parsed.get("ambiguities", [])` to the `PreviewStepsResponse(...)` constructor call.

6. **Update `PreviewStepsResponse` in `schemas.py`** per the exact field definitions above.

7. **Update `frontend/src/types/index.ts`** to add the two new fields to the TypeScript type.

8. **Unit tests in `tests/test_prompt_path_parsing.py`** (per test strategy in jira-card-to-test-step-intelligence.md): add fixture AC text with explicit `>` paths, assert `_detect_nav_paths()` returns the correct list. Add fixture with single-path and no-path AC, assert empty list returned. Existing `_detect_step_ambiguity()` tests can be added to the same file.

9. **Prompt audit not required**: No prompt strings are changed in this architecture decision. `BDD_NORMALIZER_PROMPT` and `JSON_COMPILER_PROMPT` are unchanged. The prompt engineering work for Deliverable 1 (teaching the LLM to split paths into scenario blocks) is separate from this detection architecture.

10. **Ambiguity string formatting review**: Before Phase 3 implementation, review the warning strings returned by `_detect_step_ambiguity()` for user-facing readability. The current format (e.g., `"Vague Sort Goal: '...' needs a specific direction"`) is acceptable for a first release but should be reviewed against the wizard UI mockup.

## Validation Checklist

- [x] Meets all system requirements — schema fields defined, detection logic sourced from correct pipeline stages
- [x] Respects technical constraints — zero added latency, zero added cost, no pipeline structure changes
- [x] Addresses non-functional requirements — < 1ms detection; deterministic; no false paths fabricated; single-path tickets return empty `detected_paths`
- [x] Technically feasible — regex + dict passthrough; existing function already computes `ambiguity_warnings`
- [x] Risks identified and acceptable — implicit navigation miss is documented and accepted
- [x] Complies with Guiding Principles in systemPatterns.md — "Programmatic Tier 1 Verification" honored; "Two-Stage AC Parsing" pattern preserved; no new LangGraph nodes added
- [x] Respects established patterns — builds on existing `_detect_step_ambiguity()` FEAT-058 pattern; extends existing return dict pattern
- [x] Observability architecture defined — logging, metrics, tracing strategy specified
- [x] Trace context propagation — no new service boundaries; existing `run_id` correlation preserved in all log statements
- [x] Logging strategy consistent with observability-requirements.md — uses existing `logger`, no `console.log`, no sensitive data, appropriate log levels
- [x] Metrics strategy follows naming conventions — snake_case, boolean label cardinality, no ticket IDs in labels

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Regex matches Markdown blockquote `>` as a path segment | Medium | Medium | Anchor regex to require word character on both sides of `>`; exclude line-leading `>` patterns; add unit tests with Markdown-heavy fixtures |
| Stage 1 paraphrases explicit `>` paths and post-Stage-2 path extraction (Option 3 path, not chosen) would have failed | Low | Low | Mitigated by choosing raw AC scan (Option 4) — not applicable to chosen approach |
| `_detect_step_ambiguity()` warning strings too verbose for wizard UI | Low | Low | Review and optionally trim strings in Phase 3 before wizard implementation; no schema change needed |
| Cache in `_ac_cache` stores old results without `detected_paths`/`ambiguities` | Medium | Low | Add `detected_paths` and `ambiguities` with `default=[]` in `PreviewStepsResponse` — missing cache keys default to empty list; cache TTL will naturally expire old entries |
| Frontend type mismatch if `frontend/src/types/index.ts` update is missed | Medium | High | jira-card-to-test-step-intelligence Phase 1 dependency: schema extension (backend + frontend) must be completed as a single PR to prevent runtime type errors in Phase 3 |
| PM writes `A>B` without spaces — regex may not match | Low | Low | Include `\s*>\s*` in pattern to allow zero surrounding spaces; add test fixture |

## Next Steps

1. **Phase 1 implementation**: Add `_detect_nav_paths()` to `ac_parser.py`; wire `detected_paths` into all return paths; wire `ambiguity_warnings` into the successful-parse return; update `PreviewStepsResponse` schema; update TypeScript type
2. **Unit tests**: Add to `tests/test_prompt_path_parsing.py` — fixture coverage for multi-path, single-path, implicit-only, and Markdown-heavy AC text
3. **Phase 3 dependency confirmed**: `ClarificationWizardModal.tsx` can read `detected_paths` and `ambiguities` from the preview response; trigger threshold (len >= 2 OR ambiguities > 0) is a separate UI/UX design decision documented in the companion UI/UX creative document
4. **Cache invalidation review**: Confirm that existing `_ac_cache` TTL is short enough that old cached results (without the new fields) expire before Phase 3 goes live, or add explicit cache busting
