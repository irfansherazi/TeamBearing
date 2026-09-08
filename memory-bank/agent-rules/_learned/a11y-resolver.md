---
name: A11y Resolver Patterns
globs: ["backend/browser/a11y_resolver.py", "backend/engine/executor.py"]
topics: ["accessibility", "playwright", "locator-resolution"]
priority: low
auto_generated: true
derived_from: [accessibility-tree-grounding]
evidence_count: 1
last_validated: 2026-07-30
---

# Learned Rules: a11y-resolver

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **a11y-two-tier-probe** (`backend/browser/a11y_resolver.py`, `backend/engine/executor.py`): When implementing a Playwright `get_by_role(role, name=name)` resolution tier with a normalized-regex retry, fire the normalization retry ONLY on N==0 (zero matches), never on N>=2 (ambiguous). Normalization (NFC, casefold, icon glyph strip, ellipsis strip) can only expand the match set — applying it after ambiguity amplifies false positives instead of resolving them. Ambiguous matches should short-circuit to selector fallback with a WARN log carrying the count; never call `.first` silently.
  - _Source_: reflection-accessibility-tree-grounding (2026-07-30)
  - _Reinforced_: 0x

- **a11y-primitive-boundaries** (`backend/browser/a11y_resolver.py`): A11y resolver modules living in `backend/browser/` MUST accept primitives (`aria_role: str`, `aria_name: str`) rather than importing `TestPlanStep` or other `backend/engine/` schemas. This preserves the layer boundary and prevents import cycles between the browser and engine layers. Callers in `backend/engine/executor.py` extract the primitives at the call site.
  - _Source_: reflection-accessibility-tree-grounding (2026-07-30)
  - _Reinforced_: 0x
