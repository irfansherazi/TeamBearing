# Creative: Architecture — Playwright Standard Library Integration
## playwright-standard-library-integration-full-runtime-wiring | FEAT-052 | Phase: CREATIVE

**Design Date**: 2026-05-27  
**Designer**: Inline Orchestrator  
**Type**: Architecture Design

---

## Decision

**Chosen**: Option A — New Sub-Module `backend/api/playwright_routes.py` + Updated Registry

Split Playwright-specific endpoints into a dedicated FastAPI router (`playwright_routes.py`) and update `PlaywrightRegistry` to point at the canonical `playwright/playwright_index.json`. This keeps `routes.py` under 100KB (currently 90KB), maintains clean separation of concerns, and allows Playwright-specific middleware (log scrubber, semaphore) to be scoped without polluting the main router.

---

## System Architecture

### Current State (Baseline)

```
backend/api/routes.py  (90KB, 2800+ lines)
    └─ GET /playwright/tests  →  PlaywrightRegistry.list_tests()
            └─ PlaywrightRegistry reads from: backend/playwright_tests/ (WRONG)
                (stub with demo.spec.ts only)

frontend/src/components/PlaywrightLibrary.tsx
    └─ Embedded sub-component inside ExecutionPanel
    └─ Shows tests but no run capability, no config, no storage mgmt
```

### Target State (playwright-standard-library-integration-full-runtime-wiring)

```
backend/
├── api/
│   ├── routes.py            (unchanged except: include_router + compat shim for /playwright/tests)
│   └── playwright_routes.py [NEW]  ← all /playwright/* endpoints
│       ├── GET  /playwright/tests
│       ├── POST /playwright/run         (semaphore + PID tracking + scrubber)
│       ├── GET  /playwright/storage/status
│       └── POST /playwright/storage/generate  (asyncio.Lock throttle)
├── storage/
│   └── playwright_registry.py  [MODIFIED]  ← re-pointed to playwright/playwright_index.json
└── main.py  [MODIFIED]  ← lifespan shutdown → SIGTERM orphaned PIDs

playwright/
├── playwright_index.json    (canonical, 40 entries, pre-existing)
├── fixtures/users/users.json  [NEW]  ← 13 users with email+username+role
├── storage/
│   ├── prod/                (storageState_*.json)
│   ├── test/
│   ├── smoke/
│   └── qa/
└── utils/generateStorageStates.mjs  (pre-existing)

frontend/src/
├── pages/
│   └── PlaywrightPage.tsx   [NEW]  ← standalone full page
├── components/
│   ├── PlaywrightLibrary.tsx  [MODIFIED/DEPRECATED]  ← keep for ExecutionPanel compat
│   ├── TestBrowserPanel.tsx   [NEW sub-component]
│   ├── TestConfigPanel.tsx    [NEW sub-component]
│   ├── RunControlPanel.tsx    [NEW sub-component]
│   └── StorageManagerPanel.tsx [NEW sub-component]
└── router.tsx  [MODIFIED]  ← add /playwright route
```

---

## Option Analysis

### Option A (Chosen): New Sub-Module `playwright_routes.py`

```python
# backend/api/playwright_routes.py
from fastapi import APIRouter

playwright_router = APIRouter(prefix="/playwright", tags=["Playwright"])

# Registered in routes.py or main.py:
app.include_router(playwright_router)
```

**Pros**:
- `routes.py` doesn't grow past 90KB
- Playwright-specific state (`_playwright_pids`, `_pw_semaphore`, `_pw_generate_lock`) is scoped to the sub-module
- Easier to test in isolation (`TestClient(playwright_router)`)
- Log scrubber is defined once in `playwright_routes.py` — no risk of re-use in unrelated endpoints

**Cons**:
- One extra file to discover for new developers
- Need to ensure `include_router` happens before `app.openapi()` is called

**Mitigation**: Clear docstring at the top of `routes.py` listing all included sub-routers.

---

### Option B: All Endpoints in `routes.py`

**Pros**: Single file; consistent with current pattern
**Cons**: `routes.py` grows to 110KB+; semaphore state is mixed with AI agent state; makes unit testing harder

**Rejected**: Code hygiene outweighs single-file consistency for a 90KB file.

---

### Option C: Separate FastAPI Sub-Application (mounted at `/playwright`)

**Pros**: Complete isolation; own lifespan
**Cons**: Loses shared auth middleware; separate OpenAPI docs; CORS headers duplicate; WebSocket routing becomes complex (two WS servers)

**Rejected**: Over-engineered for a single feature; WebSocket sharing is critical.

---

## Component Architecture

### Backend Components

#### `backend/api/playwright_routes.py` [NEW]

```
Module-Level State:
  _playwright_pids: dict[str, int]      # run_id → subprocess PID
  _pw_semaphore: asyncio.Semaphore(2)   # max 2 concurrent runs
  _pw_generate_lock: asyncio.Lock()     # one generate at a time

Functions:
  _log_scrubber(line: str) -> str
      - Masks SHARED_TEST_PASSWORD value
      - Masks ADMIN_TEST_PASSWORD value
      - Masks storageState JSON blobs (tokens)
      - Pattern: re.sub(r'(password|token|storageState)[\"\s:=]+\S+', '[REDACTED]', line, re.I)

Endpoints:
  GET  /playwright/tests         → PlaywrightRegistry.list_tests()
  POST /playwright/run           → validate → semaphore → subprocess → stream WS
  GET  /playwright/storage/status → filesystem scan per user×env
  POST /playwright/storage/generate → lock → node generateStorageStates.mjs
```

#### `backend/storage/playwright_registry.py` [MODIFIED]

```python
# Before:
PLAYWRIGHT_INDEX_FILE = os.getenv("PLAYWRIGHT_INDEX_FILE", "backend/playwright_tests/")

# After:
PLAYWRIGHT_INDEX_FILE = os.getenv(
    "PLAYWRIGHT_INDEX_FILE",
    str(Path(__file__).parent.parent.parent / "playwright" / "playwright_index.json")
)
```

Registry loads JSON at startup (or on first request). Falls back gracefully if file missing (returns empty list with warning log).

#### `backend/main.py` Shutdown Hook [MODIFIED]

```python
@app.on_event("shutdown")
async def _cleanup_playwright_processes():
    from backend.api.playwright_routes import _playwright_pids
    for run_id, pid in list(_playwright_pids.items()):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
```

### Frontend Components

#### Route Architecture

```
/playwright  →  PlaywrightPage.tsx (protected route)
    ├── Tab: "Test Library"  (default)
    │   ├── TestBrowserPanel   (left ~35% width)
    │   ├── TestConfigPanel    (right, conditional on selection)
    │   └── RunControlPanel    (right, conditional on run state)
    └── Tab: "Storage Manager"
        └── StorageManagerPanel  (full width)
```

#### State Management

All state is local to `PlaywrightPage.tsx` — no Redux, no global state, no persistence:

```typescript
// PlaywrightPage.tsx state
const [tests, setTests] = useState<PlaywrightTest[]>([]);
const [selectedTestId, setSelectedTestId] = useState<string | null>(null);
const [config, setConfig] = useState<RunConfig>({ env: 'test', user: 'DemoSalesExec', browser: 'chromium' });
const [runState, setRunState] = useState<RunState>('idle'); // 'idle' | 'starting' | 'running' | 'complete'
const [terminalLines, setTerminalLines] = useState<TerminalLine[]>([]);
const [exitCode, setExitCode] = useState<number | null>(null);
const [activeTab, setActiveTab] = useState<'library' | 'storage'>('library');
```

#### WebSocket Integration

Reuses `useWebSocket` hook pattern with a new `terminal_log` message type:

```typescript
// In RunControlPanel — WebSocket message handling
case 'terminal_log':
    setTerminalLines(prev => {
        const next = [...prev, { line: msg.line, stream: msg.stream }];
        return next.length > 500 ? next.slice(-500) : next; // windowing
    });
    break;
case 'completed':
case 'failed':
    setExitCode(msg.exit_code ?? (msg.type === 'failed' ? 1 : 0));
    setRunState('complete');
    break;
```

---

## Data Flow Diagrams

### Test Run Data Flow

```
User                Frontend           Backend                    Playwright
 │                     │                  │                           │
 │ Click "Run Test"     │                  │                           │
 │────────────────────▶│                  │                           │
 │                     │ POST /playwright/run                         │
 │                     │─────────────────▶│                           │
 │                     │                  │ validate test_id          │
 │                     │                  │ acquire semaphore         │
 │                     │                  │ create_subprocess_exec    │
 │                     │                  │────────────────────────▶ │
 │                     │ {run_id, status}  │                           │
 │                     │◀─────────────────│                           │
 │                     │                  │                           │
 │                     │ WS connect(run_id)│                           │
 │                     │─────────────────▶│                           │
 │                     │                  │  stdout line              │
 │                     │                  │◀────────────────────────│
 │                     │                  │  _log_scrubber(line)     │
 │                     │                  │  _broadcast_terminal_log │
 │                     │ WSTerminalLogMsg  │                           │
 │                     │◀─────────────────│                           │
 │ Lines stream         │                  │                           │
 │◀────────────────────│                  │                           │
 │                     │                  │  process.returncode=0     │
 │                     │                  │◀────────────────────────│
 │                     │                  │  WSTerminalMessage(done) │
 │                     │ ✅ PASSED badge   │                           │
 │◀────────────────────│                  │                           │
```

### Storage Generation Data Flow

```
User             Frontend            Backend              Node.js
 │                  │                   │                    │
 │ Click "Refresh    │                   │                    │
 │  Auth (prod)"     │                   │                    │
 │──────────────────▶│                   │                    │
 │                   │ POST /storage/generate {env: "prod"}  │
 │                   │──────────────────▶│                    │
 │                   │                   │ acquire Lock       │
 │                   │                   │ node generateSS.mjs│
 │                   │                   │──────────────────▶ │
 │                   │                   │                    │ creates 13 files
 │                   │                   │◀──────────────────│
 │                   │ {status: ok, generated: 13}           │
 │                   │◀─────────────────│                    │
 │ "✅ 13/13 users"  │                   │                    │
 │◀──────────────────│                   │                    │
```

---

## Security Architecture

### Input Validation Layer (Defense in Depth)

```
Request arrives at POST /playwright/run
    │
    ├─ Layer 1: Pydantic Schema (PlaywrightRunRequest)
    │   ├─ env: Literal["prod","test","smoke","qa"]   → 422 on invalid
    │   ├─ browser: Literal["chromium","firefox","webkit"]  → 422
    │   └─ test_id: str (raw string, no validation yet)
    │
    ├─ Layer 2: Shell Injection Guard (in endpoint handler)
    │   └─ METACHAR_RE = re.compile(r'[;&|`$(){}<>]')
    │       if METACHAR_RE.search(test_id):
    │           raise HTTPException(422, "Invalid test_id: shell metacharacters")
    │
    ├─ Layer 3: Allow-List Check
    │   └─ if test_id not in registry.get_test_ids():
    │           raise HTTPException(422, f"Unknown test_id: {test_id}")
    │
    └─ Layer 4: User Allow-List
        └─ users = load_users_fixture()
            if user not in [u["username"] for u in users]:
                raise HTTPException(422, f"Unknown user: {user}")
```

### Log Scrubber Design

```python
import re
import os

# Pre-compile at module load for performance
_SCRUB_PATTERNS = [
    # Literal password values from env
    (re.compile(re.escape(os.getenv("SHARED_TEST_PASSWORD", "PLACEHOLDER"))), "[REDACTED]"),
    (re.compile(re.escape(os.getenv("ADMIN_TEST_PASSWORD", "PLACEHOLDER"))), "[REDACTED]"),
    # storageState JSON blobs (session tokens)
    (re.compile(r'"storageState"\s*:\s*\{[^}]+\}', re.DOTALL), '"storageState": "[REDACTED]"'),
    # JWT-shaped strings (Bearer tokens)
    (re.compile(r'Bearer\s+[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+'), 'Bearer [REDACTED]'),
    # Generic password/token key-value patterns
    (re.compile(r'(password|token|secret)[\"\s:=]+\S+', re.IGNORECASE), r'\1=[REDACTED]'),
]

def _log_scrubber(line: str) -> str:
    for pattern, replacement in _SCRUB_PATTERNS:
        line = pattern.sub(replacement, line)
    return line
```

---

## Process Management Architecture

### Subprocess Lifecycle

```
POST /playwright/run called
    ├─ _pw_semaphore.acquire() (or 429 if saturated)
    ├─ proc = await asyncio.create_subprocess_exec(
    │       "npx", "playwright", "test", test_file,
    │       "--project", browser,
    │       cwd=str(PLAYWRIGHT_DIR),
    │       env={**os.environ, "TEST_ENV": env, "PLAYWRIGHT_USER": user},
    │       stdout=asyncio.subprocess.PIPE,
    │       stderr=asyncio.subprocess.STDOUT
    │   )
    ├─ _playwright_pids[run_id] = proc.pid
    ├─ async for line in proc.stdout:
    │   await _broadcast_terminal_log(run_id, _log_scrubber(line.decode()))
    ├─ await proc.wait()
    ├─ exit_code = proc.returncode
    ├─ del _playwright_pids[run_id]
    └─ _pw_semaphore.release()
```

### Cleanup on Shutdown

```python
# main.py — lifespan or on_event("shutdown")
async def _cleanup_playwright():
    from backend.api.playwright_routes import _playwright_pids
    import signal, os
    for run_id, pid in list(_playwright_pids.items()):
        try:
            os.kill(pid, signal.SIGTERM)
            _playwright_pids.pop(run_id, None)
        except (ProcessLookupError, PermissionError):
            pass
```

---

## File Dependency Map

```
playwright_index.json (canonical)
    ↑ read by
PlaywrightRegistry.py
    ↑ imported by
playwright_routes.py ──────────────────────── routes.py (include_router)
    ↑ uses
_broadcast_terminal_log() ← already in routes.py
    ↑ broadcasts to
WebSocket connections (existing /ws/{run_id} hub)
    ↑ consumed by
useWebSocket.ts (frontend hook)
    ↑ used by
PlaywrightPage.tsx > RunControlPanel.tsx
```

---

## Risk Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `npx playwright` not found in PATH | Medium | Validate at startup; return descriptive 503 if missing |
| `playwright_index.json` stale (tests added) | Low | Log warning on load; provide `scripts/sync_playwright_index.py` for manual refresh |
| Zombie subprocess on frontend disconnect | Medium | Timeout: kill process after 10 min if no WS receiver |
| Memory leak: terminalLines > 500 | Low | Windowing enforced in React state mutation |
| concurrent `generate` floods disk I/O | Low | `asyncio.Lock` enforces serialization |
| `test_id` path traversal via `..` | High | Allow-list eliminates path construction entirely |
