# Spike Card: jira-to-playwright-prompt-quality — Internal/Codebase Lane

**Status**: COMPLETE
**run_id**: 20260715-c5e7c39abca4
**framing_sha**: c5e7c39abca4
**approved_depth**: deep
**approved_lanes**: academic, oss-production, practitioner-discourse, docs, codebase
**MCP used**: n/a (local-only lane)
**mcp_servers_available**: none
**fallback_used**: no

---

## Findings

| Source (file:line) | Type | Evidence Grade | Key Finding | Implications |
|---|---|---|---|---|
| `backend/engine/prompts.py:42–100` | BDD_NORMALIZER_PROMPT | B | Stage 1 prompt uses XML-style structural delimiters (`<GOLDEN_RULES>`, `<RULES>`, `<MANDATORY_REASONING_WORKFLOW>`, `<INPUT_CONTEXT>`, `<CRITICAL_REMINDER>`), a 5-step mandatory reasoning workflow, and 11 explicit rules. NO few-shot examples. NO chain-of-thought output tags. | Prompt follows the Anchoring (Primacy+Recency) convention documented in systemPatterns.md. The missing few-shot layer is the most tractable improvement vector. |
| `backend/engine/prompts.py:107–189` | JSON_COMPILER_PROMPT | B | Stage 2 prompt uses the same XML structural pattern with 7 rules and a typed `<OUTPUT_FORMAT>` block showing exact JSON schema inline. No few-shot examples of correct vs. incorrect compilation. Injects domain glossary and system boundary via `{domain_glossary_section}` and `{system_boundary_rule}` placeholders from profiles. | The inline schema reduces hallucination but does not enforce it at the API level (no tool-use/JSON-mode in Stage 2). A single bad example would already give the LLM a "ground truth" reference. |
| `backend/llm/provider.py:208–211` | Model configuration | B | Default model (`bedrock_model_id`) is `us.anthropic.claude-haiku-4-5-20251001-v1:0` (Haiku 4.5). Heavy model (`bedrock_model_id_heavy`) is `us.anthropic.claude-sonnet-4-20250514-v1:0` (Sonnet 4). Parser calls `get_llm("parser")` which resolves to Haiku at temperature=0.0, max_tokens=2048 (Stage 1) or 8192 (Stage 2). | The AC parser is running on Haiku, not Sonnet. Framing brief assumed Sonnet. This is a significant gap — upgrading Stage 1 or Stage 2 to Sonnet (or Claude 3.5 Sonnet with extended thinking) is a discrete intervention that does not require prompt changes. |
| `backend/engine/ac_parser.py:452–453` | Stage 2 max_tokens | B | Stage 2 compiler requests `max_tokens=8192`, Stage 1 requests `max_tokens=2048`. | 2048 may be insufficient for complex multi-scenario tickets. Haiku's 200K context is fine but output truncation at 2048 tokens on Stage 1 could cause `_repair_json` to run unnecessarily. |
| `backend/engine/ac_parser.py:474–595` | Retry mechanism | B | Stage 2 has a `MAX_COMPILE_RETRIES=2` loop that feeds Pydantic `ValidationError` and `JSONDecodeError` messages back to the LLM as `HumanMessage` with targeted hints. Provides a `transient/ephemeral` selector-specific hint on retry. Stage 1 has NO retry. | This is a working self-correction loop. It is a concrete reusable pattern. However, the validation error text fed back is raw Pydantic output — a cleaner targeted-hint approach (like the `transient/ephemeral` case) would improve self-correction rates. |
| `backend/engine/ac_parser.py:183–248` | `_repair_json` | B | Iterative right-trim bracket-closing repair that handles max_tokens truncation. Runs up to 500 iterations. | Sophisticated fallback but its presence signals the LLM regularly produces truncated JSON. This is a symptom, not a cure — better output format enforcement would reduce reliance on this. |
| `backend/engine/ac_quality_gate.py:668–800` | AC Quality Gate | B | Zero-LLM-cost rule-based scorer on 5 dimensions (Specificity, Observable Outcome, Actionability, Precondition Clarity, Scope Atomicity), 0–10 scale. GOOD (7–10) proceeds; FAIR (4–6) triggers FAIR Guardrail (block + operator review); POOR (0–3) hard-rejects. | The gate operates on raw text, before any enrichment. It does not evaluate whether the LLM-compiled JSON plan was accurate — it only evaluates input quality. There is no equivalent output quality gate on the Stage 2 test plan. |
| `backend/engine/ac_parser.py:1063–1143` | FAIR Guardrail (TASK-096/FEAT-077) | B | A HITL checkpoint already exists AT AC PARSING TIME for FAIR-grade tickets. Uses `asyncio.Event` to block `ac_parser_node` and broadcasts `pre_parse_guidance_required` WS event. Frontend shows a guidance panel. Operator either provides text or clicks "Proceed Anyway". | This is a pre-parse HITL checkpoint — exactly the design pattern DRP-003 asks about. It is active in production. The gap is that it only fires for FAIR-graded tickets; there is no equivalent checkpoint for reviewing/correcting the COMPILED TEST PLAN before execution proceeds. |
| `backend/engine/ac_parser.py:928–998` | Override AC steps | B | `override_ac_steps` in `VQAState` lets the frontend user edit AC steps in a review screen before execution. If set, `ac_parser_node` re-runs Stage 2 on a minimal synthetic BDD from the user's goals. | This is a second, distinct HITL point: post-parse step editing. It re-invokes Stage 2 but on a degraded synthetic BDD ("When {goal} / Then verify"), losing the richer BDD context that Stage 1 produced. |
| `backend/engine/schemas.py:161–296` | TestPlan schema | B | `TestPlan` → `StructuredACStep` → `Verification`. `StructuredACStep` has: `step_id`, `goal`, `step_type` (11 Literal values), `preconditions`, `target_component`, `verification` (list of `Verification`), `fallback_strategy`, `max_actions`, `target_element_types`, `input_value`, `target_persona`, `target_user`, `sub_steps`, `post_action_wait_ms`. `Verification` has: `type` (9 Literal values), `selector_hint` (with `reject_transient_selectors` validator), `expected_text`, `expected_state`, `url_pattern`, `status_code`, `expected_column`, `expected_direction`. | The schema is DEEP and well-typed. 13+ downstream consumers read `acceptance_criteria_steps` (legacy flat list). Changing the schema structure would require updating every consumer. Adding optional fields to `StructuredACStep` or `Verification` is safe; removing or renaming existing fields is a TRAP. |
| `backend/engine/human_takeover.py:972–1587` | `human_takeover_node` | B | Execution-time HITL: blocks on `asyncio.Event` with 5-minute timeout. Injects JS click-capture listener into browser. Captures full action sequence via `_human_action_sequence`. On resume: advances AC step index, writes to `human_guidance.md`, `vSuite-actions.md`, `learned_workflows.json`, persistent SQLite memory, and `selector_registry.json`. Returns `_next_node: "planner"` or `"reporter"`. | This is EXECUTION-time HITL (triggered when the agent gets stuck), not PARSE-time HITL. It is architecturally distinct from the FAIR Guardrail. Adding a parse-result review HITL (post-Stage-2, pre-execution) would need a new LangGraph node or a modified `ac_parser_node` path. |
| `backend/engine/human_takeover.py:55–99` | HITL state dictionaries | B | Uses module-level dicts (`_takeover_events`, `_takeover_data`, `_WS_BROADCAST_FN`, `_WS_SCREENSHOT_FN`, `_WS_ACTION_FN`, `_WS_DIALOG_FN`, `_last_human_click`, `_human_action_sequence`, `_pending_dialogs`) keyed by `run_id`. Callbacks injected by `routes.py` at startup to avoid circular imports. | A new pre-execution test-plan review HITL checkpoint could reuse this same pattern: module-level event dict + injected WS broadcast callback. The `asyncio.Event` + WS broadcast architecture is the established convention. |
| `scripts/benchmark_pipeline.py:88–178` | Golden 10 benchmark | B | Benchmark measures: (1) parser success (non-empty `acceptance_criteria_steps`), (2) step coverage via fuzzy `SequenceMatcher` ratio > 0.8 against `expected_steps`, (3) AC quality score, (4) full E2E step verification (if `--full`). Does NOT measure: test plan schema correctness, `step_type` accuracy, `verification` assertion quality, or `target_component` accuracy. | The benchmark measures "did parsing produce steps" and "do step texts roughly match expected", not "is the compiled TestPlan a correct and executable plan". This is the evaluation gap identified in DRP-001. A new benchmark dimension measuring JSON schema fidelity (correct step types, valid selectors, correct verification types) would directly measure the improvement the spike is targeting. |
| `tests/benchmarks/golden_10_data.json:1–80+` | Golden 10 dataset | B | 10 cards from the QA project (`QA-170`, `QA-185`, `QA-172`, ...). Each has `acceptance_criteria`, `expected_steps` (Given/When/Then format), `summary`, `description`, `tier`, `category`, `automatable`, `step_count`. Cards are real vSuite tickets. No field for expected `test_plan` JSON, `step_type`, or `verification` assertions. | Golden 10 covers AC parsing coverage but not JSON Compiler fidelity. Extending the dataset with `expected_test_plan` structures (or at minimum `expected_step_types` per step) would enable a Stage 2-specific regression test. |
| `backend/engine/ac_enricher.py:1–100` | AC Enricher (FEAT-002) | B | Zero-LLM-cost KB enrichment stage that runs BEFORE Stage 1. Detects domain themes (table_sort, quick_order, voice_workflow), queries TF-IDF KB, and appends `<domain_context>` XML blocks to the raw AC text. | This is the RAG-augmentation layer for Stage 1. It injects structured domain knowledge pre-parse. A few-shot example layer would complement this by showing Stage 1 WHAT GOOD BDD LOOKS LIKE for these domains. |
| `backend/engine/ac_parser.py:361–413` | Stage 1 human guidance injection | B | `pre_parse_guidance` appended to `BDD_NORMALIZER_PROMPT` with explicit separator banners after the base prompt. KB-fetched guidance for the ticket also prepended via `_merged_user_guidance`. | The prompt assembly order is: base BDD_NORMALIZER_PROMPT + pre_parse_guidance appended. The human guidance sits at the RECENCY position — consistent with the Primacy/Recency anchoring pattern. |
| `backend/engine/ac_parser.py:624–685` | Legacy fallback parser | B | A flat-list fallback runs if the two-stage pipeline fails. Uses a minimal prompt: "Parse into 5-12 numbered goal strings, JSON array". No BDD, no schema, no visual context. | The fallback degrades gracefully but loses all structured information. If Stage 2 fails consistently due to a model limitation, runs silently degrade to this flat mode (surfaced as `parse_quality: "degraded"`). |
| `memory-bank/systemPatterns.md:59–66` | Prompt Hardening Standards | A | Documented convention: XML-style tags, Primacy/Recency anchoring, few-shot for domain-specific failure modes, and a `knowledge/prompt_audit_checklist.md`. | Any prompt engineering change to `BDD_NORMALIZER_PROMPT` or `JSON_COMPILER_PROMPT` MUST pass the checklist at `knowledge/prompt_audit_checklist.md`. This is an A-grade constraint. |
| `memory-bank/systemPatterns.md:89–94` | Two-Stage AC Parsing pattern | A | Documented architectural pattern: "separation of concerns makes each stage independently testable and debuggable." | Any proposal that merges Stage 1 and Stage 2 into a single LLM call would violate this documented pattern. Adding a Stage 0 (enrichment) or Stage 3 (validation) is structurally consistent. |

---

## TRAP Candidates

**TRAP-1: Schema breakage risk — 13+ downstream consumers of `acceptance_criteria_steps`**
`acceptance_criteria_steps` is read by 13+ downstream consumers (planner, executor, reporter, benchmark, etc.) identified in the dual-write commentary at `ac_parser.py:26–40`. Changing the `TestPlan` JSON structure (field renames, type changes, removing `goal`) would silently break these consumers. New optional fields on `StructuredACStep` are safe; any existing field removal or type change is a hard compatibility break. Verify all consumers before proposing schema changes.

**TRAP-2: Model tier confusion — parser runs on Haiku, not Sonnet**
The framing brief assumed "Claude 3.5 Sonnet" for the parser. The actual default is `claude-haiku-4-5-20251001-v1:0` (`backend/config.py:207–215`). Upgrading the parser to Sonnet would increase cost significantly (Haiku is ~20x cheaper per `provider.py:19`). The `heavy=True` flag exists in the factory but is not wired to the parser. Adding `get_llm("parser", heavy=True)` for Stage 2 only is the minimal viable model upgrade path.

**TRAP-3: Tool-use / JSON-mode is NOT used for Stage 2**
Stage 2 uses `ainvoke(messages)` with a raw string output and relies on `_repair_json` + Pydantic validation + retry for schema enforcement. The Bedrock `toolConfig` / `tool_use` mechanism (already implemented for the planner in `schemas.py:986–1029`) is NOT applied to Stage 2. Adding `PLANNER_TOOL_CONFIG`-style tool enforcement to Stage 2 would enforce schema compliance at the API level, but requires the `ChatBedrockConverse` binding to support `tool_use` forcing — the same `langchain-aws` version already does this for the planner, so compatibility is likely but needs verification.

**TRAP-4: Adding a LangGraph node between `ac_parser_node` and `setup_role_node` requires graph.py changes**
The documented node graph (`systemPatterns.md:25–36`) is `jira_fetch_node → ac_parser_node → setup_role_node`. Adding a "test plan review" node between `ac_parser_node` and `setup_role_node` requires modifying `backend/engine/graph.py`. This is low-risk but must be done carefully — the LangGraph `StateGraph` wiring must preserve all existing edges and the `_next_node` routing pattern.

**TRAP-5: `override_ac_steps` re-compiles from degraded BDD**
When users edit AC steps via the review screen (`override_ac_steps`), Stage 2 re-runs on a synthetic BDD: `"When {goal} / Then verify the action completed correctly"`. This loses all context from Stage 1. The planner then receives a test plan compiled from this thin BDD, which may produce lower-quality `verification` assertions than the original pipeline. This is a latent quality gap that any HITL review feature must account for.

**TRAP-6: Benchmark does not measure Stage 2 JSON fidelity**
The Golden 10 benchmark (`scripts/benchmark_pipeline.py:98–109`) measures parser success (non-empty steps) and fuzzy step-text coverage, not `step_type` correctness, `target_component` accuracy, or `verification` assertion validity. Any improvement to Stage 2 prompt quality cannot be measured with the current benchmark dataset or metrics without extending `golden_10_data.json` with ground-truth `test_plan` fields.

---

## Open Questions

1. **`knowledge/prompt_audit_checklist.md` content** — Referenced in `systemPatterns.md:64` as a mandatory review artifact for prompt changes, but not read in this lane. What specific checks does it enforce that constrain Stage 1/2 prompt engineering options?

2. **`backend/profiles.py`** — Stage 2 calls `get_active_profile()` to obtain `domain_glossary_section` and `system_boundary_rule` (`ac_parser.py:457–464`). The profile content directly influences JSON Compiler output quality, but this file was not read. What profiles exist and how complete are the domain glossaries?

3. **`backend/engine/state.py` — `detected_paths` and `ambiguities` fields** — These fields are returned by `ac_parser_node` but do not appear in the main `VQAState` TypedDict (not found in grep). Are they accepted as untyped extra keys by LangGraph, or are they declared in a section of state.py not captured by the grep pattern?

4. **LangGraph checkpointer behavior on FAIR guardrail** — `routes.py:523–558` mentions a "checkpointer for pause/resume state updates." Is the FAIR Guardrail `asyncio.Event.wait()` integrated with LangGraph's checkpointer (allowing resume after process restart), or is it only an in-memory event that is lost on server restart?

5. **Actual AC parsing failure mode distribution** — The benchmark measures binary parser success but has no breakdown of Stage 1 vs Stage 2 failure rates, or which specific schema validation errors most commonly trigger the retry loop. This is the empirical data needed to prioritize interventions.

---

### Existing Patterns

| Pattern | Location (file:line) | Relevance |
|---|---|---|
| XML structural prompt delimiters | `prompts.py:43–100` (BDD), `prompts.py:108–189` (JSON) | Any new prompt must use `<GOLDEN_RULES>`, `<RULES>`, `<CRITICAL_REMINDER>` structure |
| Primacy/Recency prompt anchoring | `systemPatterns.md:59–62` (documented), `ac_parser.py:373–382` (human guidance at recency) | Critical rules should appear at start AND end of system prompts |
| `asyncio.Event` HITL pause/resume | `human_takeover.py:55–60`, `ac_parser.py:1088–1111` | Reusable pattern for any new HITL checkpoint: module-level `dict[str, asyncio.Event]` + WS broadcast callback |
| Pydantic retry loop with targeted hints | `ac_parser.py:474–595` | Stage 2 self-correction loop is reusable; same pattern for adding a Stage 1 retry |
| `ChatBedrockConverse` tool-use forcing | `schemas.py:986–1029` (PLANNER_TOOL_CONFIG) | Technique for enforcing JSON schema at the Bedrock API level — already works in the same stack |
| Dual-write backward compatibility | `ac_parser.py:26–40` | Pattern for introducing new structured output while preserving legacy consumers |
| KB TF-IDF RAG enrichment before LLM | `ac_enricher.py` (full file) | Zero-LLM-cost context injection — reusable pattern for Stage 1 few-shot retrieval |
| Prompt budget trimmer | `prompt_budget.py` (referenced at `systemPatterns.md:231–235`) | Any new prompt additions must respect token budgets; use `prompt_budget.py` |

---

### Compatibility Constraints

- **Model upgrade cost**: Switching parser from Haiku to Sonnet would increase per-run LLM cost by approximately 20x for parsing calls. Applies only to Stage 2 if using `heavy=True` selectively.
- **`TestPlan` schema is frozen for existing consumers**: Removing or renaming any field in `StructuredACStep` or `Verification` breaks 13+ consumers. Only additive changes (new optional fields) are safe.
- **`langchain-aws` `ChatBedrockConverse` binding**: Tool-use forcing for Stage 2 requires this library to support `toolConfig` with `"toolChoice": {"tool": ...}` — already validated for the planner but not tested for the parser role.
- **`knowledge/prompt_audit_checklist.md`**: All prompt modifications must pass this checklist (documented requirement, A-grade). Content unknown — must be read before submitting any prompt PR.
- **LangGraph `StateGraph` wiring**: Adding a node to the graph requires `backend/engine/graph.py` changes. The graph uses `_next_node` string routing via conditional edges; any new node must integrate with this routing pattern.
- **`_repair_json` dependency**: The presence of `_repair_json` as a production dependency indicates Stage 2 regularly produces malformed JSON. Removing it would be unsafe unless structured output enforcement is verified to produce zero truncation on all Golden 10 cards.
- **Bedrock inference profiles**: Both model IDs use `us.` prefix (cross-region inference profiles). Swapping to a different model family (e.g., Amazon Nova) would require new inference profile ARNs configured in `.env` — not just a string change.
