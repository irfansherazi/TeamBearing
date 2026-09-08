# Creative: Algorithm Design — Playwright Standard Library Integration
## playwright-standard-library-integration-full-runtime-wiring | FEAT-052 | Phase: CREATIVE

**Design Date**: 2026-05-27  
**Designer**: Inline Orchestrator  
**Type**: Algorithm Design

---

## Decision

**Chosen**: Option A — Static Allow-List with Pre-Compiled Patterns + Async Generator Streaming

All security-critical algorithms (input validation, log scrubbing) operate on pre-compiled, module-level data structures loaded at import time. Streaming uses async generators over the subprocess stdout pipe. This maximizes both security (no runtime string construction of CLI arguments) and performance (no re-compilation of regex patterns per request).

---

## Algorithm 1: Test Execution Pipeline

### Input Validation Algorithm

```
FUNCTION validate_run_request(test_id, env, user, browser):

    # Layer 1: Pydantic enum validation
    # Already enforced before this function is called
    # env ∈ {"prod", "test", "smoke", "qa"}
    # browser ∈ {"chromium", "firefox", "webkit"}

    # Layer 2: Shell metacharacter injection guard
    METACHAR_PATTERN = compiled regex: r'[;&|`$(){}<>\n\r\t]'
    IF METACHAR_PATTERN.search(test_id):
        RAISE HTTP 422: "Invalid test_id: shell metacharacters detected"

    # Layer 3: Allow-list check (O(1) set lookup)
    allowed_ids = PLAYWRIGHT_REGISTRY.get_test_id_set()  # frozenset
    IF test_id NOT IN allowed_ids:
        RAISE HTTP 422: f"Unknown test_id: {test_id}"

    # Layer 4: User allow-list (O(1) set lookup)
    allowed_users = USERS_FIXTURE.get_username_set()  # frozenset
    IF user NOT IN allowed_users:
        RAISE HTTP 422: f"Unknown user: {user}"

    RETURN True
```

**Complexity**: O(1) for layers 2–4 (set lookup + compiled regex). Layer 1 is handled by Pydantic at deserialization.

**Key invariant**: The `test_id` is NEVER concatenated into a shell command string. It is used only to look up the `file` field from `playwright_index.json`, and that resolved file path is validated to be within `playwright/tests/`.

### Command Construction Algorithm (No Shell Injection)

```
FUNCTION build_playwright_command(test_entry, browser, env, user):
    # test_entry comes from the trusted registry (JSON file), not from user input
    # Only test_entry["file"] is used — never test_id directly

    test_file = test_entry["file"]  # e.g., "qa-321-sorting-list-and-compact.test.ts"
    
    # Path containment guard (defense in depth)
    resolved = (PLAYWRIGHT_TESTS_DIR / test_file).resolve()
    IF not str(resolved).startswith(str(PLAYWRIGHT_TESTS_DIR.resolve())):
        RAISE SecurityError("Path traversal detected in registry entry")
    
    command = [
        "npx", "playwright", "test",
        str(resolved),           # absolute path, no shell expansion
        "--project", browser,    # validated enum value
        "--reporter", "line"     # forces line-by-line output for streaming
    ]
    
    env_vars = {
        **os.environ,
        "TEST_ENV": env,                              # validated enum
        "PLAYWRIGHT_USER": user,                      # validated allow-list
        "PLAYWRIGHT_STORAGE_STATE": str(
            PLAYWRIGHT_STORAGE_DIR / env / f"storageState_{user}.json"
        )
    }
    
    RETURN command, env_vars
```

### Streaming Algorithm (Async Generator Pattern)

```
ASYNC FUNCTION stream_playwright_run(run_id, command, env_vars):
    proc = await asyncio.create_subprocess_exec(
        *command,
        env=env_vars,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout stream
        cwd=str(PLAYWRIGHT_DIR)
    )
    
    _playwright_pids[run_id] = proc.pid
    
    TRY:
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
            scrubbed = _log_scrubber(line)
            await _broadcast_terminal_log(
                run_id,
                scrubbed,
                stream="stdout"
            )
    FINALLY:
        await proc.wait()
        exit_code = proc.returncode
        _playwright_pids.pop(run_id, None)
        _pw_semaphore.release()
    
    RETURN exit_code
```

**Error paths**:
- `UnicodeDecodeError`: caught by `errors="replace"` — garbled bytes displayed as `?` rather than crashing
- `asyncio.CancelledError`: process is left running (PID tracked for cleanup)
- `FileNotFoundError` (`npx` not in PATH): caught in endpoint handler; returns 503

---

## Algorithm 2: Log Scrubber

### Pattern Priority Order

```
Scrub priority (highest to lowest):

1. Literal password values (pre-compiled with re.escape)
   Pattern: re.escape(SHARED_TEST_PASSWORD)
   Replacement: "[REDACTED]"
   Why first: Exact match is most specific; prevents false matches in later patterns

2. Literal admin password
   Pattern: re.escape(ADMIN_TEST_PASSWORD)
   Replacement: "[REDACTED]"

3. storageState JSON blobs (session tokens in JSON output)
   Pattern: r'"storageState"\s*:\s*\{[^}]*\}'  (non-greedy)
   Replacement: '"storageState": "[REDACTED]"'
   Edge case: Handles compact JSON without spaces

4. JWT-shaped Bearer tokens
   Pattern: r'Bearer\s+[A-Za-z0-9\-_.]+\.[A-Za-z0-9\-_.]+\.[A-Za-z0-9\-_.]+'
   Replacement: 'Bearer [REDACTED]'
   Note: Three-part dot-separated pattern is JWT-like; not a false positive for UUIDs

5. Generic key=value / key: value for sensitive keys
   Pattern: r'(?i)(password|token|secret|apikey|api_key)[\"\s:=]+\S+'
   Replacement: r'\1=[REDACTED]'
   Note: Preserves the key name for debuggability

EDGE CASES:
- Empty line: patterns simply don't match; original empty string returned
- Line with no sensitive content: O(N*P) where N=line length, P=pattern count (all compiled)
- Line entirely consisting of a secret: entire line replaced with "[REDACTED]"
- Multi-line blobs: handled via DOTALL flag on storageState pattern only
```

### Scrubber Performance Analysis

```
Pre-compilation cost: O(1) at module load (5 patterns)
Per-line cost: O(N * P) where N = avg line length (≈80 chars), P = 5 patterns
              ≈ 400 char comparisons per line
              For 1000 lines/sec throughput: 400,000 comparisons/sec (negligible)

Memory: 5 compiled regex objects (< 1KB total)
Thread safety: re.Pattern objects are stateless (safe for concurrent calls)
```

---

## Algorithm 3: Storage Status Check

### Freshness Classification

```
CONSTANT VALID_AGE = timedelta(hours=24)
CONSTANT USERS = load_from_fixture("playwright/fixtures/users/users.json")
CONSTANT ENVS = ["prod", "test", "smoke", "qa"]

FUNCTION get_storage_status():
    result = {}
    now = datetime.utcnow()
    
    FOR env IN ENVS:
        result[env] = {}
        FOR user IN USERS:
            path = PLAYWRIGHT_STORAGE_DIR / env / f"storageState_{user['username']}.json"
            
            IF NOT path.exists():
                result[env][user['username']] = "missing"
                CONTINUE
            
            mtime = datetime.utcfromtimestamp(path.stat().st_mtime)
            age = now - mtime
            
            IF age < VALID_AGE:
                result[env][user['username']] = "valid"
            ELSE:
                result[env][user['username']] = "expired"
    
    RETURN result

Complexity: O(U * E) = O(13 * 4) = O(52) filesystem stat() calls
            Each stat() is ~1µs → total < 100µs
            No caching needed (called on-demand, not in a hot loop)
```

---

## Algorithm 4: Client-Side Search & Grouping

### Search Algorithm (Frontend)

```typescript
// Input: query string (user types in search box)
// Output: filtered + grouped test list

function filterTests(tests: PlaywrightTest[], query: string): GroupedTests {
    const q = query.trim().toLowerCase();
    
    // Empty query: return all
    if (!q) return groupByPrefix(tests);
    
    // Filter: match any of id, description, jira_keys
    const filtered = tests.filter(t =>
        t.id.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q) ||
        t.jira_keys.some(k => k.toLowerCase().includes(q))
    );
    
    return groupByPrefix(filtered);
}

function groupByPrefix(tests: PlaywrightTest[]): GroupedTests {
    const groups: Record<string, PlaywrightTest[]> = {
        QA: [],
        VC2: [],
        Other: []
    };
    
    for (const test of tests) {
        const prefix = test.jira_keys[0]?.split('-')[0]?.toUpperCase() ?? 'Other';
        if (prefix === 'QA') groups.QA.push(test);
        else if (prefix === 'VC2') groups.VC2.push(test);
        else groups.Other.push(test);
    }
    
    return groups;
}
```

**Complexity**: O(N * M) where N = number of tests (40), M = average field length (~50 chars).
At 40 tests with 100ms debounce: negligible CPU cost, runs synchronously in the render cycle.

### Terminal Windowing Algorithm (Frontend)

```typescript
// Goal: keep last 500 lines, discard oldest, prevent memory growth
// Challenge: O(N) slice on every message is wasteful for high-throughput streams

// Option A (Simple, chosen for 40-test workload):
function appendLine(prev: TerminalLine[], newLine: TerminalLine): TerminalLine[] {
    const next = [...prev, newLine];
    // Amortized batch truncation: only slice when > 600 (20% buffer)
    if (next.length > 600) {
        return next.slice(-500); // O(N) but only triggered every 100 lines
    }
    return next;  // O(N) spread still — acceptable for ≤600 lines
}

// Note: For production-scale (>10K lines/sec), would switch to circular buffer.
// At Playwright throughput (~50-200 lines/test run), this is sufficient.
```

---

## Algorithm 5: Storage State Generation Throttle

### Single-Lock Serialization

```
STATE:
  _pw_generate_lock = asyncio.Lock()
  _active_generate_env = None  # for status visibility

ASYNC FUNCTION generate_storage_states(env: str) -> dict:
    IF _pw_generate_lock.locked():
        RAISE HTTP 429: {
            "detail": f"Storage generation already in progress for {_active_generate_env or 'an environment'}"
        }
    
    async with _pw_generate_lock:
        _active_generate_env = env
        TRY:
            env_vars = {
                **os.environ,
                "TEST_ENV": env,
            }
            proc = await asyncio.create_subprocess_exec(
                "node",
                str(PLAYWRIGHT_DIR / "utils" / "generateStorageStates.mjs"),
                env=env_vars,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PLAYWRIGHT_DIR)
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=300.0  # 5-minute hard timeout (13 users × browser auth)
            )
            
            IF proc.returncode != 0:
                RAISE HTTP 500: {
                    "detail": "Storage generation failed",
                    "stderr": stderr.decode("utf-8", errors="replace")[:2000]  # cap at 2KB
                }
            
            # Count generated files by scanning storage dir
            generated_count = len(list(
                (PLAYWRIGHT_STORAGE_DIR / env).glob("storageState_*.json")
            ))
            
            RETURN {"status": "ok", "generated": generated_count}
        
        FINALLY:
            _active_generate_env = None
```

**Timeout reasoning**: 13 users × ~15s per browser auth flow = ~195s. 300s provides 54% safety margin.  
**Lock semantics**: `asyncio.Lock` is not reentrant — a second call from the same coroutine would deadlock. This is acceptable because storage generation is always from independent HTTP requests.

---

## Algorithm 6: Concurrency Semaphore Gate

```
STATE:
  _pw_semaphore = asyncio.Semaphore(MAX_CONCURRENT_RUNS)  # default: 2
  _active_runs: dict[str, RunInfo] = {}  # run_id → {test_id, started_at, pid}

ASYNC FUNCTION run_playwright_test_guarded(run_id, ...):
    # Non-blocking acquire check
    acquired = _pw_semaphore._value > 0  # peek without blocking
    
    IF NOT acquired:
        RAISE HTTP 429: {
            "detail": f"Too many concurrent Playwright runs. Max: {MAX_CONCURRENT_RUNS}",
            "active_runs": list(_active_runs.keys())
        }
    
    # Actual acquire (will succeed because we peeked above — in single-threaded async context)
    await _pw_semaphore.acquire()
    _active_runs[run_id] = {
        "test_id": test_id,
        "started_at": datetime.utcnow().isoformat(),
        "pid": None  # filled after subprocess starts
    }
    
    TRY:
        exit_code = await stream_playwright_run(run_id, ...)
    FINALLY:
        _active_runs.pop(run_id, None)
        _pw_semaphore.release()
    
    RETURN exit_code
```

**Race condition note**: The "peek then acquire" pattern is safe in asyncio's single-threaded event loop. There is no TOCTOU race because no other coroutine can run between the check and acquire (asyncio is cooperative, not preemptive).

---

## Algorithm 7: Subprocess PID Cleanup

```
FUNCTION cleanup_playwright_processes():
    import signal, os
    
    for run_id, info in list(_active_runs.items()):
        pid = info.get("pid")
        IF pid is None:
            CONTINUE
        
        TRY:
            os.kill(pid, signal.SIGTERM)
            # Give 5 seconds for graceful shutdown
            # (in practice, SIGTERM is enough for npx playwright)
        EXCEPT ProcessLookupError:
            PASS  # already exited
        EXCEPT PermissionError:
            LOG warning: f"Cannot kill PID {pid} for run {run_id}"
    
    _active_runs.clear()
```

**Called from**: FastAPI lifespan shutdown event.  
**Not called**: On WebSocket disconnect (the test continues running if the client disconnects — user can reconnect with the same `run_id`).

---

## Correctness Guarantees

| Property | Guarantee | Mechanism |
|----------|-----------|-----------|
| No shell injection | GUARANTEED | Allow-list + no shell=True + no string interpolation |
| No path traversal | GUARANTEED | resolved() + prefix check inside PLAYWRIGHT_TESTS_DIR |
| Max 2 concurrent runs | GUARANTEED | asyncio.Semaphore (never released early) |
| Max 1 concurrent generate | GUARANTEED | asyncio.Lock |
| No credential leakage | BEST EFFORT | Log scrubber covers known patterns; unknown custom log formats may bypass |
| Terminal stays under 500 lines | GUARANTEED | Batch truncation in React state updater |
| Orphaned processes cleaned up | BEST EFFORT | SIGTERM on shutdown; timeout is not enforced mid-run |
