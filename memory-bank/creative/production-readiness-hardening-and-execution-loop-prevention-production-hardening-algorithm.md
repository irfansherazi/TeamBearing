# Algorithm Decision: Stagnation Detection & Visual Delta Verification

**Created**: 2026-05-31T19:35:00Z
**Status**: DECIDED
**Decision Type**: Algorithm
**Task**: production-readiness-hardening-and-execution-loop-prevention / FEAT-062

---

## Problem Statement

Two distinct algorithmic problems must be solved for production-readiness-hardening-and-execution-loop-prevention:

**Problem A — Amnesic Loop Stagnation Detection (Pillar 1)**
The agent executes actions that succeed mechanically (Playwright reports no error) but produce zero semantic progress — the URL and DOM structure remain identical across N consecutive actions. Currently there is no detection for this class of loop; the only protection is the AC-level circuit breaker (trips after 8 total actions on one AC step), which is too blunt. The agent must detect *semantic stagnation* specifically and apply a lower threshold (3 consecutive null-outcome actions).

**Problem B — Visual Delta Pixel Difference (Pillar 2)**
The existing `cv_fallback_state_change_check` has three signals (URL diff, ARIA diff, DOM count diff) but none catches canvas-rendered changes or SPA animations where the DOM structure is unchanged but the visual output is different. A fourth signal based on pixel-level screenshot comparison is needed, with a noise floor threshold to avoid false positives from JPEG compression artifacts or cursor blink.

---

## Inputs & Outputs

### Problem A: Stagnation Detection

#### Inputs
| Name | Type | Size/Range | Source |
|------|------|------------|--------|
| `_prev_page_state_snapshot` | `dict` | 2 keys: `url` (str), `element_count` (int \| None) | `VQAState` (carried from last tick) |
| `latest_step` | `ExecutionStep` dict | Variable | LangGraph state `execution_log[-1]` |
| `amnesic_loop_count` | `int` | 0–N | `VQAState` |
| `ac_step_index` | `int` | 0–N | `VQAState` |

#### Outputs
| Name | Type | Description |
|------|------|-------------|
| `is_stagnant` | `bool` | True if URL and element count both unchanged |
| `updated_snapshot` | `dict` | New snapshot to store in state for next tick |
| `new_loop_count` | `int` | Incremented or reset counter |
| `should_trip` | `bool` | True when `new_loop_count >= _AMNESIC_LOOP_THRESHOLD` |

#### Edge Cases
1. `element_count` unavailable in `latest_step` → return `is_stagnant=False` (fail-safe, non-stagnant)
2. First action (empty snapshot) → return `is_stagnant=False`, populate snapshot
3. AC step advances → counter resets to 0 (handled externally by evaluator, same as `retry_count`)
4. Failed action (`success=False`) → skip stagnation check entirely (failed actions don't indicate stagnation)

---

### Problem B: Visual Delta Pixel Difference

#### Inputs
| Name | Type | Size/Range | Source |
|------|------|------------|--------|
| `pre_screenshot_b64` | `str` | Base64 PNG/JPEG, ~50–300KB decoded | Captured before CV click in executor |
| `post_screenshot_b64` | `str` | Base64 PNG/JPEG, same dimensions | Captured inside `cv_fallback_state_change_check` |
| `threshold` | `float` | 0.0–1.0, default 0.005 | Caller-configurable |

#### Outputs
| Name | Type | Description |
|------|------|-------------|
| `has_visual_change` | `bool` | True if pixel diff ratio >= threshold |

#### Edge Cases
1. PIL not installed → return `True` (fail-open, preserve existing behavior)
2. Images have different dimensions → return `True` (dimensions changed = something changed)
3. Identical images → ratio = 0.0 → return `False`
4. JPEG compression artifacts → ratio < 0.005 → return `False` (noise floor rejection)
5. Base64 decode error → log warning, return `True` (fail-open)

---

## Constraints

### Performance Requirements (Problem A)
- **Maximum Latency**: < 1ms per check (synchronous, no I/O; pure dict lookup + integer comparison)
- **Throughput**: Called once per executor action cycle (typically 1–3 actions/second)
- **Memory Budget**: < 1KB per run (snapshot is 2 scalar fields)

### Performance Requirements (Problem B)
- **Maximum Latency**: < 500ms for 1920×1080 screenshot comparison (PIL numpy ops are fast)
- **Throughput**: Called only on CV fallback path (rare, < 5% of actions)
- **Memory Budget**: < 10MB peak (two decoded images + diff array; released immediately)

### Scale Requirements
- **Current**: Typically 10–50 actions per AC step; 9 AC steps per run
- **Expected Growth**: 10× with parallel ticket pool (FEAT-060) — still < 10 stagnation checks/second total
- **Peak Load**: 3 parallel runs → 3 concurrent stagnation checks (trivial)

### Other Constraints
- PIL/Pillow must be imported lazily with try/except for fail-open behavior
- Stagnation counter must be in `VQAState` (cross-iteration persistence) — not in a class variable
- Visual delta function must be pure (no side effects) for unit testability

---

## Options Explored

### Problem A: Stagnation Detection Algorithm

#### Option A1: URL+ElementCount Dual Signal (Chosen)

**Approach**: Compare two signals between consecutive successful actions:
1. Page URL (exact string match)
2. DOM element count (`document.querySelectorAll('*').length`)

Both must be unchanged for the action to be classified as stagnant. Single unchanged signal is not sufficient (e.g., URL stable but DOM growing is not stagnation; DOM stable but redirect pending is not stagnation).

**Pseudocode**:
```python
def _detect_amnesic_loop(state, latest_step):
    snapshot = state.get("_prev_page_state_snapshot", {})
    if not snapshot:
        # First action: initialize snapshot, non-stagnant
        new_snap = {
            "url": latest_step.get("post_url", ""),
            "element_count": latest_step.get("post_element_count"),
        }
        return False, new_snap

    current_url = latest_step.get("post_url", "")
    current_count = latest_step.get("post_element_count")

    url_unchanged = (current_url == snapshot.get("url", "")) and current_url != ""
    count_unchanged = (
        current_count is not None
        and snapshot.get("element_count") is not None
        and current_count == snapshot["element_count"]
    )

    is_stagnant = url_unchanged and count_unchanged

    new_snap = {"url": current_url, "element_count": current_count}
    return is_stagnant, new_snap
```

**Time Complexity**:
- Best: O(1) — two string compare + two int compare
- Average: O(len(url)) — URL string comparison (URLs typically < 256 chars)
- Worst: O(len(url)) — same

**Space Complexity**: O(1) — fixed 2-key dict

**Data Structures**: Python dict (2 keys), string, int

**Pros**:
- Extremely fast — no I/O, no async, no LLM calls
- Two independent signals reduces false positive rate substantially
- Element count is already collectable by executor with minimal overhead
- Fail-safe: missing data defaults to non-stagnant

**Cons**:
- Element count is a coarse signal — SPA DOM mutations that add/remove equal elements cancel out
- URL won't catch hash-change navigation in SPAs without `#` awareness
- Cannot distinguish a legitimately idempotent action (e.g., clicking an already-selected radio) from true stagnation

**Best For**: Server-rendered apps, Angular/PrimeNG apps with DOM mutations on interaction
**Worst For**: Canvas-heavy apps where no DOM changes ever occur (but those are covered by Pillar 2)

---

#### Option A2: Scroll Position + Action-Type Heuristic

**Approach**: Track scroll position (Y offset) in addition to URL/DOM. Mark scroll actions as inherently non-stagnant even if DOM doesn't change (scroll CAN produce progress by revealing new content).

**Pros**:
- Reduces false positives where legitimate scroll reveals new content
- Scroll position adds a third independent signal

**Cons**:
- Adds a third async Playwright call (`page.evaluate("window.scrollY")`) per action — latency ~5ms
- Complicates the snapshot dict by 1 field
- The current production-readiness-hardening-and-execution-loop-prevention spec explicitly says: "Stagnant = URL unchanged AND element_count unchanged" — scroll is not in spec

**Technical Fit**: Medium — adds Playwright overhead
**Complexity**: Low-Medium

---

#### Option A3: Semantic Embedding Similarity of ARIA Tree

**Approach**: Capture ARIA tree snapshot after each action; compute cosine similarity between consecutive snapshots. Cosine similarity above 0.99 = stagnant.

**Pros**:
- Highest semantic richness — ARIA tree captures true rendered state
- Handles SPA mutations and canvas apps

**Cons**:
- ARIA tree serialization is already a bottleneck in the planner prompt
- Embedding computation requires an LLM call or sklearn TF-IDF — adds latency and cost per action
- Contradicts "Programmatic Tier 1 Verification" principle (LLM should be last resort)
- Overkill for the problem — URL+DOM is sufficient for the 3-consecutive threshold

**Technical Fit**: Low — violates Programmatic Tier 1
**Complexity**: High

---

### Problem B: Visual Delta Algorithm

#### Option B1: PIL ImageChops.difference + Non-Zero Pixel Ratio (Chosen)

**Approach**:
1. Base64-decode both images
2. Open with `PIL.Image.open(BytesIO(...))`
3. Convert both to RGB (normalizes format differences)
4. Resize `post` to match `pre` dimensions if they differ (covers minor viewport shifts)
5. `diff = ImageChops.difference(pre_rgb, post_rgb)`
6. Convert diff to grayscale → numpy array
7. Compute `ratio = np.count_nonzero(arr) / arr.size`
8. Return `ratio >= threshold` (default 0.005)

**Pseudocode**:
```python
def _visual_delta_check(pre_b64: str, post_b64: str, threshold: float = 0.005) -> bool:
    try:
        from PIL import Image, ImageChops
        import numpy as np
        pre_img = Image.open(BytesIO(base64.b64decode(pre_b64))).convert("RGB")
        post_img = Image.open(BytesIO(base64.b64decode(post_b64))).convert("RGB")
        if pre_img.size != post_img.size:
            post_img = post_img.resize(pre_img.size, Image.LANCZOS)
        diff = ImageChops.difference(pre_img, post_img)
        arr = np.array(diff.convert("L"))  # grayscale
        ratio = np.count_nonzero(arr) / arr.size
        return ratio >= threshold
    except ImportError:
        logger.warning("PIL not available — skipping visual delta check (fail-open)")
        return True
    except Exception as e:
        logger.debug("Visual delta check failed: %s", e)
        return True  # fail-open
```

**Time Complexity**:
- O(W × H) — linear in image pixel count
- For 1920×1080: ~2M pixels, ~10ms with numpy

**Space Complexity**: O(W × H) — 3 image arrays in memory simultaneously (pre, post, diff)

**Data Structures**: PIL Image objects, numpy uint8 arrays

**Pros**:
- Proven approach — PIL/ImageChops.difference is the standard library method for image comparison
- Threshold-tunable — noise floor rejection built in
- Handles JPEG compression artifacts (ratio < 0.005 = truly identical)
- Fail-open on import error preserves existing behavior
- Pure function — no side effects, easily unit-testable with synthetic images

**Cons**:
- Allocates 3 image arrays (~18MB for 1920×1080 RGB) — released immediately, but peak is notable
- Slow for very high-res screenshots (4K = 8M pixels = ~40ms) — acceptable since CV path is rare
- JPEG artifacts with different quality settings could cause false positives if threshold is too low

**Best For**: SPA color/animation changes, modal overlays, canvas chart updates
**Worst For**: Pure positional changes that don't change pixel values (rare)

---

#### Option B2: Structural Similarity Index (SSIM)

**Approach**: Use `skimage.metrics.structural_similarity` to compute SSIM score. SSIM below 0.999 = changed.

**Pros**:
- More perceptually accurate — SSIM accounts for luminance, contrast, and structure
- Handles compression artifacts better than pixel diff

**Cons**:
- Slower: SSIM is O(W × H × window²) — ~100ms for 1080p
- Requires `scikit-image` (already a transitive dep via sklearn, but not always guaranteed)
- Overkill for the use case — we just need "did anything change?", not "how much did it change?"
- More complex threshold tuning (SSIM range is 0–1; 0.999 is empirically determined)

**Technical Fit**: Medium
**Complexity**: Medium

---

#### Option B3: Perceptual Hash (dHash)

**Approach**: Compute difference hash (dHash) of each image; Hamming distance > threshold = changed.

**Pseudocode**:
```python
def dhash(img, hash_size=8):
    img = img.convert("L").resize((hash_size+1, hash_size))
    pixels = np.array(img)
    diff = pixels[:, 1:] > pixels[:, :-1]
    return diff.flatten()

distance = np.count_nonzero(dhash(pre) ^ dhash(post))
changed = distance > 3  # threshold: 3+ bits differ
```

**Pros**:
- Extremely fast: O(1) — reduces image to 64-bit hash
- Memory-efficient: no large arrays
- Robust to minor crops and resizes

**Cons**:
- High information loss — subtle SPA renders (small UI state change) may not flip enough hash bits
- Threshold tuning is fragile (3 bits = arbitrary)
- False negatives for small-but-meaningful canvas changes
- The use case requires sensitivity to ~0.5% of pixels — perceptual hash is too coarse

**Technical Fit**: Low — too lossy for this use case
**Complexity**: Low

---

## Complexity Comparison

| Metric | A1 (URL+Count) | A2 (+ScrollY) | A3 (ARIA Embed) |
|--------|----------------|----------------|-----------------|
| Time | O(len(URL)) ≈ O(1) | O(len(URL)) + 5ms I/O | O(N×V²) LLM |
| Space | O(1) | O(1) | O(N) |
| Async I/O | None | 1 Playwright call | 1 LLM call |
| Implementation | Simple | Simple | Complex |

| Metric | B1 (Pixel Diff) | B2 (SSIM) | B3 (dHash) |
|--------|-----------------|-----------|------------|
| Time | O(W×H) ~10ms | O(W×H×w²) ~100ms | O(1) ~1ms |
| Space | O(W×H) ~18MB peak | O(W×H) ~18MB peak | O(1) |
| Sensitivity | High | Very High | Low |
| Implementation | Simple | Medium | Simple |

---

## Performance Projection

**Problem A at current scale** (50 actions/step × 9 steps = 450 checks/run):
- Option A1: 450 × ~0.01ms = **4.5ms total overhead** — negligible
- Option A3: 450 × ~500ms = **225 seconds** — completely unacceptable

**Problem B at current scale** (CV fallback fires ~5 times per run):
- Option B1: 5 × ~10ms = **50ms total overhead** — negligible
- Option B2: 5 × ~100ms = **500ms total overhead** — acceptable but wasteful

---

## Decision

**Chosen**:
- Problem A: **Option A1 — URL+ElementCount Dual Signal**
- Problem B: **Option B1 — PIL ImageChops.difference + Non-Zero Pixel Ratio**

### Rationale

**A1** is the mathematically simplest algorithm that satisfies the constraints: O(1) time, zero I/O, two independent Boolean signals that together give a robust definition of semantic stagnation. The 3-consecutive threshold plus the dual-signal requirement eliminates false positives on legitimate slow loads.

**B1** is the PIL standard library approach — well-understood, battle-tested, correct for the use case. The 0.5% pixel ratio threshold is tuned specifically for JPEG artifacts (which rarely exceed 0.1% non-zero after re-encode) while catching real SPA state changes (which typically move ≥ 1% of pixels). The fail-open fallback on PIL unavailability is critical for backward compatibility.

### Trade-offs Accepted

| Trade-off | Why Acceptable |
|-----------|----------------|
| A1: Equal DOM add/remove cancels stagnation signal | Real-world stagnation (scroll loops, wait loops) doesn't produce DOM mutations — the loop specifically affects no-change actions |
| A1: Hash-change SPA routing not detected by URL | Hash-change navigation is visible in element count change when new content renders |
| B1: 18MB peak memory per CV check | CV fallback is rare (< 5% of actions); images are immediately GC'd after comparison |
| B1: 0.5% threshold empirically chosen | Unit tests will validate with synthetic near-identical JPEG pairs |

---

## Implementation Details

### Problem A: Data Structures

| Structure | Purpose | Operations |
|-----------|---------|------------|
| `_prev_page_state_snapshot: dict` | Carries {url, element_count} across evaluator ticks | O(1) get/set |
| `amnesic_loop_count: int` | Tracks consecutive stagnant action count | O(1) increment/reset |

### Problem A: Algorithm Steps

1. `evaluator_node` checks `success=True` gate — skip stagnation check on failures
2. Call `_detect_amnesic_loop(state, latest_step)` — pure function
3. If `is_stagnant`: increment counter; else reset to 0
4. If `counter >= 3`: route to `human_takeover`, inject `agent_critique`
5. Otherwise: write `amnesic_loop_count` and `_prev_page_state_snapshot` into returned state dict (merged at end of evaluator's success path return)

### Problem A: Reset Conditions

Counter resets to 0 when:
- `is_stagnant=False` (URL or DOM changed)
- `ac_step_index` advances (same as `retry_count` reset at line ~250 in evaluator)
- Human takeover completes and execution resumes

### Problem B: Algorithm Steps

1. Before `page.mouse.click(x, y)` in executor CV path: `pre_b64 = await capture_screenshot_b64(run_id)`
2. Execute the coordinate click
3. Pass `pre_screenshot_b64=pre_b64` to `cv_fallback_state_change_check(...)`
4. Inside verifier: after Signals 1-3, call `_visual_delta_check(pre_b64, post_b64, threshold=0.005)`
5. `post_b64 = await capture_screenshot_b64(run_id)` — captured inside verifier before comparison
6. Return `True` if ratio >= 0.005

### Edge Case Handling

| Edge Case | Problem A | Problem B |
|-----------|-----------|-----------|
| Missing data | Default non-stagnant | Fail-open True |
| Import error | N/A | Fail-open True, log warning |
| Decode error | N/A | Fail-open True, log debug |
| Size mismatch | N/A | Resize post to pre dimensions |
| Empty snapshot | Init snapshot, non-stagnant | N/A |
| Failed action | Skip check entirely | N/A |

---

## Testing Strategy

### Problem A: Unit Tests (`tests/engine/test_evaluator.py`)

| Test | Assertion |
|------|-----------|
| `test_amnesic_loop_detection_3_consecutive` | Mock 3 identical URL+count actions → `_next_node == "human_takeover"` |
| `test_amnesic_loop_does_not_fire_on_url_change` | URL changes on action 3 → no trip |
| `test_amnesic_loop_does_not_fire_below_threshold` | Only 2 consecutive stagnant → planner route |
| `test_amnesic_loop_resets_on_ac_step_advance` | Counter resets to 0 when `ac_step_index` increments |
| `test_detect_amnesic_loop_missing_element_count` | `post_element_count=None` → `is_stagnant=False` |
| `test_detect_amnesic_loop_empty_snapshot` | Empty snapshot → `is_stagnant=False`, snapshot initialized |

### Problem B: Unit Tests (`tests/engine/test_verifier.py` or `test_cv_fallback.py`)

| Test | Assertion |
|------|-----------|
| `test_visual_delta_identical_images` | Same image × 2 → `False` |
| `test_visual_delta_changed_images` | Different b64 strings → `True` |
| `test_visual_delta_noise_below_threshold` | < 0.5% pixels differ → `False` |
| `test_visual_delta_no_pil` | Mock ImportError → `True` (fail-open) |
| `test_visual_delta_size_mismatch` | Different dimensions → `True` |
| `test_cv_fallback_integrates_visual_delta` | `pre_screenshot_b64` passed → Signal 4 evaluated |

### Performance Benchmarks

- A1: Benchmark 1000 consecutive calls — expect < 10ms total
- B1: Benchmark on 1920×1080 image — expect < 50ms single call

---

## Next Steps

1. Implement `_detect_amnesic_loop()` as pure helper in `evaluator.py`
2. Add `amnesic_loop_count: int` and `_prev_page_state_snapshot: dict` to `VQAState` and `make_initial_state`
3. Add post-action URL/element-count capture in `executor.py` dispatch loop
4. Implement `_visual_delta_check()` as pure helper in `verifier.py`
5. Add `pre_screenshot_b64` parameter to `cv_fallback_state_change_check`
6. Wire pre-screenshot capture in executor's CV fallback path
7. Write all RED tests first, verify they fail, then implement GREEN
