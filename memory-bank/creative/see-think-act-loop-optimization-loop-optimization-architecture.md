# Architecture Decision: See-Think-Act Loop Optimization

**Created**: 2026-06-02
**Status**: DECIDED
**Decision Type**: Architecture

## Context

### System Requirements
- **Dense Semantic Embeddings**: Replace TF-IDF retrieval for human guidance matching with a ChromaDB-backed local vector store query.
- **Semantic DOM Culling**: Prune structural boilerplate and empty wrapper elements from the accessibility tree, achieving a ≥40% character reduction before sending to the planner.
- **VLM/Local Model Split-Execution**: Implement semantic actions (`semantic_click` and `semantic_fill`) that locate screen coordinates locally, bypassing visual Set-of-Marks overlays.

### Technical Constraints
- Must run locally without requiring external paid embedding APIs (e.g. OpenAI).
- Must execute quickly; culling and local element resolution must add < 500ms of overhead.
- Must preserve all interactive elements and landmarks in the culling pass.
- Must fall back gracefully to standard execution paths if local resolution fails.

### Non-Functional Requirements
- **Performance**: Single-ticket execution time reduced by ≥30%.
- **Token Efficiency**: Accessibility tree character footprint reduced by ≥40%.
- **Reliability**: Zero-shot RAG retrieval precision improved by ≥25%.

---

## Component Analysis

### Core Components
| Component | Purpose | Responsibilities |
|-----------|---------|------------------|
| `HumanGuidanceVault` | ChromaDB vector store wrapper in `backend/kb/rag.py` | Indexes `human_guidance.md` using `all-MiniLM-L6-v2` local embeddings. Queries guidance semantically. |
| `SemanticDOMCuller` | ARIA tree optimizer in `backend/engine/culler.py` | Parses raw ARIA tree text, builds a tree representation, prunes non-interactive/non-landmark branches, and serializes back. |
| `LocalObjectDetector` | Coordinate resolver in `backend/browser/vision_utils.py` | Extracts bounding boxes and text of DOM elements; uses fuzzy match to map a target label to exact `(x, y)` coordinates. |
| `VQAExecutor` | Action execution engine in `backend/engine/executor.py` | Dispatches clicks/actions directly to resolved coordinates, bypassing SoM rendering. |

### Component Interactions
```
[AC Step] ──▶ [HumanGuidanceVault] (Semantic RAG) ──▶ [Matched hint]
                                                           │
                                                           ▼
[Planner Node] ──▶ [Extract ARIA] ──▶ [SemanticDOMCuller] ──▶ [Pruned Tree (≥40% smaller)]
      │                                                            │
      ▼ (Bedrock Claude 3.5 Sonnet)                                │
[Semantic Action (e.g. click "Save button")]                       │
      │                                                            │
      ▼                                                            ▼
[Executor Node] ──▶ [LocalObjectDetector] (fuzzy matches target to DOM coords) ──▶ [mouse.click(x, y)]
```

---

## Options Explored

### Option 1: Live Browser DOM Manipulation & Visual SoM Coordinates
- **Description**: Mutate the browser DOM styles to hide elements (culling), capture screenshot with Set-of-Marks IDs, and use the VLM to select element ID.
- **Pros**:
  - Leverages existing SoM infrastructure.
- **Cons**:
  - Visual overlay drawing is slow (~1.5s per screenshot).
  - Screenshots are cluttered with red bounding boxes.
  - DOM mutation can visually disrupt noVNC stream and break Angular re-renders.

### Option 2: Hybrid Text-based Culling & Local Coordinate Resolution (Chosen)
- **Description**:
  1. Capture raw ARIA tree; run string parsing culler in Python (`SemanticDOMCuller`) to prune empty containers.
  2. Planner Claude Sonnet sees a clean screenshot and pruned text tree, then outputs semantic target.
  3. `LocalObjectDetector` extracts interactive DOM bounds from Playwright and fuzzy matches the target label using Python token matching to resolve `(x, y)` coordinates.
- **Pros**:
  - Bypasses slow SoM rendering, reducing loop cycle time by ~1.5s per action.
  - Zero modifications to the live page DOM (safe, avoids breaking inputs).
  - Screenshots are completely clean.
  - Culling is measured precisely in Python via string length comparison.
- **Cons**:
  - Element matching relies on DOM metadata matching target description (requires robust fuzzy matching logic).

---

## Evaluation Matrix

| Criteria | Option 1 | Option 2 |
|----------|----------|----------|
| Scalability | Medium | High |
| Maintainability | Medium | High |
| Performance | Low (slow SoM) | High (fast local resolver) |
| Security | High | High |
| Observability | Medium | High (metrics logged) |
| Implementation Cost | Low | Medium |

---

## Observability Architecture

### Logging
- **Log Format**: Structured JSON with traceId.
- **Key Metrics Logged**:
  - `Pruned ARIA tree from X chars to Y chars (Z% reduction)` (Info level).
  - `RAG guidance match count and cosine similarity score` (Debug level).
  - `Local resolution target: "Target" matched to element "[role] "Name"" with confidence score S` (Info level).

### Distributed Tracing
- Trace context is propagated through FastAPI to background ChromaDB indexing tasks.

---

## Decision

**Chosen**: Option 2 - Hybrid Text-based Culling & Local Coordinate Resolution

### Rationale
This approach eliminates the rendering bottleneck of Set-of-Marks visual overlays while preserving the accuracy of coordinate-based clicks. Python-side culling is completely non-destructive to the browser session, and fuzzy matching ensures the planner's semantic targets (e.g. "Save button") map reliably to close matches in the DOM (e.g. "Save All").

### Trade-offs Accepted
- Slight CPU increase in Python due to local sentence embeddings and string tree traversal (negligible, ~15ms total).
- High reliance on DOM elements exposing valid names/text in the accessibility tree (mitigated by falling back to full visual SoM if resolution fails).

---

## Implementation Guidelines

### 1. Dense Semantic Embeddings (`backend/kb/rag.py`)
- Define class `HumanGuidanceVault` initialized with local `chromadb.PersistentClient(path="storage/chromadb")`.
- Use `embedding_functions.DefaultEmbeddingFunction()` (local `all-MiniLM-L6-v2`).
- On startup, read `knowledge/human_guidance.md`. Split on `## WORKFLOW:` into document chunks. Upsert documents into collection `human_guidance` with title as ID and metadata `{"type": "human-guidance"}`.
- Provide `query(text: str, max_results: int = 1)` that returns matched chunks. Integrate in `loader.py` to intercept queries.

### 2. Semantic DOM Culling (`backend/engine/culler.py`)
- Implement `SemanticDOMCuller` with `semantic_dom_cull(aria_tree: str) -> str`.
- Algorithm:
  1. Parse indented text lines into a Node hierarchy.
  2. Classify nodes: `is_interactive` (role in `INTERACTIVE_ROLES`), `is_safety` (role in `dialog`, `alert`, `navigation`, `tab`, `main`, `heading`, `form`), or `is_boilerplate` (empty `[generic]`, `[none]`, `[presentation]`).
  3. Prune tree bottom-up: keep a node if it is interactive, safety, or has any descendant that is kept.
  4. Serialize kept nodes back to indented text.
- Integrate in `planner.py` before prompting Bedrock, logging character reduction details.

### 3. Coordinate Resolution (`backend/browser/vision_utils.py` & `backend/engine/executor.py`)
- Update `PlannerAction` schema to support actions: `"semantic_click"` and `"semantic_fill"`.
- Implement `LocalObjectDetector.resolve_target(page, target: str) -> tuple[int, int]`:
  1. Evaluate JS script in Playwright to extract all clickable/interactive element rects and text labels.
  2. Run fuzzy matching (ratio of label match, overlap) between target text and elements.
  3. Return center `(x, y)` of highest-scoring element.
- Executor calls resolver and runs `page.mouse.click(x, y)` or `page.mouse.click(x, y)` then types value.

---

## Validation Checklist
- [x] Meets all system requirements
- [x] Respects technical constraints
- [x] Addresses non-functional requirements
- [x] Technically feasible
- [x] Risks identified and acceptable
- [x] Complies with Guiding Principles in systemPatterns.md
- [x] Observability architecture defined

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Local resolver selects incorrect element due to poor labeling | Medium | High | Fall back to standard Playwright locators or visual SoM on failure; check confidence score before executing. |
| Local embedding database fails to initialize | Low | Medium | Graceful fallback to legacy TF-IDF matcher. |
| Culler accidentally prunes essential parent containers | Low | High | Protect all safety roles (`dialog`, `alert`, `navigation`, `tab`, etc.) and ensure any node with interactive children is preserved. |

---

## Next Steps

1. Create `backend/engine/culler.py` containing `SemanticDOMCuller`.
2. Create `backend/kb/rag.py` containing `HumanGuidanceVault`.
3. Integrate `culler` and `rag` into `planner.py` and `loader.py`.
4. Implement coordinate resolution in `vision_utils.py` and update executor.
5. Create unit tests in `tests/test_task_094_loop_optimization.py`.
