# Creative Design: end-to-end-pipeline-optimization Pipeline Optimization

**Task**: end-to-end-pipeline-optimization
**Status**: IN_PROGRESS
**Focus**: End-to-End Pipeline Reliability

---

## 1. Jira Description Parsing & AC Normalization

### Current Limitations
- Markdown tables in Jira descriptions are often flattened or misparsed by the current LLM prompt.
- Complex nested lists lose their hierarchy.
- Implicit preconditions (e.g., "User is on the login page") are sometimes missed if not explicitly stated in the AC block, even if implied by the summary.

### Proposed Design: Structured Decomposition
Instead of a single "normalize" pass, use a structured extraction strategy:
1. **Structural Pre-processor**: Identify blocks (Tables, Lists, Blocks of text) before sending to LLM.
2. **Contextual Enrichment**: Inject the "implicit knowledge base" (e.g., if ticket mentions "Quick Order", always assume navigation to the Quick Order page is needed).
3. **Multi-Model Verification**: Use a smaller, faster model (Haiku) to check if the BDD output from the larger model (Sonnet) actually covers all points from the original text.

---

## 2. Planner & Executor: PrimeNG Reliability

### The PrimeNG "Shadow DOM" Problem
PrimeNG components often hide the native `<input>` or `<select>` and use overlays that append to the `<body>`.

### Proposed Design: Interaction Recipes
Instead of the Planner trying to "guess" the locator every time, we will formalize the **Recipe Strategy**:
1. **Component-First Planning**: When the Planner detects a `p-dropdown`, it MUST use the `p-dropdown` recipe from `component_registry.json`.
2. **Retry with Displacement**: If `click()` fails due to an intercept error, the Executor should:
   - Identify the intercepting element (e.g., a loading spinner or another overlay).
   - Wait for it to disappear.
   - If it's a "known" harmless overlay (like a tooltip), try `force=True` or a coordinate-based click.

### Proposed Design: Locator "Election"
The Planner will now propose a "Primary" and "Fallback" locator strategy in its JSON:
```json
{
  "action": "click",
  "strategy": "get_by_role",
  "role": "button",
  "name": "Submit",
  "fallback": {
    "strategy": "css_selector",
    "selector": "p-button[label='Submit']"
  }
}
```

---

## 3. Verifier Accuracy

### Current Limitations
- False positives when an action is successful but the UI hasn't updated yet.
- False negatives when a toast message disappears before the verifier can see it.

### Proposed Design: Temporal Verification
1. **State Snapshotting**: Capture DOM state *immediately* before and *immediately* after the action.
2. **Transient Cache**: Enhance the "Toast Capture" (toast-capture-enhancement) to be more robust, potentially using a MutationObserver in the browser context that pipes events back to the backend in real-time.
3. **Wait-then-Verify**: Implement a "Settling Time" for PrimeNG/Angular animations (default 300ms) before the Verifier starts its Tier 1 (Programmatic) checks.

---

## 4. Benchmark Strategy

### Script: `scripts/benchmark_pipeline.py`
- Load the "Golden 10" from a JSON/YAML file.
- Run the full graph for each.
- Compare result against "Expected Trace" (a sequence of expected successful steps).
- Output a JUnit-style XML or a Markdown table for the `progress.md`.

---

## 5. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-12 | Use "Primary/Fallback" locator schema | Increases executor resilience without extra LLM turns. |
| 2026-05-12 | Implement `Settling Time` in Verifier | Handles Angular animation latency (PrimeNG slide/fade). |
| 2026-05-12 | Structured Pre-processor for Parser | Ensures tables/lists are preserved before LLM normalization. |
