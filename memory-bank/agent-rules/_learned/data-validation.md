---
derived_from: [hitl-portal-aware-click-capture]
evidence_count: 2
last_validated: 2026-07-29
---
# Learned Rules: data-validation

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **data-validation** (`knowledge/*.yaml`, `knowledge/*.json`): Before writing a `verify_after` field in a YAML blueprint, check whether the engine pre-checks that selector for pre-existing visibility and silently skips the recipe if found — interaction blueprints should use `verify_state_change` (or omit `verify_after`) instead of `element_visible`.
  - _Source_: reflection-TASK-001 (2026-05-07)
  - _Reinforced_: 1x

- **data-validation** (`knowledge/selector_registry.json`, batch JSON edits): After bulk rule-based classification of JSON entries, always run a code-review pass to catch misclassified boundary cases — a 7–8% misclassification rate is expected when classifying by key-name heuristics alone.
  - _Source_: reflection-TASK-001 (2026-05-07)
  - _Reinforced_: 1x

- **yaml-authoring** (`knowledge/blueprints/*.yaml`): Always quote YAML string fields whose values are English words that YAML parses as booleans (`Yes`, `No`, `True`, `False`, `On`, `Off`) to prevent silent type coercion in Pydantic validators.
  - _Source_: reflection-TASK-001 (2026-05-07)
  - _Reinforced_: 1x

- **knowledge-registry** (`knowledge/blueprints/*.yaml`): Documentation-only YAML files that do not conform to the `RecipeStep` schema MUST be placed in `knowledge/docs/` (or similar) to avoid `RecipeRegistry` globbing validation errors that crash the entire registry.
  - _Source_: reflection-TASK-051 (2026-05-26)
  - _Reinforced_: 1x

- **pydantic-hybrid-list** (`backend/config.py`): When defining list types in Pydantic `BaseSettings` that are populated from environment variables, use `list[str] | str` to support both JSON arrays and simple comma-separated strings. Comma-separated strings are the standard for many container orchestrators and are less prone to escaping errors than JSON strings.
  - _Source_: reflection-TASK-058 (2026-05-27)
  - _Reinforced_: 0x

- **pydantic-literal-action-constraint** (`backend/engine/hitl_trace_parser.py`, `backend/engine/recipe_runner.py`, any serializer writing to a `RecipeStep`-like schema): Before designing a serializer output shape that introduces a new action name (e.g., `primeng_dropdown`), verify whether the downstream Pydantic model's `action` field is a `Literal[...]` type. If it is, any new action name requires a schema change — treat that as OUT OF SCOPE unless the task explicitly includes the schema/executor changes. The escape hatch is to use an existing Literal-compatible action type (e.g., `click`, `fill`) plus an existing modifier field like `container_selector` to encode the scoped context. Design the fallback contract around what the schema already permits, not what a uniform payload shape would suggest.
  - _Source_: reflection-hitl-portal-aware-click-capture (2026-07-29)
  - _Reinforced_: 0x
