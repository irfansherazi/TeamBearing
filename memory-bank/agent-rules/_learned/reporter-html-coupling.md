---
name: Reporter HTML/CSS Coupling
globs: ["backend/engine/reporter.py", "backend/**/*report*.py", "backend/**/*_render_*.py"]
paths: ["backend/engine/"]
topics: ["reporter", "html-rendering", "css-coupling", "observability", "code-review"]
priority: low
auto_generated: true
derived_from: [critic-pass-llm-evaluator]
evidence_count: 1
last_validated: 2026-07-30
---

# Learned Rules: reporter-html-coupling

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **render-function-css-class-must-be-defined** (`backend/engine/reporter.py`, any `_render_*` function that emits HTML): When adding a `_render_*` function that emits HTML referencing CSS class names, either (a) reuse class names already defined in the project's report stylesheet, or (b) add the new class definitions to the stylesheet in the **same commit**. Never introduce dangling class references — the HTML section renders silently unstyled in production; there is no runtime error and no test failure, so the gap is invisible until a stakeholder demo. Code-reviewer subagents on reporter-touching phases should grep for `class="..."` in newly added `_render_*` output and verify each token exists in the stylesheet before approving. critic-pass-llm-evaluator Phase 3 evidence: `_render_critic_pass_section()` introduced `.badge-pass`, `.badge-warn`, `.badge-skip`, `.critic-table`, `.critic-reasons`, `.critic-summary`, `.retry-count` with no stylesheet definitions; caught only in the final whole-branch review as a Minor finding.
  - _Source_: reflection-critic-pass-llm-evaluator (2026-07-30)
  - _Reinforced_: 0x
