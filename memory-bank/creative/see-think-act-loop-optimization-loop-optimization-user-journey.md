# User Journey Design: See-Think-Act Loop Optimization

**Created**: 2026-06-02
**Status**: DECIDED
**Decision Type**: User Journey

## Journey Overview

**Feature**: FEAT-071: See-Think-Act Loop Optimization
**Primary Persona**: PM, QA Lead, Platform Admin
**Journey Type**: Hybrid (Background automation with real-time UI reporting)
**Orchestration Pattern**: Dashboard + Progressive Disclosure (Real-time Run Monitoring)

### Success Statement
> PM runs a test ticket from the dashboard; the run executes 40% faster, shows clean un-cluttered screenshots during execution, and displays clear token efficiency metrics and matching human guidance.

## Persona Context

### Primary User: Product Manager / QA Lead
- **Who**: PM or QA Analyst validating tickets.
- **Goal**: Quickly verify AC steps are passing without waiting for long browser execution times or parsing verbose logs.
- **Context**: Executing live runs via the React dashboard.
- **Proficiency**: Non-technical/Low-code; relies on visual confirmation and structured progress tables.

### Administrative User: Platform Admin / Developer
- **Who**: Platform Admin or QA Engineer managing the vQA infrastructure.
- **Goal**: Ensure the RAG system finds relevant guidance files based on semantic intent, and verify token usage stays within the context window limits.
- **Different needs**: Needs detailed performance statistics (token count reductions, embedding search precision, split-execution locator coordinates).

---

## Journey Map

### Entry Points
| Entry | Context | User Intent |
|-------|---------|-------------|
| "Run Test" Button | SELECT mode on dashboard | Initiate the optimized autonomous run for a JIRA ticket. |
| "Triage Panel" / "Run History" | COMPLETE mode / past runs | View token efficiency stats, retrieved guidance logs, and coordinate resolution steps. |

### State Diagram
```
[SELECT: Config ticket & role]
       │
       ▼ (Run Test)
[RUNNING: optimized loop] ──▶ RAG Search: retrieves semantic guidance
       │                  ──▶ Culling: trims accessibility tree (≥40% savings)
       │                  ──▶ Split-Execution: Planner VLM outputs target;
       │                      local resolver finds coordinates on clean screen
       ▼
[COMPLETE: Success/Failure Report]
       │
       ▼ (Triage/Review)
[Success/Failure Details: Displays Token Savings, Guidance Used, & Clean Steps]
```

### Step-by-Step Journey

#### Step 1: SELECT (Configuration)
- **System**: Frontend / Backend API (`POST /execute`)
- **User Sees**: Searchable JIRA Ticket selection, role selector, and advanced settings (Toggle for Semantic Culling and Split-Execution, enabled by default).
- **User Actions**: Clicks "Run Test" on a ticket.
- **Feedback**: Shimmer loading animation transitioning to the RUNNING state.

#### Step 2: RUNNING (Execution Loop)
- **System**: LangGraph Nodes (`planner_node` ➔ `executor_node` ➔ `verifier_node`)
- **User Sees**: 
  - Live screenshot feed showing **clean screen captures** (no red/green Set-of-Marks overlay bounding boxes blocking the view).
  - CopilotSidebar updating live with steps.
  - Performance Toast/Metrics widget in the sidebar displaying:
    - `Tokens Trimmed`: Cumulative tokens saved by the culler (e.g. `12.4k tokens saved`).
    - `Semantic Guidance`: Under the current step, the matched guidance workflow title (e.g. "Matched guidance: 'List View Sorting'").
- **Data Flow**:
  - `planner.py` logs `cull_ratio` and outputs semantic actions (e.g., `{"action": "semantic_click", "target": "Save button"}`).
  - `vision_utils.py` / `executor.py` resolves targets to `(x, y)` coordinates.

#### Step 3: COMPLETE (Success Details)
- **System**: Reporter Node (`reporter_node`)
- **User Sees**: Audit report with a summary of the optimizations:
  - Total duration reduction (e.g., `Execution took 1m 15s (35% faster)`).
  - Total cost savings (estimated token cost difference).
  - Clean step action details list (e.g. "Step 3: Clicked 'Save button' at resolved coordinates (120, 350)").

---

## Error Handling

### Error States
| Error Type | When | User Sees | Recovery |
|------------|------|-----------|----------|
| Target Resolution Failure | Local resolver cannot find target description | Live feed showing target search failure toast, fallback to full page analysis or escalates to HITL. | Operator takes over browser via VNC stream; system records click. |
| Embedding API Timeout / Error | ChromaDB/Local embeddings fail | Warning log in sidebar; retrieval falls back silently to keyword/literal retrieval. | None needed (graceful degradation). |
| Aggressive Culling Bug | Interactive element pruned | Action fails on element; evaluator triggers escalations; sidebar shows culling warning. | Retries with culling disabled (`cull_enabled=False`) on model retry. |

---

## Options Explored

### Option 1: Silent Under-the-Hood Optimization
- **Orchestration**: Standard dashboard, no UI changes.
- **Entry Point**: Click "Run Test".
- **Key Interactions**: Visuals and inputs remain identical. No mention of RAG matches or token reductions on the UI.
- **Pros**:
  - Zero frontend changes required.
  - Less cognitive noise for PM.
- **Cons**:
  - The user has no idea why the run is faster, nor can they audit if the correct human guidance was matched.
  - Hard to troubleshoot if culling causes a failure.

### Option 2: Dashboard Real-Time Statistics & Clean Visualization (Chosen)
- **Orchestration**: Sidebar Metrics Widget + Clean Screenshots + Interactive Guidance Badges.
- **Entry Point**: Standard dashboard execution.
- **Key Interactions**:
  - Metrics widget displays cumulative token count reduction and performance speedup.
  - Active steps display the name of the matched semantic guidance workflow.
  - screenshots are clean, making visual review easy.
- **Pros**:
  - Highlights system intelligence (proves the NFR values: token savings and semantic precision).
  - Enables easy troubleshooting (indicates which guidance was applied).
  - screenshots are clear and report-ready.
- **Cons**:
  - Requires updating the React frontend (`StepTable` and `RunTestView` components) to receive and display these new execution state metrics.

---

## Evaluation Matrix

| Criterion | Option 1 | Option 2 |
|-----------|----------|----------|
| Discoverability | Low | High |
| Learnability | Medium | High |
| Efficiency | High | High |
| Error Prevention | Medium | High (visual cues verify correct guidance) |
| Error Recovery | Low | High (culling rollback visible) |
| Consistency | High | High (integrates with StepTable metrics) |
| Accessibility | High | High |

---

## Decision

**Chosen**: Option 2 - Dashboard Real-Time Statistics & Clean Visualization

### Rationale
Displaying optimization statistics directly in the execution view provides high transparency. PMs can see that their guidance works without reading logs, and developers immediately know if DOM culling was too aggressive. Clean screenshots are visually superior and more representative of actual user screens.

### Trade-offs Accepted
- Frontend updates are required to display token savings, matched guidance badges, and coordinate-based action descriptions. These updates must degrade gracefully if variables are missing.

---

## Acceptance Criteria (MANDATORY)

### AC-JOURNEY-1: User sees token savings in the execution UI
**Priority**: MUST
**Given** the user is viewing a live running test on the dashboard
**When** the semantic DOM culler executes on a page
**Then** the UI displays the cumulative tokens/character savings (e.g. `DOM Culling: 42% (8.5k chars saved)`) in the progress panel.

**Verification**:
- [ ] E2E: Progress messages include culling statistics.
- [ ] Frontend: StepTable/Sidebar displays the culling statistics if present.

### AC-JOURNEY-2: Clean screenshots without SoM bounding boxes are displayed
**Priority**: MUST
**Given** the user is viewing the live screenshot stream during execution
**When** the planner decides to click a semantic target using split-execution
**Then** the screenshot shown in the UI contains NO visual Set-of-Marks bounding boxes or overlays.

**Verification**:
- [ ] E2E: Screenshot gallery shows clean browser captures.

### AC-JOURNEY-3: User sees matched human guidance workflows
**Priority**: MUST
**Given** the user has started a run that references a step covered in `human_guidance.md`
**When** the RAG system retrieves a match
**Then** the sidebar displays a badge with the matched workflow title under that step.

**Verification**:
- [ ] E2E: Matched guidance workflows are displayed in the step details.

---

## Next Steps

1. Create Architecture Decision Document defining local resolver and culler mechanisms.
2. Implement backend culler, ChromaDB vault, and coordinate resolver.
3. Update FastAPI WebSocket message schema to broadcast culling stats and RAG match titles.
4. Update React frontend to display culling stats and matched guidance badges.
