# Agent Rules Index

Generated: 2026-07-20T00:00:00Z
Indexed: 30 rules (1 human-authored, 29 learned) | Rejected: 0 (unsafe) | Warnings: 0

## Validation Summary

### Health Check
- Total rules: 30
- Human-authored rules: 1
- Learned rules (auto-generated): 29
- Estimated max context: ~1100 lines (load selectively)
- Conflicts detected: 0

## Rules by File Pattern

| Pattern | Rule | Priority | Lines |
|---------|------|----------|-------|
| `backend/api/` | [Backend API Patterns](agent-rules/_learned/backend-api-patterns.md) | high | 57 |
| `backend/api/routes.py` | [Backend API Patterns](agent-rules/_learned/backend-api-patterns.md) | high | 57 |
| `backend/api/playwright_routes.py` | [Backend API Patterns](agent-rules/_learned/backend-api-patterns.md) | high | 57 |
| `backend/browser/context.py` | [Browser Patterns](agent-rules/_learned/browser-patterns.md) | medium | 32 |
| `backend/engine/human_takeover.py` | [Browser Patterns](agent-rules/_learned/browser-patterns.md) | medium | 32 |
| `playwright/tests/**/*.test.ts` | [Browser Patterns](agent-rules/_learned/browser-patterns.md) | medium | 32 |
| `scripts/validate_env.py` | [Config Validation Patterns](agent-rules/_learned/config-validation.md) | low | 12 |
| `backend/config.py` | [Config Validation Patterns](agent-rules/_learned/config-validation.md) | low | 12 |
| `backend/engine/verifier.py` | [Context Budget Patterns](agent-rules/_learned/context-budget.md) | high | 25 |
| `backend/engine/planner.py` | [Context Budget Patterns](agent-rules/_learned/context-budget.md) | high | 25 |
| `knowledge/*.yaml` | [Data Validation Patterns](agent-rules/_learned/data-validation.md) | medium | 25 |
| `knowledge/*.json` | [Data Validation Patterns](agent-rules/_learned/data-validation.md) | medium | 25 |
| `backend/config.py` | [Data Validation Patterns](agent-rules/_learned/data-validation.md) | medium | 25 |
| `backend/engine/*.py` | [Deferred Verification Patterns](agent-rules/_learned/verification-patterns.md) | high | 25 |
| `backend/engine/evaluator.py` | [Engine Reliability Patterns](agent-rules/_learned/engine-reliability.md) | high | 84 |
| `backend/browser/` | [Engine Reliability Patterns](agent-rules/_learned/engine-reliability.md) | high | 84 |
| `backend/engine/reporter.py` | [Engine Reliability Patterns](agent-rules/_learned/engine-reliability.md) | high | 84 |
| `backend/browser/context.py` | [Ephemeral UI Observer Pattern](agent-rules/_learned/ephemeral-ui-buffer.md) | medium | 21 |
| `backend/engine/verifier.py` | [Ephemeral UI Observer Pattern](agent-rules/_learned/ephemeral-ui-buffer.md) | medium | 21 |
| `backend/adapters/` | [Error Handling Patterns](agent-rules/_learned/error-handling.md) | high | 48 |
| `backend/api/routes.py` | [Error Handling Patterns](agent-rules/_learned/error-handling.md) | high | 48 |
| `frontend/src/components/*.tsx` | [Error Handling Patterns](agent-rules/_learned/error-handling.md) | high | 48 |
| `backend/engine/evaluator.py` | [Evaluator Routing Patterns](agent-rules/_learned/evaluator-routing.md) | high | 68 |
| `backend/engine/graph.py` | [Evaluator Routing Patterns](agent-rules/_learned/evaluator-routing.md) | high | 68 |
| `backend/engine/state.py` | [Evaluator Routing Patterns](agent-rules/_learned/evaluator-routing.md) | high | 68 |
| `frontend/src/components/*.tsx` | [Frontend Patterns](agent-rules/_learned/frontend-patterns.md) | medium | 68 |
| `frontend/src/context/*.tsx` | [Frontend Patterns](agent-rules/_learned/frontend-patterns.md) | medium | 68 |
| `frontend/src/hooks/*.ts` | [Frontend Patterns](agent-rules/_learned/frontend-patterns.md) | medium | 68 |
| `frontend/src/pages/*.tsx` | [Frontend Patterns](agent-rules/_learned/frontend-patterns.md) | medium | 68 |
| `docker/` | [Infrastructure Debugging Patterns](agent-rules/_learned/infrastructure-debugging.md) | medium | 52 |
| `backend/browser/context.py` | [Infrastructure Debugging Patterns](agent-rules/_learned/infrastructure-debugging.md) | medium | 52 |
| `backend/browser/accessibility.py` | [Intent-Driven ARIA Pruning](agent-rules/_learned/aria-pruning.md) | low | 36 |
| `backend/engine/planner.py` | [Intent-Driven ARIA Pruning](agent-rules/_learned/aria-pruning.md) | low | 36 |
| `backend/jira/client.py` | [Jira Ingestion Robustness](agent-rules/_learned/jira-robustness.md) | medium | 30 |
| `backend/engine/` | [KB Injection Patterns](agent-rules/_learned/kb-injection.md) | low | 24 |
| `knowledge/` | [KB Injection Patterns](agent-rules/_learned/kb-injection.md) | low | 24 |
| `backend/engine/planner.py` | [Learned: Fuzzy Matching](agent-rules/_learned/fuzzy-matching.md) | low | 21 |
| `knowledge/*.json` | [Learned: Fuzzy Matching](agent-rules/_learned/fuzzy-matching.md) | low | 21 |
| `memory-bank/tasks/*.md` | [Learned: Memory Bank Syncing](agent-rules/_learned/memory-bank-syncing.md) | high | 20 |
| `memory-bank/progress.md` | [Learned: Memory Bank Syncing](agent-rules/_learned/memory-bank-syncing.md) | high | 20 |
| `backend/engine/vision_analyzer.py` | [Learned: Vision Analysis](agent-rules/_learned/vision-analysis.md) | low | 21 |
| `backend/engine/ac_parser.py` | [Learned: Vision Analysis](agent-rules/_learned/vision-analysis.md) | low | 21 |
| `backend/browser/vnc_builder.py` | [Network Patterns](agent-rules/_learned/network-patterns.md) | low | 12 |
| `backend/config.py` | [Performance Architecture Patterns](agent-rules/_learned/performance-architecture.md) | high | 34 |
| `backend/engine/*.py` | [Performance Architecture Patterns](agent-rules/_learned/performance-architecture.md) | high | 34 |
| `backend/kb/*.py` | [Performance Architecture Patterns](agent-rules/_learned/performance-architecture.md) | high | 34 |
| `backend/engine/*.py` | [Proactive Context Injection](agent-rules/_learned/proactive-injection.md) | low | 21 |
| `backend/kb/*.py` | [Proactive Context Injection](agent-rules/_learned/proactive-injection.md) | low | 21 |
| `backend/engine/prompts.py` | [Prompt Engineering Patterns](agent-rules/_learned/prompt-engineering.md) | high | 32 |
| `backend/main.py` | [Python Compatibility Patterns](agent-rules/_learned/python-compatibility.md) | medium | 12 |
| `conftest.py` | [Python Compatibility Patterns](agent-rules/_learned/python-compatibility.md) | medium | 12 |
| `backend/kb/` | [RAG Index Design Patterns](agent-rules/_learned/rag-index-design.md) | medium | 20 |
| `memory-bank/roadmap.md` | [Roadmap Patterns](agent-rules/_learned/roadmap-patterns.md) | low | 8 |
| `backend/api/` | [Security Patterns](agent-rules/_learned/security-patterns.md) | high | 28 |
| `backend/engine/` | [Security Patterns](agent-rules/_learned/security-patterns.md) | high | 28 |
| `backend/storage/*.py` | [Storage Layer Patterns](agent-rules/_learned/storage-layer-pattern.md) | medium | 20 |
| `tests/` | [Testing Patterns](agent-rules/_learned/testing-patterns.md) | high | 68 |
| `conftest.py` | [Testing Patterns](agent-rules/_learned/testing-patterns.md) | high | 68 |
| `backend/engine/test_*.py` | [Testing Patterns](agent-rules/_learned/testing-patterns.md) | high | 68 |
| `**/*` | [VC Workflow Enforcement](agent-rules/vc-workflow.md) | critical | 25 |
| `memory-bank/tasks/*.md` | [Workflow Compliance Patterns](agent-rules/_learned/workflow-compliance.md) | high | 92 |
| `memory-bank/roadmap.md` | [Workflow Compliance Patterns](agent-rules/_learned/workflow-compliance.md) | high | 92 |

## Rules by Path

| Path Contains | Rule | Priority | Lines |
|---------------|------|----------|-------|
| `backend/api/` | [Backend API Patterns](agent-rules/_learned/backend-api-patterns.md) | high | 57 |
| `backend/api/` | [Security Patterns](agent-rules/_learned/security-patterns.md) | high | 28 |
| `backend/api/` | [Error Handling Patterns](agent-rules/_learned/error-handling.md) | high | 48 |
| `backend/browser/` | [Browser Patterns](agent-rules/_learned/browser-patterns.md) | medium | 32 |
| `backend/browser/` | [Engine Reliability Patterns](agent-rules/_learned/engine-reliability.md) | high | 84 |
| `backend/browser/` | [Ephemeral UI Observer Pattern](agent-rules/_learned/ephemeral-ui-buffer.md) | medium | 21 |
| `backend/browser/` | [Infrastructure Debugging Patterns](agent-rules/_learned/infrastructure-debugging.md) | medium | 52 |
| `backend/browser/` | [Intent-Driven ARIA Pruning](agent-rules/_learned/aria-pruning.md) | low | 36 |
| `backend/engine/` | [Context Budget Patterns](agent-rules/_learned/context-budget.md) | high | 25 |
| `backend/engine/` | [Deferred Verification Patterns](agent-rules/_learned/verification-patterns.md) | high | 25 |
| `backend/engine/` | [Engine Reliability Patterns](agent-rules/_learned/engine-reliability.md) | high | 84 |
| `backend/engine/` | [Ephemeral UI Observer Pattern](agent-rules/_learned/ephemeral-ui-buffer.md) | medium | 21 |
| `backend/engine/` | [Evaluator Routing Patterns](agent-rules/_learned/evaluator-routing.md) | high | 68 |
| `backend/engine/` | [Intent-Driven ARIA Pruning](agent-rules/_learned/aria-pruning.md) | low | 36 |
| `backend/engine/` | [KB Injection Patterns](agent-rules/_learned/kb-injection.md) | low | 24 |
| `backend/engine/` | [Performance Architecture Patterns](agent-rules/_learned/performance-architecture.md) | high | 34 |
| `backend/engine/` | [Proactive Context Injection](agent-rules/_learned/proactive-injection.md) | low | 21 |
| `backend/engine/` | [Security Patterns](agent-rules/_learned/security-patterns.md) | high | 28 |
| `backend/jira/` | [Jira Ingestion Robustness](agent-rules/_learned/jira-robustness.md) | medium | 30 |
| `backend/kb/` | [Performance Architecture Patterns](agent-rules/_learned/performance-architecture.md) | high | 34 |
| `backend/kb/` | [Proactive Context Injection](agent-rules/_learned/proactive-injection.md) | low | 21 |
| `backend/kb/` | [RAG Index Design Patterns](agent-rules/_learned/rag-index-design.md) | medium | 20 |
| `backend/storage/` | [Storage Layer Patterns](agent-rules/_learned/storage-layer-pattern.md) | medium | 20 |
| `docker/` | [Infrastructure Debugging Patterns](agent-rules/_learned/infrastructure-debugging.md) | medium | 52 |
| `frontend/src/` | [Error Handling Patterns](agent-rules/_learned/error-handling.md) | high | 48 |
| `frontend/src/` | [Frontend Patterns](agent-rules/_learned/frontend-patterns.md) | medium | 68 |
| `knowledge/` | [Data Validation Patterns](agent-rules/_learned/data-validation.md) | medium | 25 |
| `knowledge/` | [KB Injection Patterns](agent-rules/_learned/kb-injection.md) | low | 24 |
| `knowledge/` | [Proactive Context Injection](agent-rules/_learned/proactive-injection.md) | low | 21 |
| `memory-bank/tasks/` | [Learned: Memory Bank Syncing](agent-rules/_learned/memory-bank-syncing.md) | high | 20 |
| `memory-bank/tasks/` | [Workflow Compliance Patterns](agent-rules/_learned/workflow-compliance.md) | high | 92 |
| `memory-bank/c4/` | [Workflow Compliance Patterns](agent-rules/_learned/workflow-compliance.md) | high | 92 |
| `playwright/tests/` | [Browser Patterns](agent-rules/_learned/browser-patterns.md) | medium | 32 |
| `scripts/` | [Config Validation Patterns](agent-rules/_learned/config-validation.md) | low | 12 |
| `tests/` | [Testing Patterns](agent-rules/_learned/testing-patterns.md) | high | 68 |

## Rules by Topic

| Keywords | Rule | Priority |
|----------|------|----------|
| `api-patterns`, `concurrency`, `subprocess`, `pid-tracking`, `security` | [Backend API Patterns](agent-rules/_learned/backend-api-patterns.md) | high |
| `browser`, `playwright`, `table-extraction`, `teardown`, `vnc` | [Browser Patterns](agent-rules/_learned/browser-patterns.md) | medium |
| `config`, `validation`, `diagnostics`, `environment` | [Config Validation Patterns](agent-rules/_learned/config-validation.md) | low |
| `context-budget`, `prompt-assembly`, `failure-diary` | [Context Budget Patterns](agent-rules/_learned/context-budget.md) | high |
| `data-validation`, `yaml`, `pydantic`, `knowledge-registry` | [Data Validation Patterns](agent-rules/_learned/data-validation.md) | medium |
| `verification`, `transient-states`, `reliability`, `loops` | [Deferred Verification Patterns](agent-rules/_learned/verification-patterns.md) | high |
| `stagnation`, `dom-culling`, `state-serialization`, `engine-reliability` | [Engine Reliability Patterns](agent-rules/_learned/engine-reliability.md) | high |
| `reliability`, `race-conditions`, `ephemeral-ui` | [Ephemeral UI Observer Pattern](agent-rules/_learned/ephemeral-ui-buffer.md) | medium |
| `error-handling`, `graceful-degradation`, `fallbacks`, `502` | [Error Handling Patterns](agent-rules/_learned/error-handling.md) | high |
| `evaluator`, `routing`, `circuit-breaker`, `langgraph`, `graph-recursion` | [Evaluator Routing Patterns](agent-rules/_learned/evaluator-routing.md) | high |
| `frontend`, `react`, `css`, `state-machine`, `theming`, `local-state` | [Frontend Patterns](agent-rules/_learned/frontend-patterns.md) | medium |
| `docker`, `debugging`, `diagnostics`, `deployment`, `empirical` | [Infrastructure Debugging Patterns](agent-rules/_learned/infrastructure-debugging.md) | medium |
| `accessibility-tree`, `token-optimization`, `web-automation` | [Intent-Driven ARIA Pruning](agent-rules/_learned/aria-pruning.md) | low |
| `jira`, `ingestion`, `robustness` | [Jira Ingestion Robustness](agent-rules/_learned/jira-robustness.md) | medium |
| `kb-injection`, `knowledge-base`, `deduplication`, `hitl-training` | [KB Injection Patterns](agent-rules/_learned/kb-injection.md) | low |
| `fuzzy-matching`, `text-matching`, `hallucination-reduction` | [Learned: Fuzzy Matching](agent-rules/_learned/fuzzy-matching.md) | low |
| `state-management`, `git-workflow`, `memory-bank`, `documentation-sync` | [Learned: Memory Bank Syncing](agent-rules/_learned/memory-bank-syncing.md) | high |
| `vision`, `multimodal`, `ui-reasoning` | [Learned: Vision Analysis](agent-rules/_learned/vision-analysis.md) | low |
| `network`, `url-construction`, `proxy`, `vnc-url` | [Network Patterns](agent-rules/_learned/network-patterns.md) | low |
| `performance`, `feature-flags`, `speculative-execution`, `parallelism`, `asyncio` | [Performance Architecture Patterns](agent-rules/_learned/performance-architecture.md) | high |
| `prompt-engineering`, `hallucination-reduction`, `dropdown-options` | [Proactive Context Injection](agent-rules/_learned/proactive-injection.md) | low |
| `llm`, `prompts`, `engineering`, `bdd` | [Prompt Engineering Patterns](agent-rules/_learned/prompt-engineering.md) | high |
| `python-3.13`, `import-ordering`, `compatibility`, `numpy` | [Python Compatibility Patterns](agent-rules/_learned/python-compatibility.md) | medium |
| `rag`, `vector-search`, `knowledge-base`, `chromadb` | [RAG Index Design Patterns](agent-rules/_learned/rag-index-design.md) | medium |
| `roadmap`, `planning`, `objectives` | [Roadmap Patterns](agent-rules/_learned/roadmap-patterns.md) | low |
| `security`, `allow-list`, `subprocess`, `credentials`, `in-memory` | [Security Patterns](agent-rules/_learned/security-patterns.md) | high |
| `storage`, `sqlite`, `threading`, `filesystem`, `locking` | [Storage Layer Patterns](agent-rules/_learned/storage-layer-pattern.md) | medium |
| `testing`, `pytest`, `mocking`, `fixtures`, `async` | [Testing Patterns](agent-rules/_learned/testing-patterns.md) | high |
| | [VC Workflow Enforcement](agent-rules/vc-workflow.md) | critical |
| `workflow`, `documentation`, `c4-architecture`, `mermaid` | [Workflow Compliance Patterns](agent-rules/_learned/workflow-compliance.md) | high |
