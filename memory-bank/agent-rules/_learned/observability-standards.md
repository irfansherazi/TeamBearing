---
name: Observability Standards — Codebase Reality Check Before CLAUDE.md Aspirations
globs: ["backend/**/*.py", "CLAUDE.md"]
paths: ["backend/", "memory-bank/creative/", "memory-bank/tasks/"]
topics: ["observability", "logging", "opentelemetry", "aspirational-standards", "adr-documented-deviation"]
priority: low
auto_generated: true
derived_from: [per-user-session-isolation]
evidence_count: 1
last_validated: 2026-08-07
---

# Learned Rules: observability-standards

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **codebase-reality-check-before-observability-standard** (`backend/**/*.py`, any planning/creative/build agent reading `CLAUDE.md` observability section): Before implementing an observability requirement stated in `CLAUDE.md` (e.g., "OpenTelemetry First", "distributed tracing always", "structured JSON with traceId/spanId"), perform a codebase reality check: (1) `grep -r "^from opentelemetry" backend/`, (2) `grep -i opentelemetry requirements.txt`, (3) check `backend/main.py` for the active logging bootstrap. If the installed stack does not match the stated standard, flag the discrepancy in the creative doc as an ADR and either (a) scope-in the observability bootstrap as its own phase with dependency additions, or (b) ADR-document an explicit deviation shipping the closest achievable equivalent. `CLAUDE.md` observability standards are aspirational for many brownfield projects; silently attempting to implement them will add unplanned dependency work and cascading test/config changes. `per-user-session-isolation` evidence: `CLAUDE.md` mandates "OpenTelemetry First" but the codebase had zero OTel SDK imports and `backend/main.py:80` used plain `logging.basicConfig`. The feature shipped structured JSON logs via stdlib `JsonFormatter` + CloudWatch Metric Filters, ADR-documented as an explicit deviation; full OTel bootstrap is now scoped as a separate follow-up task rather than accidentally derailing the isolation feature's timeline.
  - _Source_: reflection-per-user-session-isolation (2026-08-07)
  - _Reinforced_: 0x
