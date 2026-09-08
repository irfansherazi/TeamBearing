# Archive: Remote Browser Control & Autorecording Engine

## Metadata
- Task ID: remote-browser-control-and-autorecording-engine
- Complexity: Level 4
- Started: 2026-05-19
- Completed: 2026-05-20
- Duration: 2 days
- Roadmap Link: FEAT-044

## Executive Summary
Implemented an interactive remote browser takeover system and an automated action recording engine for the vQA platform. This feature allows human operators to visually control the remote Playwright browser during HITL (Human-in-the-Loop) events and automatically transforms their interactions into replayable automation steps. This significantly accelerates knowledge acquisition, reduces manual data entry, and ensures 100% deterministic replays for complex UI workflows.

## System Overview
### Purpose
To bridge the gap between headless remote browser execution and human intervention. Operators need to see and interact with the browser directly when the AI gets stuck, and the system should learn from those interventions automatically.

### Scope
- Backend dynamic VNC URL generation.
- Frontend React integration of noVNC iframe.
- Playwright-based JavaScript event interception.
- Action serialization and Knowledge Base injection.

### Key Capabilities
- **Live Interactive Stream**: Full mouse/keyboard control of remote browser via noVNC.
- **Dynamic Routing**: Automatic detection of protocol/host for zero-config remote access.
- **Autorecording**: Automatic capture of clicks, typing, and selects.
- **KB Autopilot**: Direct serialization of human actions into the Knowledge Base.

## Architecture
### Overview
The system uses a sidecar noVNC/websockify process to expose the Playwright browser's display (VNC). The backend generates a dynamic URL for the frontend to embed in an iframe. A custom JavaScript payload is injected into the browser context to intercept DOM events and stream them back to Python via a Playwright bridge.

### Component Diagram
- **Frontend (React)**: `TakeoverPanel` -> `LiveBrowser` (iframe)
- **Backend (FastAPI)**: `routes.py` -> `VncUrlBuilder`
- **Engine (LangGraph)**: `human_takeover_node` -> `AutorecordSerializer`
- **Browser (Playwright)**: JS Interaction Listener -> `exposeFunction` Bridge

### Data Flow
1. Human clicks/types in VNC iframe.
2. JS Listener captures event + selector metadata.
3. JS sends event to Python via `__vqa_record_human_action__`.
4. Python appends to raw event buffer for the run.
5. On "Done", `AutorecordSerializer` cleans and formats the buffer.
6. Actions are written to `learned_workflows.json` and markdown files.

### Integration Points
- **noVNC**: External process providing the web-VNC bridge.
- **LangGraph**: Integrated as part of the `human_takeover` node.
- **Knowledge Base**: Updates `learned_workflows.json`, `vSuite-actions.md`, and `human_guidance.md`.

## Design Decisions
### Dynamic noVNC URL Generation
- **Decision**: Build VNC URLs at runtime using HTTP request headers.
- **Rationale**: Support Docker, remote dev, and production environments without environment variable churn.
- **Alternatives Considered**: Static environment variables (too brittle).

### Navigation-Resilient Injection
- **Decision**: Use Playwright's `framenavigated` event to re-inject the JS listener.
- **Rationale**: Ensure operator actions are captured even if they navigate away or reload the page.
- **Alternatives Considered**: Periodic polling (too slow/unreliable).

### Real-time Event Streaming
- **Decision**: Use `page.expose_function` for immediate event delivery.
- **Rationale**: Lower latency and higher reliability than log-scraping or polling.

## Implementation
### Phases
| Phase | Duration | Outcome |
|-------|----------|---------|
| Phase 1: VNC & Frontend | 4h | Live iframe stream working in React |
| Phase 2: Event Capture | 6h | Multi-event interception and bridge established |
| Phase 3: Serialization | 5h | Automated KB updates on Done signal |

### Key Components
- **`VncUrlBuilder`**: Logic for protocol/host mapping and proxy detection.
- **`AutorecordSerializer`**: Logic for merging keystrokes and deduplicating clicks.
- **`human_takeover_node`**: Orchestrator for injection, capture, and resumption.

### Technical Specifications
- **JS Listener**: Captures `click`, `keyup`, `change`, `scroll`.
- **Selector Strategy**: Captures `data-testid`, `aria-label`, `role`, `innerText`, and CSS paths in priority order.
- **Serialization**: Merges individual character events into a single `fill` action for performance.

## Testing
### Strategy
Used TDD for the serialization engine and integration testing for the Playwright bridge.

### Results
| Test Type | Count | Pass Rate |
|-----------|-------|-----------|
| Unit | 12 | 100% |
| Integration | 8 | 100% |
| Manual | 5 | 100% |

### Coverage
Exhaustive coverage of `VncUrlBuilder` and `AutorecordSerializer`. Manual verification of VNC iframe loading across local and remote hosts.

## Deployment
### Procedures
1. Ensure `novnc` and `websockify` are installed in the Docker image.
2. Set `NOVNC_PORT` (default 6080) in environment.
3. Deploy updated frontend and backend.

### Configuration
- `NOVNC_PORT`: Port for the noVNC proxy.
- `EXTERNAL_HOST`: (Optional) Explicit override for VNC host.

### Rollback
Revert to previous version; the Knowledge Base files are append-only and backwards compatible.

## Maintenance
### Monitoring
- Watch for `VNC iframe connection closed` warnings in logs.
- Monitor `learned_workflows.json` size for excessive bloat.

### Common Issues
| Issue | Resolution |
|-------|------------|
| CSP Block | Ensure backend allows `frame-src` for the VNC port. |
| Missing Inputs | Check if the JS listener is being re-injected on navigation. |

## Lessons Learned
- **Dynamic Origin Pattern**: Always build external service URLs at runtime using request headers.
- **Event Debouncing**: Need to implement client-side debouncing to avoid redundant clicks.
- **HITL as Signal**: Human intervention is the highest quality signal for a RAG-based agent.

## References
- Reflection: `memory-bank/reflection/reflection-remote-browser-control-and-autorecording-engine.md`
- Task: `memory-bank/tasks/remote-browser-control-and-autorecording-engine.md`
- Branch: `feature/FEAT-044-remote-takeover-autorecord`

## Future Considerations
- Implement multi-tab recording support.
- Add client-side event debouncing.
- Visual diffing of captured human steps vs AI attempts.
