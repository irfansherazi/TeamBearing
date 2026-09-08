# High-Stakes ADOPTs — Handoff to Phase 3 Adversarial Pass

**work_slug**: vqa-success-factors
**run_id**: 20260716-13383c61b543
**framing_sha**: 13383c61b543
**Total ADOPTs**: 12
**High-stakes count**: 3 (cap)
**Deferred low-stakes ADOPTs**: 9 (see synthesis draft; not queued for adversarial review — they are additive config/telemetry changes or retentions of existing patterns)

> Read this file as a self-contained handoff. Do not read the synthesis draft to make your challenges — the point is procedural independence. Each block below carries the claim, its evidence anchors, the stakes, and the trigger flags. Challenge each on its own terms.
>
> Note: This file overwrites a prior "Adversarial: 0 challenges" stub written before the five lane cards were produced. That stub was correct at the time (no evidence had been synthesized yet); this version reflects the completed synthesis.

---

### HS-ADOPT-1 — DR-004: DOM-programmatic-first tiered verification (with cap-asymmetry correction)

**Verdict row (from synthesis draft)**:
> Formalize DOM-programmatic-first tiered verification (Tier 1 Playwright DOM check → Tier 2 LLM Claude Haiku fallback only when Tier 1 lacks selector_hint or `visual_check` type present). Correct the programmatic-vs-LLM cap asymmetry (TC-4: programmatic FAILED at total ≥ 4; LLM FAILED at total ≥ 6).

**Rationale (from evidence)**:
- Academic (A, Advani 2606.09863): non-LLM detectors reach AUROC 0.83–0.95 vs LLM 0.65 at 3,300× lower latency.
- Practitioner (B, Braintrust): no LLM-judge configuration exceeded AUROC 0.65 on false-success detection across 5 models × 5 prompts.
- Practitioner (B, Getmaxim.ai): 66% LLM-judge agreement ceiling with human experts; 1-in-3 verdicts wrong.
- Codebase (A, verifier.py:1-61 + TC-4): tiered verifier already exists; programmatic-vs-LLM caps asymmetric (4 vs 6); asymmetry is not documented as intentional.

**Why high-stakes** (3 triggers):
- **Central/critical-path**: every step verdict in every run routes through the verifier. This is *the* run-verdict authority.
- **Broad blast radius**: a change to Tier 1/Tier 2 routing logic changes the outcome distribution of every future run — including runs already in flight if hot-deployed.
- **Thin evidence for high impact on the specific cap-alignment claim**: the AUROC evidence justifies preferring DOM-programmatic; it does not directly justify a specific numeric target for aligning the 4-vs-6 asymmetry. Aligning caps could accelerate or delay legitimate failures in ways not directly measured by external sources.

**Adversarial angles worth pressing**:
1. If Tier 1 programmatic caps escalate at ≥4 and Tier 2 LLM caps escalate at ≥6, is the asymmetry actually a feature (more retries where DOM signal is unavailable) rather than a bug? Codebase card called it unintentional but did not cite an original design doc.
2. Advani's non-LLM detectors are TF-IDF text detectors, not DOM-state detectors. The category-transfer from "TF-IDF beats LLM" to "Playwright DOM checks beat LLM" is intuitive but not directly measured in the cited evidence.
3. What happens to `visual_check`-typed ACs (e.g. brand assertions, layout comparisons) if Tier 2 is deprioritized? Codebase card notes Tier 2 is invoked "when `visual_check` type present or no `selector_hint`" — the routing branch matters, and current ADOPT wording preserves it, but subtle changes could regress visual-only ACs.

---

### HS-ADOPT-2 — DR-006: Role-credential isolation (fresh session per run, non-refreshable short TTL, per-role auth)

**Verdict row (from synthesis draft)**:
> Enforce role-credential isolation: fresh session per run (no session-inheritance across runs), non-refreshable short-TTL agent sessions, per-role auth token separation.

**Rationale (from evidence)**:
- Practitioner (B, WorkOS): delegated human tokens carry full permission scope — agent inheriting admin session becomes admin, producing false passes on role-gated ACs. "When the user's session is eventually revoked, the agent may break in ways that are hard to trace."
- Practitioner (B, Scalekit): provider-specific token TTLs (Google APIs 1h, GitHub App 8h, Slack 12h, Zendesk 24-48h); concurrent-refresh race conditions corrupt auth state.
- Practitioner (B, FutureAGI): silent trajectory corruption on mid-task expiry — agent types next planned form value into login form field, appearing as navigation error not auth error.

**Why high-stakes** (3 triggers):
- **Hard-to-reverse (one-way door for auth architecture)**: if the auth path is refactored to enforce short-TTL non-refreshable sessions, rollback requires re-enabling long-lived session inheritance — which the ADOPT explicitly targets as unsafe.
- **Central/critical-path**: every run authenticates before execution; a broken pre-flight or session-issue path halts all runs.
- **Broad blast radius**: role-specific tests (viewer / editor / admin) depend on the intended role token being live; any misrouting produces false passes or false failures across an entire test class.

**Adversarial angles worth pressing**:
1. All three supporting sources are B-grade practitioner blogs; the ADOPT gate is satisfied (≥2 independent B) but this is not A-grade evidence. What is the failure mode if the ADOPT is wrong and long-lived shared sessions are actually preferable in a controlled QA environment?
2. "Non-refreshable" plus "per-role" plus "per-run" implies N-role × M-runs distinct session provisioning. What is the operational cost of this at scale? Cost is not addressed in the evidence.
3. Josh's memory (`project_vqa_environments`) notes: "tests always target qa.vcreative.net regardless of environment." Is the role-isolation intervention needed on a controlled QA target as much as on a live production tenant? The evidence is from live-agent-in-production contexts (WorkOS, Scalekit); QA-target contexts may differ.

---

### HS-ADOPT-3 — DR-010: State-hash no-progress detector (independent of framework recursion_limit)

**Verdict row (from synthesis draft)**:
> Add a state-hash-based no-progress detector independent of the framework recursion_limit, aligned with LangGraph #6731 workaround guidance. Complement (do not replace) the existing amnesic loop CB, which should also be upgraded (TC-3).

**Rationale (from evidence)**:
- Academic (B, Hou et al. 2607.01641): static analysis of 6,549 LLM agent repos found IAL (Infinite Agentic Loop) failures in 47 projects with recursion limits set; framework-induced feedback paths survive the limit.
- OSS (B, LangGraph issue #6731): the recommended workaround for the 1.0.6 regression is explicitly "inject a state-hash no-progress check."
- Practitioner (C, rajatpandit.com): recommends state-embedded TTL + semantic cache checking last 3 turns.
- Codebase (A, TC-3): current amnesic CB uses URL + element count only; systemPatterns.md explicitly documents this as an unreliable signal ("Visual Delta Trust Signal Anti-Pattern").

**Why high-stakes** (3 triggers):
- **Central/critical-path**: interacts with the existing amnesic CB (evaluator.py:507-522) which is on the hot path for every step; a state-hash detector adds latency/complexity to every evaluator invocation.
- **Contradicts discourse**: the Codebase card TC-3 explicitly warns the current URL+element-count signal is broken — yet this ADOPT proposes to extend (not replace) it with a state-hash detector. If the current signal is broken, why keep it? The ADOPT says "complement, do not replace" without evidence that both signals together are additive rather than compounding-FP.
- **Thin evidence for high impact**: only three sources cite the state-hash pattern (Academic B + OSS B + Practitioner C). The pattern is intuitive but not empirically measured for FP/FN rate in a production QA agent context. Rolling it into a critical CB path without measurement is a change with a large blast radius.

**Adversarial angles worth pressing**:
1. What exactly gets hashed? DOM subtree hash, tool-call-argument hash, planner action hash, or full state channel hash? Each has different FP/FN profiles. The evidence doesn't specify — production integration is left to the implementer, so the "ADOPT" is essentially "ADOPT the direction," not "ADOPT the specific mechanism."
2. If DR-010 is added and TC-3 (the current amnesic breaker) is fixed independently, are we double-counting the intervention? The ADOPT says "complement, do not replace" — this may be a conflation of two separate fixes (fix the existing signal *or* add a new one) being sold as one.
3. Semantic cache checking "last 3 turns" (rajatpandit.com, Practitioner C) is a heuristic with no measured production FP rate. Adopting it based on a C-grade single source pushes the aggregate evidence toward the edge of the gate — 1×B (Hou), 1×B (LangGraph issue), 1×C (rajatpandit). Gate technically met (2×B); marginal.

---

## For the adversarial reviewer

- Each block above stands alone — no need to read the synthesis draft to challenge them.
- The three chosen HS-ADOPTs share a common theme: they are the ADOPTs where the pattern direction is well-evidenced but the specific implementation choice is not. Focus your adversarial pressure on the implementation-detail gap, not the pattern direction.
- If you conclude an HS-ADOPT should be demoted to BORROW or DEFER, cite which specific implementation-detail gap justifies the demotion.
- No deferred challenges to re-spike: 12 ADOPTs total, 3 flagged, 9 are low-stakes (config-value changes, retention of existing patterns, additive telemetry) and do not require adversarial review per the trigger criteria.
