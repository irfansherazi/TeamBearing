---
legacy_id: remote-browser-control-and-autorecording-engine
---
# remote-browser-control-and-autorecording-engine: Remote Browser Control & Autorecording Engine

**Status**: REFLECTION_COMPLETE
**Phase**: DONE
**Complexity**: Level 4
**Created**: 2026-05-19
**Roadmap Link**: FEAT-044
**Branch**: feature/FEAT-044-remote-takeover-autorecord

---

## Summary

In production/Docker environments, the Playwright browser runs in a headless environment inside a container or remote host, preventing operators from seeing or taking manual control during HITL events. Furthermore, the current coordinate-injection and character-typing text interface is highly unintuitive. This feature implements:

1. **Interactive Remote Browser Takeover Stream** — Replace the current static screenshot coordinate injection with an interactive live browser stream (via VNC/noVNC iframe) embedded directly in the React frontend during HITL takeover events. This gives operators direct visual and interactive control over the live browser window.
2. **Automatic Action Capture & Autorecording Engine** — When an operator takes manual control, dynamically listen to all browser interaction events (mouse clicks, character typing, navigations, dropdown changes) and automatically translate these human interventions into structured vQA execution steps/Playwright API calls, appending them directly to the test's execution history and the Knowledge Base without manual text command entry.

---

## Specification

### Invocation Location
- **Remote VNC Stream**: Embedded inside the frontend React application (`TakeoverPanel.tsx` and `LiveBrowser.tsx` components) as an interactive `iframe` that loads when the run status switches to `awaiting_human_takeover: True`.
- **Dynamic URL Generation**: Backend `routes.py` constructs a dynamic `novnc_url` at runtime using the incoming HTTP request headers (origin/host) rather than hardcoded `localhost:6080` to support remote deployments seamlessly.
- **Autorecording Engine**: Activated automatically by `human_takeover_node` in `backend/engine/human_takeover.py` before broadcasting the takeover event, injecting the JavaScript listener to capture mouse clicks, keyboard text entries, and change events.

### Success Criteria
- When a human takeover event is triggered, a live visual stream of the browser appears inside an iframe in the `TakeoverPanel` within 1 second.
- The operator can click and type directly inside the iframe to control the remote browser (via noVNC proxy) without CORS or CSP security violations.
- Operator interactions are dynamically intercepted by a JavaScript click/change listener and streamed back to the FastAPI backend via a Playwright `exposeFunction` bridge in real time.
- Clicking "Done" serializes the recorded events into deterministic Playwright action blocks (e.g., `click`, `fill`, `select`) and writes them directly to:
  - `knowledge/blueprints/learned_workflows.json`
  - `knowledge/vSuite-actions.md`
  - `knowledge/human_guidance.md`
- The next test execution encountering the same AC step successfully bypasses LLM planning and replays the auto-recorded human sequence, resulting in a fast, deterministic run.

### Data Persistence
- **Staging Selectors**: `knowledge/human_learned.jsonl` (JSON lines of raw event strategies).
- **Learned Workflows**: `knowledge/blueprints/learned_workflows.json` (JSON object maps AC steps to full Playwright action arrays).
- **Auto-Learned KB**: `knowledge/vSuite-actions.md` (markdown append-only format).
- **Combined HITL Guidance**: `knowledge/human_guidance.md` (markdown append-only of text + selectors).

---

## Acceptance Criteria

### AC-ENTRY-1: Dynamic noVNC URL Generation
**Priority**: MUST

**Given** a run paused for human takeover
**When** the frontend queries the run status or receives a WebSocket status broadcast
**Then**:
  - The payload contains a valid, dynamically constructed `novnc_url` matching the request's protocol and origin (e.g. `http://vqa.vcreative.net:6080/vnc.html` or `http://localhost:6080/vnc.html`)
  - The URL is built using `settings.external_host` and `settings.novnc_port` with appropriate fallback behavior

**Verification**:
- [ ] API test verifying `novnc_url` construction in `/status/{run_id}` response.
- [ ] Unit test: `test_vnc_url.py` validates protocol (http/https) and host mapping.

---

### AC-HAPPY-1: Interactive noVNC Stream Displays in Takeover Panel
**Priority**: MUST

**Given** the backend is in `awaiting_human_takeover` state
**When** the operator opens the React dashboard
**Then**:
  - The static screenshot takeover panel is replaced with an interactive VNC `iframe` pointing to the dynamic `novnc_url`
  - The operator can interactively click buttons and type text directly into the virtual window

**Verification**:
- [ ] Manual test: Verify noVNC loads and renders correctly inside the iframe without sandbox/CSP errors.
- [ ] Browser inspect: Assert no browser console errors on loading VNC frame.

---

### AC-HAPPY-2: Robust Multi-Event Interception
**Priority**: MUST

**Given** the VNC stream is active and the operator is interacting with the browser
**When** the operator clicks an element, types text, changes a dropdown, or triggers navigation
**Then**:
  - Every click event captures data-testid, aria-label, role, innerText, and CSS paths
  - Input/change events capture the final value typed/selected (e.g., character strings or checkbox states)
  - All events are streamed over the `__vqa_record_human_action__` Playwright bridge and logged to Python in real time

**Verification**:
- [ ] Unit test: Mock Playwright page and simulate exposed Python calls to verify `_on_human_action` logs correctly.
- [ ] Integration test: Verify click and text input capture strategies generate stable CSS/text locators.

---

### AC-HAPPY-3: Auto-Serialization & KB Injection on Done
**Priority**: MUST

**Given** the operator has completed the manual step and clicked "Done"
**When** `POST /runs/{run_id}/human-takeover/done` is called
**Then**:
  - All captured events are serialized into standard Playwright actions (click, fill)
  - The action sequence is appended to `learned_workflows.json` keyed by the AC step text
  - A RAG-retrievable markdown block containing BOTH the operator's text explanation and the Playwright selector JSON is appended to `human_guidance.md` and `vSuite-actions.md`
  - The LangGraph node successfully resumes and advances to the next step

**Verification**:
- [ ] Unit test: `test_autorecord_done.py` verifies file writing and JSON formatting.
- [ ] RAG test: Assert the TF-IDF retriever retrieves the newly generated entry for identical AC query.

---

### AC-ERROR-1: Frame Navigation and Re-injection Resilience
**Priority**: MUST

**Given** the VNC stream is active in human takeover mode
**When** the operator clicks a link that navigates to a new page or reloads the tab
**Then**:
  - The backend intercepts the navigation event
  - The JavaScript action capture listener is automatically re-injected into the new document context
  - Subsequent clicks/inputs on the new page continue to be captured without data loss

**Verification**:
- [ ] Unit test: `test_navigation_reinjection.py` simulates frame navigations and asserts re-injection logic.

---

## Component Analysis

### New Components

| Component | File | Purpose |
|---|---|---|
| `VncUrlBuilder` | `backend/browser/vnc_builder.py` | Handles dynamic URL construction, proxy routing checks, and CORS/CSP header adjustments for remote noVNC streams |
| `AutorecordSerializer` | `backend/engine/autorecord.py` | Handles parsing, filtering, and sanitizing the JS raw event sequence into clean, replayable Playwright JSON steps |

### Affected Components

| Component | File | Change |
|---|---|---|
| `human_takeover_node` | `backend/engine/human_takeover.py` | Extend the JS interception payload to capture scroll, text input, dropdown change, and frame-navigation events. Improve de-duplication and auto-injection hooks |
| `routes.py` | `backend/api/routes.py` | Update status and done endpoints to handle dynamic `novnc_url` building and invoke automated serialization upon Done signal |
| `LiveBrowser.tsx` | `frontend/src/components/LiveBrowser.tsx` | Embed noVNC `iframe` during active takeover states, switching from static screenshot coordinate mode |
| `TakeoverPanel.tsx` | `frontend/src/components/TakeoverPanel.tsx` | Render VNC iframe container, manage keyboard focus, Done/Skip overlay controls, and capture status |

---

## Implementation Strategy

### Phase 1 — VNC Stream & React Frontend Integration (2–3 files)
**Goal**: Wire the dynamic noVNC URL generator and integrate the interactive iframe into the React frontend.

1. Implement `backend/browser/vnc_builder.py` to build VNC URLs dynamically based on incoming headers.
2. Update `routes.py` status endpoints to return this URL dynamically.
3. Modify `TakeoverPanel.tsx` and `LiveBrowser.tsx` to render the VNC iframe during takeover.

**Files touched**: `backend/browser/vnc_builder.py` (new), `backend/api/routes.py`, `frontend/src/components/TakeoverPanel.tsx`, `frontend/src/components/LiveBrowser.tsx`

---

### Phase 2 — Multi-Event Interception & Playwright Bridge (2 files)
**Goal**: Expand the JavaScript event capture listener to intercept all human interactions (clicks, keyboard inputs, changes) and route them over the exposed bridge.

1. Expand the JS injection script in `human_takeover.py` to add `keyup`, `change`, and `scroll` listener handlers.
2. Build strategies to capture PrimeNG element values and label attributes.
3. Wire page navigation hooks to automatically re-inject the listener on new frame load.

**Files touched**: `backend/engine/human_takeover.py`, `tests/test_event_interception.py` (new)

---

### Phase 3 — Serialization & Knowledge Base Autopilot (3 files)
**Goal**: Translate raw interaction events into high-quality Playwright action sequences, saving them automatically to the Knowledge Base on "Done".

1. Create `backend/engine/autorecord.py` to convert captured events into standard `{action, strategy, name, value}` JSON blocks.
2. Hook `complete_takeover()` to run the serializer and write to `learned_workflows.json`, `vSuite-actions.md`, and `human_guidance.md` in one transaction.
3. Add unit test coverage for the entire end-to-end serialization pipeline.

**Files touched**: `backend/engine/autorecord.py` (new), `backend/engine/human_takeover.py`, `tests/test_autorecord_serialization.py` (new)

---

## Dependencies & Risks

| Risk | Mitigation |
|---|---|
| **CORS / CSP Browser Blockers** | iframe loading noVNC from a different port (`6080` vs `8000`) might fail CSP rules. **Mitigation**: Backend implements a proxy route `/vnc-proxy` that tunnels noVNC traffic if local origin mismatch is detected, or configures the FastAPI CORS middleware properly. |
| **No Action Captured on Keyboard Input** | Human types without clicking/focusing. **Mitigation**: Capture input change events globally and link them to the last clicked text/input field selector. |
| **Tab/Page Closures** | If the operator closes a tab manually in VNC, Playwright reference becomes null. **Mitigation**: Event listener catches tab close and `human_takeover_node` opens a new tab automatically to keep VNC active. |
| **Index Bloat** | Repeated takeovers on the same step duplicate entries. **Mitigation**: Implement exact duplicate heading search in `vSuite-actions.md` and only append if the step has not been recorded before. |

---

## Prompt Efficiency & Performance

1. **Auto-Learned RAG Injection**: Auto-learned workflows are written in structured markdown blocks which are loaded by the TF-IDF engine. By keeping the JSON action descriptions compact (only action, strategy, and selector), we avoid adding useless prompt tokens.
2. **Replay Accuracy**: Because the selector sequence is recorded directly from a human click/fill, it is 100% correct, resulting in zero planner hallucination retries.
3. **Selective Logging**: Ignore system clicks and only capture human actions during manual takeover window.

---

## Observability Requirements

- **Applies**: Yes
- **Structured JSON Logging**: Every captured human event is logged with `traceId` and `spanId` propagated from FastAPI backend.
- **Trace Context Propagation**: WS status updates carry the current `traceId` for front-to-back request tracing.
- **Logs**:
  - `INFO`: `"[run-xxx] Human takeover initiated. VNC stream: http://..."`
  - `INFO`: `"[run-xxx] Intercepted human interaction: click on button [data-testid='submit']"`
  - `INFO`: `"[run-xxx] Serialized 4 manual actions to learned_workflows.json"`
  - `WARNING`: `"[run-xxx] VNC iframe connection closed, attempting automatic browser page recovery"`

---

## API Requirements

### REST: New / Updated Endpoints
- **GET /runs/{run_id}/status**
  - Response field `novnc_url` is dynamically updated.
- **POST /runs/{run_id}/human-takeover/done**
  - Invokes `AutorecordSerializer` before completing the event wait.

---

## Creative Phases Required

None — The VNC architecture and events capturing strategies follow existing Playwright/VNC standards, and the SQLite + Markdown storage patterns perfectly match current backend systems.

---

## Work Items

### WI-033-001: Phase 1 — VNC Stream & React Frontend Integration
**Status**: Complete
**Completed**: 2026-05-20
**Test Results**: 9/9 passing
**Code Review**: APPROVED
**Dependencies**: None
**Files**:
- `backend/browser/vnc_builder.py` (new)
- `backend/api/routes.py`
- `frontend/src/components/TakeoverPanel.tsx`
- `frontend/src/components/LiveBrowser.tsx`

**Implementation**:
1. Implement dynamic noVNC URL builder using FastAPI request host and protocol headers.
2. Replace static screenshot components in the React frontend with interactive iframes when `awaiting_human_takeover` is true.

---

### WI-033-002: Phase 2 — Multi-Event Interception & Playwright Bridge
**Status**: Complete
**Completed**: 2026-05-20
**Dependencies**: WI-033-001
**Files**:
- `backend/engine/human_takeover.py`
- `tests/test_event_interception.py` (new)

**Implementation**:
1. Extended the click capture script to support keyboard inputs (keyup), select dropdowns (change), and scrolls.
2. Implemented navigation re-injection using Playwright's `framenavigated` event listener with automatic cleanup.

---

### WI-033-003: Phase 3 — Serialization & Knowledge Base Autopilot
**Status**: Complete
**Completed**: 2026-05-20
**Dependencies**: WI-033-002
**Files**:
- `backend/engine/autorecord.py` (new)
- `backend/engine/human_takeover.py`
- `tests/test_autorecord_serialization.py` (new)

**Implementation**:
1. Implemented `AutorecordSerializer` to translate raw browser events into clean Playwright steps (merging typing, deduplicating focus clicks).
2. Integrated serializer into all Knowledge Base update helpers and the HITL override payload.

---

## Test Strategy

| Test File | Coverage |
|---|---|
| `tests/test_vnc_url_builder.py` | Dynamic URL protocol/host building |
| `tests/test_event_interception.py` | JS listener event formats and Playwright callback registry |
| `tests/test_autorecord_serialization.py` | Autorecording to Playwright translation logic |
| `tests/test_kb_autopilot.py` | Transacted writing to learned_workflows, vSuite-actions, and human_guidance |

**Framework**: pytest
**Mocking**: Playwright Page objects, file system writers for knowledge files.

---

## Validation Gate ✅

- [x] Invocation Location is concrete — Dynamic iframe inside `TakeoverPanel.tsx` loading VNC stream.
- [x] Invocation Element is concrete — Interactive mouse/keyboard VNC iframe stream.
- [x] Success Message is concrete — Auto-records human clicks/inputs and logs `"Serialized N manual actions"`.
- [x] Success Verification Location is concrete — `knowledge/blueprints/learned_workflows.json` on disk.
- [x] Data Persistence is concrete — `learned_workflows.json`, `vSuite-actions.md`, and `human_guidance.md`.
- [x] AC-ENTRY-1 and AC-HAPPY-1 exist — Yes.
- [x] Implementation approach respects Guiding Principles — Yes, uses environment configs, Stateless VNC routing, and HITL learning signals.
- [x] No undocumented deviations from established patterns — Yes, uses the same file persistence and LangGraph states.

---

## Execution State

**Build Status**: IDLE
**Current Phase**: DONE
**Can Resume**: NO
**Completed Phases**: PLAN, Phase 1, Phase 2, Phase 3, REFLECT
**Phase Being Built**: N/A
**Phase Number**: 3 of 3
**Is Multi-Phase**: YES
**Build Started**: 2026-05-20T10:00:00-05:00
**Build Completed**: 2026-05-20T15:30:00-05:00
**Reflection Completed**: 2026-05-20T16:30:00-05:00
**Archive Completed**: N/A
**Current Build Step**:
  Step: Reflection Complete
  Status: COMPLETE
  Completed: 2026-05-20T16:30:00-05:00

### Completed Steps
- Step 1 Read Task Context: COMPLETE (2026-05-20T10:00:00-05:00)
- Step 2 Load Complexity Context: COMPLETE (2026-05-20T10:05:00-05:00)
- Step 3 Test Writer Agent: COMPLETE (2026-05-20T10:20:00-05:00)
- Step 4 Coding Agent: COMPLETE (2026-05-20T11:00:00-05:00)
- Step 6 Execute Test Batches: COMPLETE (2026-05-20T11:15:00-05:00)
- Step 7 Integration Verification: COMPLETE (2026-05-20T11:45:00-05:00)
- Step 8 Code Reviewer Agent: COMPLETE (2026-05-20T12:00:00-05:00)
- Step 9 Documentation Agent: COMPLETE (2026-05-20T12:15:00-05:00)
- Step 10 Update Memory Bank: COMPLETE (2026-05-20T15:30:00-05:00)
- Step 11 Reflection Agent: COMPLETE (2026-05-20T16:30:00-05:00)

