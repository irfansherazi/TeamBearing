## Spike Card: Deep Research Probe DRP-002 — TypeScript Import Graph Analysis
**Work slug**: vqa-planner-retrieval   |   **Status**: COMPLETE
**run_id**: 20260717-9a2c2120fe42
**framing_sha**: 9a2c2120fe42
**approved_depth**: deep
**approved_lanes**: academic, oss-production, practitioner-discourse, official-docs, codebase
**MCP used**: WebSearch/WebFetch chain (not applicable — codebase-only probe)
**mcp_servers_available**: none (codebase analysis probe; no web retrieval required)
**fallback_used**: no (direct filesystem reads; codebase lane)
**Sources consulted**: 11 (6 helper .ts files, playwright_rag.py, setup.ts, exportUtils.ts, OrderHelper.ts imports, test file import survey)

---

### Findings

| Source | Type | Evidence Grade | Key Finding | Implications |
|--------|------|----------------|-------------|--------------|
| `playwright/utils/QO_helpers.ts` (635 lines) | code | B | Zero imports from any other helper; imports only from npm (`@playwright/test` is not even imported — QO_helpers has NO imports at all). Exports 14 items (11 functions + 3 constants). Pure utility leaf node. | QO_helpers is a pure utility leaf — pulling it as a dependency adds 635 lines / 14 symbols, all useful (date calculators, random generators, demo scripts). Zero false-positive risk for transitive pull. |
| `playwright/utils/OrderHelper.ts` (2,223 lines) | code | B | Imports `@playwright/test` (external) and 6 named symbols from `./QO_helpers` (only cross-import in the entire 6-file graph). Exports 15 async functions. Largest file by 3.5x. | Pulling OrderHelper via dependency-aware retrieval would also pull QO_helpers — a net injection of ~2,858 lines / 29 functions. QO_helpers symbols used by OrderHelper (generateRandomSpotTitle, generateRandomISCI, calculateDueDate, calculateStartDate, calculateEndDate, generateUniqueClientName) are all directly relevant to Order form tasks, so this is a **true positive pull, not a false positive**. |
| `playwright/utils/NavHelper.ts` (306 lines) | code | B | Imports `@playwright/test` and `BASE_URL` from `./setup`. No imports from any of the other 5 helpers. Exports 6 async functions. | NavHelper is functionally isolated from all 5 siblings. Pulling it adds 306 lines, 6 functions. Transitive closure = NavHelper + setup.ts (config constants only). No bloat risk. |
| `playwright/utils/SearchHelper.ts` (617 lines) | code | B | Imports `@playwright/test` and `BASE_URL` from `./setup`. No cross-imports. Exports 6 async functions. | SearchHelper is isolated. Transitive closure = SearchHelper + setup.ts. No false-positive pull from other helpers. |
| `playwright/utils/ViewHelper.ts` (712 lines) | code | B | Imports only `@playwright/test` — no local imports at all. Exports 14 items (13 async + 1 sync function). | ViewHelper is a complete island — zero transitive local dependencies. Pulling it injects exactly 712 lines / 14 functions, nothing else. |
| `playwright/utils/FirmOptionsHelper.ts` (274 lines) | code | B | Imports `@playwright/test` and `BASE_URL, STORAGE_DIR` from `./setup`. No cross-imports from other helpers. Exports 6 items. | FirmOptionsHelper is isolated. Transitive closure = FirmOptionsHelper + setup.ts. Minimal footprint (274 lines). |
| `playwright/utils/setup.ts` (shared dependency) | code | B | Exports `BASE_URL`, `STORAGE_DIR`, `SHARED_TEST_PASSWORD`, `test` (fixture), `expect`, `ENV_TIMEOUT_MULTIPLIER`, and helpers. Imported by NavHelper, SearchHelper, FirmOptionsHelper (and OrderHelper transitively via QO_helpers which does NOT import setup.ts). | setup.ts is a config/fixture re-export module — it is not a "helper" with test logic. If included in transitive closure it adds boilerplate, not test logic. Approximately 150 lines of substantive content. |
| Cross-import survey (all 6 helpers) | code | B | **Only one cross-import exists in the entire 6-file graph**: `OrderHelper.ts` imports 6 symbols from `QO_helpers.ts`. The other 4 helpers (NavHelper, SearchHelper, ViewHelper, FirmOptionsHelper) have zero inter-helper imports. No helper imports from OrderHelper. No helper imports from NavHelper, SearchHelper, ViewHelper, or FirmOptionsHelper. | The import graph is a shallow DAG with a single internal edge: `QO_helpers → OrderHelper`. It is NOT a tightly-coupled mesh. Fan-in to QO_helpers is 1 (only OrderHelper). Fan-out from any node is 0 or 1. |
| Test file import frequency survey (50 import lines, 22 test files) | code | B | OrderHelper is imported by 15 test files (most used). ViewHelper: 13. QO_helpers: 9. NavHelper: 9. SearchHelper: 8. FirmOptionsHelper: 2. No test file imports all 6. The most heavily linked test (`qa-101-client-merging.test.ts`) imports 6 symbols across 6 import lines — all 5 main helpers. | High import diversity means the retrieval problem is real: each test uses a different helper subset. A graph-overlay approach would need to resolve the correct 1-2 helpers per AC step, not all 6. |
| No barrel/index files | code | B | `find playwright/ -name "index.ts"` returns no results. `exportUtils.ts` is a separate utility (print/download helpers), not a barrel re-exporting the 6 helpers. No re-export aggregator exists. | Each helper must be imported directly by filename. No single entry point exists that would cause accidental whole-graph pulls. This makes dependency-aware retrieval simpler (no barrel to follow). |
| `backend/kb/playwright_rag.py` (current RAG) | code | B | Chunks by blank-line boundaries within each file. Import lines are skipped during chunking. The TF-IDF index treats each chunk independently — no dependency graph is consulted. `max_results=2` by default. File-level attribution is preserved (`source_file` field). | Current RAG has no graph awareness. A query for "create Quick Order Radio Commercial" may return a chunk from OrderHelper.ts without pulling the QO_helpers data generators it depends on, unless those symbols happen to appear in the same chunk. This is the real failure mode the probe is measuring. |
| `backend/engine/generator_node.py` + `codegen_transformer.py` (static mappings) | code | B | The generator node already hard-codes which helpers apply to which AC step types (search → SearchHelper, QO form → QO_helpers + OrderHelper) as static prompt strings. This is a manual pre-mapping that partially compensates for RAG misses. | The existing hard-coded static mapping is a partial substitute for graph-overlay retrieval — but only for the known helper patterns. New helpers or edge-case steps fall through to pure RAG. |

---

### TRAP Candidates

**TRAP-CANDIDATE-1 — OrderHelper size bloat**: At 2,223 lines / 15 exported functions, pulling OrderHelper as a graph transitive dep means injecting ~3,500 lines into the planner context (OrderHelper + QO_helpers combined). The current `prompt_budget.py` applies aggressive trimming. If graph-overlay adds OrderHelper whenever QO_helpers matches, the injected tokens could exceed the budget ceiling before the planner sees the actual AC steps. This is a **context-window budget risk**, not a correctness risk — the pulled code is relevant, but the volume is high. Worth profiling against the prompt_budget caps before committing.

**TRAP-CANDIDATE-2 — False-positive rate is near-zero, so graph-overlay adds little incremental value**: The import graph has only 1 internal edge (QO_helpers → OrderHelper). The 4 other helpers are completely isolated. A dependency-aware retrieval system that "pulls a file plus its imports" would only have meaningful behavior for one out of six files (OrderHelper → QO_helpers). For the other 5, graph overlay = function-level chunking with no difference. The complexity of building and maintaining a graph parser is high relative to the marginal benefit of pulling one extra file.

**TRAP-CANDIDATE-3 — setup.ts as transitive noise**: Three helpers (NavHelper, SearchHelper, FirmOptionsHelper) import from `./setup`. A naive transitive-closure puller would include setup.ts in all three helpers' dependency sets. setup.ts contains fixture boilerplate (`test.extend<>`, storage-state lookups) that is **irrelevant** to planner context injection. This is a genuine false positive — setup.ts is not a "helper" and adds token noise.

---

### Open Questions

1. Does `prompt_budget.py` have a hard ceiling on injected helper code, and would OrderHelper + QO_helpers combined (~3,500 lines, estimated ~5,000 tokens) fit within that ceiling per planner step? This cannot be answered from the import graph alone.

2. Would a simpler alternative — **filename routing** (map AC step keywords → helper filenames directly, without graph traversal) — achieve equivalent recall with lower maintenance cost? The 6-helper corpus is small enough that a static routing table could cover all cases.

3. The import graph is stable today (1 edge), but the framing brief mentions helpers change across sprints. Is there a mechanism to detect when a new cross-import is added and rebuild the graph? Without auto-detection, a stale graph becomes a latent false-negative risk.

4. QO_helpers exports `validFakeClients` (a large array) and `demoScripts` / `demoNotes` (constant strings, ~200 lines combined, lines 594–635). These constants are rarely needed by the planner — they are pre-built data payloads for specific tests. If QO_helpers is pulled as a dependency, these constants inflate token usage. Function-level chunking would exclude them; file-level graph pull would include them.

---

### Import Graph (Full Adjacency Map)

```
QO_helpers.ts  ──────────────────────────────────────────────  [leaf: no local imports]
  └─ (imported by) OrderHelper.ts

OrderHelper.ts  ─── imports from ──────────────────────────── QO_helpers.ts
  └─ (imported by) 15 test files

NavHelper.ts  ─── imports from ──────────────────────────────  setup.ts (BASE_URL only)
  └─ (imported by) 9 test files

SearchHelper.ts  ─── imports from ────────────────────────────  setup.ts (BASE_URL only)
  └─ (imported by) 8 test files

ViewHelper.ts  ──────────────────────────────────────────────  [leaf: no local imports]
  └─ (imported by) 13 test files

FirmOptionsHelper.ts  ─── imports from ──────────────────────  setup.ts (BASE_URL, STORAGE_DIR only)
  └─ (imported by) 2 test files

setup.ts  ─── (shared config, not a helper) ─────────────────  playwright.config (BASE_URL), loginHelper.mjs
```

**Summary**: The graph has exactly 1 inter-helper edge (OrderHelper → QO_helpers). The remaining 3 helpers that import from setup.ts are pulling config constants, not helper logic. There are NO cycles. There are NO multi-hop transitive dependencies (no helper imports a helper that imports another helper).

---

### Function Count Table (per file)

| File | Lines | Exported functions/constants | Private functions | Total symbols |
|------|-------|------------------------------|-------------------|---------------|
| QO_helpers.ts | 635 | 14 (11 fn + 3 const) | 0 | 14 |
| OrderHelper.ts | 2,223 | 15 | 6 | 21 |
| NavHelper.ts | 306 | 6 | 0 | 6 |
| SearchHelper.ts | 617 | 6 | 0 | 6 |
| ViewHelper.ts | 712 | 14 | 1 | 15 |
| FirmOptionsHelper.ts | 274 | 6 | 0 | 6 |
| **Total** | **4,767** | **61** | **7** | **68** |

---

### Transitive Closure Injection Estimates (per matched file)

| Matched file (RAG hit) | Transitive deps (internal) | Files pulled | Total lines injected | Total exported fn | False-positive pull? |
|------------------------|----------------------------|--------------|----------------------|-------------------|----------------------|
| QO_helpers.ts | none | 1 | 635 | 14 | no — exact match |
| OrderHelper.ts | QO_helpers.ts | 2 | 2,858 | 29 | no — QO_helpers symbols are directly used by OrderHelper |
| NavHelper.ts | setup.ts (config only) | 1+config | 306 + ~150 config lines | 6 | setup.ts adds noise (fixture boilerplate, not helper logic) |
| SearchHelper.ts | setup.ts (config only) | 1+config | 617 + ~150 config lines | 6 | setup.ts adds noise |
| ViewHelper.ts | none | 1 | 712 | 14 | no — exact match |
| FirmOptionsHelper.ts | setup.ts (config only) | 1+config | 274 + ~150 config lines | 6 | setup.ts adds noise |

**Practical false-positive rate**: 0% for OrderHelper → QO_helpers (relevant pull). ~15-20% token noise from setup.ts inclusion for NavHelper/SearchHelper/FirmOptionsHelper if graph traversal naively follows all imports. False-positive rate for irrelevant helper-to-helper pulls: **0%** — there are no spurious cross-imports between unrelated helpers.

---

### Verdict on Graph-Overlay Retrieval (evidence-based assessment — not a Phase 2 verdict)

The codebase evidence strongly suggests **function-level chunking within a single file is sufficient** for 5 of 6 helpers. The single case where graph-overlay adds value is OrderHelper (which uses QO_helpers date/name generators). A simpler solution for that case is to always inject QO_helpers alongside OrderHelper as a static co-injection rule — no graph parser required. The maintenance cost of a dynamic TypeScript AST graph builder outweighs the benefit of automating one known dependency edge that changes rarely.

The false-positive risk from the graph is near-zero (the graph is too sparse for spurious pulls), but the marginal benefit is also near-zero for the same reason. The cost-benefit argument favors the simpler alternative: function-level chunking + a 2-line static co-injection rule for OrderHelper.

Phase 2 synthesis should weigh this finding against DRP-001's dense-embedding recall results — if dense retrieval can close the QO_helpers/OrderHelper lexical mismatch at the function level, graph-overlay becomes fully redundant.
