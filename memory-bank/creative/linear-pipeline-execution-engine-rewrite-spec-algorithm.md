# Algorithm Design: linear-pipeline-execution-engine-rewrite-spec Linear Pipeline Execution Engine

**Task**: linear-pipeline-execution-engine-rewrite-spec / FEAT-105  
**Date**: 2026-06-04  
**Author**: Creative Design Agent (aligned with PE sign-off guidelines)

---

## 1. Stateless Custom Selector Resolver (`vqaEngine.ts`)

To prevent microtask race conditions and keep the footprint well under the 40 LoC budget, `vqaEngine` must be a pure, stateless query function that operates without internal variables (other than parameters), caches, or mutation observers.

### Priority Chain Search
The custom engine resolves elements based on a strict sequential chain:
1. `data-vqa-id="<value>"` exact match
2. `aria-label="<value>"` exact match
3. `input[placeholder="<value>"]` exact match

### Active Overlay Scoping
If any active PrimeNG overlay dialog or sidebar is visible, the query search root must be dynamically restricted to that overlay. If multiple overlays exist, it targets the topmost/deepest nested visible overlay. If none exist, it searches the entire `document`.

### Legacy Selector Fallback Checking
To maintain backward compatibility with CSS/text selectors on un-tagged pages, a multi-tier pattern check `_isStandardSelector(selector)` determines if a query is a legacy fallback. When triggered, it logs a structured JSON `VQA_SELECTOR_FALLBACK` technical debt warning and delegates search to standard Playwright.

### TS Pseudocode/Implementation Concept
```typescript
// core/selectors/vqaEngine.ts (Pure stateless function, ~38 LoC)
export const vqaEngine = {
  query: (root: Document | Element, selector: string): Element | null => {
    // Check if the selector is a legacy CSS / standard query
    if (/^[#\.\[]|[\s\>\+\~]|^text=/.test(selector)) {
      console.warn(JSON.stringify({
        timestamp: new Date().toISOString(),
        level: "WARN",
        node: "Executor",
        message: "VQA_SELECTOR_FALLBACK",
        tenant_id: "global", // dynamic if available in context
        technical_debt_metrics: { selector, type: "legacy_css" }
      }));
      return (root as Element).querySelector?.(selector) || document.querySelector(selector);
    }

    // Scoped Root Determination: Locate active PrimeNG overlay or fallback to root
    const overlay = document.querySelector('.p-sidebar:not(.p-sidebar-hidden), .p-dialog:not(.p-dialog-hidden), [role="dialog"]');
    const searchRoot = overlay || root;

    // Resolve priority chain
    return searchRoot.querySelector(`[data-vqa-id="${selector}"]`) ||
           searchRoot.querySelector(`[aria-label="${selector}"]`) ||
           searchRoot.querySelector(`input[placeholder="${selector}"]`) ||
           null;
  },

  queryAll: (root: Document | Element, selector: string): Element[] => {
    if (/^[#\.\[]|[\s\>\+\~]|^text=/.test(selector)) {
      console.warn(JSON.stringify({
        timestamp: new Date().toISOString(),
        level: "WARN",
        node: "Executor",
        message: "VQA_SELECTOR_FALLBACK",
        tenant_id: "global",
        technical_debt_metrics: { selector, type: "legacy_css" }
      }));
      return Array.from((root as Element).querySelectorAll?.(selector) || document.querySelectorAll(selector));
    }

    const overlay = document.querySelector('.p-sidebar:not(.p-sidebar-hidden), .p-dialog:not(.p-dialog-hidden), [role="dialog"]');
    const searchRoot = overlay || root;

    const byId = Array.from(searchRoot.querySelectorAll(`[data-vqa-id="${selector}"]`));
    if (byId.length > 0) return byId;

    const byAria = Array.from(searchRoot.querySelectorAll(`[aria-label="${selector}"]`));
    if (byAria.length > 0) return byAria;

    return Array.from(searchRoot.querySelectorAll(`input[placeholder="${selector}"]`));
  }
};
```

---

## 2. Compile Gate Self-Healing Retry Loop

The Validate Node compiles the generated Playwright `.spec.ts` script. To prevent infinite self-healing loops and slow turnaround, a strict **1-retry cap** is enforced.

```
                  ┌────────────────────────┐
                  │    Generate Node       │◄───────────────────────┐
                  │ (Produce spec.ts file) │                        │
                  └───────────┬────────────┘                        │
                              │                                     │
                              ▼                                     │
                  ┌────────────────────────┐                        │
                  │  Validate Node (tsc)   │                        │
                  └───────────┬────────────┘                        │
                              │                                     │
                     [Does tsc compile?]                            │
                    /                   \                           │
                  YES                    NO                         │
                  /                       \                         │
                 ▼                         ▼                        │
          ┌─────────────┐         [Has retried before?]             │
          │ Open Gate   │         /                   \             │
          │ (Proceed)   │       YES                    NO ──────────┘
          └─────────────┘       /                       \ (Inject error to LLM,
                               ▼                         mark "has_retried = true")
                        ┌─────────────┐
                        │    Halt     │
                        │ (COMPILE_   │
                        │   FAILED)   │
                        └─────────────┘
```

### Algorithm Steps:
1. **Initialize Compiler Gate**: Run `npx tsc --noEmit --target es2022 --module commonjs <temp_spec_path>`.
2. **Success Path**: If exit code is `0`, parse imports and match selector keys used in `page.locator('vqa=<key>')` against `selectors.json` schema. If valid, exit Validate Node with `SUCCESS`.
3. **Failure Path (First Attempt)**:
   - Capture TypeScript error output.
   - Check retry counter (`retryCount === 0`).
   - If `0`, format error messages and inject a targeted correction prompt back to the Generate Node.
   - Set `retryCount = 1` and re-trigger Generate Node.
4. **Failure Path (Second Attempt)**:
   - If `retryCount === 1` and `tsc` fails again, halt execution.
   - Log OpenTelemetry structured JSON:
     `{"timestamp": "...", "level": "ERROR", "node": "Validate", "message": "COMPILE_FAILED", "tenant_id": "...", "error_details": "..."}`
   - Throw a hard, structured `CompileFailedException`.

---

## 3. Strict-Mode Execution Collision Auto-Regeneration

When the generated spec executes, strict-mode locator resolution may throw a multi-element matching exception (e.g., `Locator.click: strict mode violation: locator('vqa=submit_btn') resolved to 3 elements`). The system captures this and performs a parent-scoped self-healing loop.

```
                      ┌───────────────────────┐
                      │     Generate Node     │◄───────────────────────┐
                      │ (Using parent-scoped  │                        │
                      │  disambiguation)      │                        │
                      └──────────┬────────────┘                        │
                                 │                                     │
                                 ▼                                     │
                      ┌───────────────────────┐                        │
                      │     Execute Node      │                        │
                      └──────────┬────────────┘                        │
                                 │                                     │
                     [Does execution succeed?]                         │
                    /                         \                        │
                  YES                          NO                      │
                  /                             \                      │
                 ▼                               ▼                     │
          ┌─────────────┐             [Has collision-retried?]         │
          │ Run Done    │             /                      \         │
          │ (SUCCESS)   │           YES                       NO ──────┘
          └─────────────┘           /                          \ (Capture trace details,
                                   ▼                            send correction prompt,
                            ┌─────────────┐                     mark "execution_retried = true")
                            │    Halt     │
                            │ (Escalate   │
                            │  to Human)  │
                            └─────────────┘
```

### Algorithm Steps:
1. **Execute spec**: Spawn Playwright against target sandbox.
2. **Collision Event Catch**:
   - Parse execution standard error/logs for pattern: `strict mode violation: locator(...) resolved to N elements`.
   - Extract the failing selector key (e.g., `vqa=edit_btn`).
3. **Diagnostic Extraction**:
   - Inspect surrounding DOM state from Playwright JSON report / trace.
   - Locate the parent container of each colliding element (e.g., Row 1 `.p-datatable-row`, Row 2 `.p-datatable-row`).
4. **Correction Prompt Generation**:
   - Formulate a prompt: *"Strict mode violation: locator('vqa=edit_btn') matched 3 elements. To resolve, scope the locator using a parent container. Example: use `page.locator('tr').filter({ hasText: 'RowText' }).locator('vqa=edit_btn')` instead."*
   - Send the context-enriched prompt back to the Generate Node.
5. **Auto-Regeneration Retry**:
   - Set `executionRetried = true`.
   - Run Generate → Validate → Execute pipeline on the corrected spec.
6. **Hard Limit Verification**:
   - If execution fails on the self-healed spec (even for a different selector or exception), immediately halt to avoid infinite cycles.
   - Terminate the run, transition to `FAILED` state, and trigger a structured notification to a human code reviewer.

---

## 4. Selector Schema Runtime Validation

To keep the production code under the **350 LoC ceiling**, compile-time code generation is replaced with lightweight, synchronous runtime validation of selector keys.

### Validator Logic:
- Reads the tenant's `selectors.json` file synchronously into memory:
  `const selectorMappings = JSON.parse(fs.readFileSync('tenants/{tenant}/selectors.json', 'utf-8'));`
- Compiles a set of valid selector keys: `const validKeys = new Set(Object.keys(selectorMappings));`
- Uses a regular expression to extract all occurrences of `vqa=` selectors from the generated spec:
  ```typescript
  const specContent = fs.readFileSync(specPath, 'utf-8');
  const selectorRegex = /vqa=([a-zA-Z0-9_\-]+)/g;
  let match;
  while ((match = selectorRegex.exec(specContent)) !== null) {
    const key = match[1];
    if (!validKeys.has(key)) {
      throw new Error(`Invalid selector key found in spec: "${key}". Not registered in tenant's selectors.json.`);
    }
  }
  ```
- This lean regex-based parsing contains zero heavy AST parsing dependencies, resolving PE concerns while maintaining strict safety in less than 15 lines of code.
