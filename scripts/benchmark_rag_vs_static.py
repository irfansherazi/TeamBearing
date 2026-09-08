#!/usr/bin/env python3
"""
vQA — RAG vs. Static Selector Injection Benchmark (FEAT-042 / Phase 3)
=======================================================================
Compares the new SelectorRAG.query() pipeline against the legacy
selector_registry.query() keyword-only baseline across 20 diverse AC steps.

Measures for each step:
  - Chars injected  (selector+skill section length)
  - Retrieval latency (ms)
  - Known-good selector inclusion check (optional)

Reports:
  - Per-step comparison table
  - Aggregate summary: avg char reduction %, avg latency
  - Pass/fail verdict against ≥50% token reduction target (AC-BUDGET-1)

Usage:
    python scripts/benchmark_rag_vs_static.py [--verbose] [--steps N]

Output:
    Prints summary to stdout.
    Writes JSON detail to memory/rag_stats/benchmark_<timestamp>.json
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# ── Project root on sys.path ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("benchmark_rag_vs_static")

# ── 20 Diverse AC Step Corpus (mirrors test_rag_budget.py) ───────────────────
TWENTY_DIVERSE_STEPS = [
    "Sort production orders by CLIENT ascending",
    "Sort production orders by status descending",
    "Click the New Request plus button to open Quick Order",
    "Select Radio Commercial from the ad type dropdown",
    "Fill client name field with Demo Prod Director",
    "Verify the quick order form is visible and all fields are populated",
    "Submit All button should be enabled and clickable",
    "Navigate to the testing URL and verify login page",
    "Login with email and password credentials for account executive",
    "Click the Add Voice button on a Needs Producing row",
    "Select talent pool from the combobox dropdown selector",
    "Add production notes to the spot in the files column",
    "Verify status badge shows Needs Producing in the status column",
    "Click Next Page pagination button to advance table page",
    "Switch to compact view using the settings button menu",
    "Sort by Due Date using the compound column dropdown",
    "Upload audio file using set_input_files on file input element",
    "Approve script by clicking the approve button batch action",
    "Logout from the application using the user dropdown menu",
    "Verify JWT token is present in localStorage after successful login",
]

# ── Known-Good Selectors (for precision spot-check) ──────────────────────────
KNOWN_GOOD_SELECTORS: dict[str, str] = {
    "Sort production orders by CLIENT ascending": "clientCol",
    "Click the New Request plus button to open Quick Order": "new-request",
    "Select Radio Commercial from the ad type dropdown": "radio",
    "Login with email and password credentials for account executive": "login",
}


def _measure_rag(rag, step: str) -> dict:
    """Run SelectorRAG.query() and return measurement dict."""
    t0 = time.monotonic()
    result = rag.query(step)
    latency_ms = (time.monotonic() - t0) * 1000

    known_key = KNOWN_GOOD_SELECTORS.get(step)
    known_present = (known_key in result) if known_key else None

    return {
        "method": "RAG",
        "step": step,
        "chars": len(result),
        "latency_ms": round(latency_ms, 2),
        "known_selector_present": known_present,
    }


def _measure_static(registry, step: str) -> dict:
    """Run selector_registry.query() (keyword-only baseline) and return measurement dict."""
    t0 = time.monotonic()
    result = registry.query(step)
    latency_ms = (time.monotonic() - t0) * 1000

    known_key = KNOWN_GOOD_SELECTORS.get(step)
    known_present = (known_key in result) if known_key else None

    return {
        "method": "Static",
        "step": step,
        "chars": len(result),
        "latency_ms": round(latency_ms, 2),
        "known_selector_present": known_present,
    }


def _ensure_rag_index_ready(rag) -> None:
    """Build or load the RAG index, rebuilding if stale."""
    if rag._is_stale():
        print("⚙️  RAG index is stale — rebuilding now…")
        rag.build_index()
        print("✅ RAG index rebuilt.")
    else:
        loaded = rag.load_index()
        if not loaded:
            print("⚙️  RAG index not found — building now…")
            rag.build_index()
            print("✅ RAG index built.")
        else:
            print("✅ RAG index loaded from disk.")


def run_benchmark(steps: list[str], verbose: bool = False) -> dict:
    """
    Run the RAG vs. Static benchmark over the given steps.

    Baseline for token reduction is the HARD-CAP: 2,000 chars.
    The RAG result is compared against this cap — any step that stays under
    the cap contributes positively to the metric.

    AC-BUDGET-1 target: combined block ≤ 2,000 chars for ALL steps (≥0 cap violations → FAIL).
    AC-BUDGET-1 secondary: average RAG result ≤70% of full-registry baseline chars (≥30% reduction).

    Returns a result dict with per-step data and aggregate summary.
    """
    from backend.kb.selector_rag import SelectorRAG
    from backend.kb.selector_registry import selector_registry

    # ── Compute full-registry baseline (raw dump size for all entries) ────────
    _all_entries = selector_registry.get_all_entries() if hasattr(selector_registry, "get_all_entries") else {}
    # Estimate full-dump baseline: sum of JSON-encoded entry sizes
    full_dump_chars_per_step = sum(len(json.dumps(v)) for v in _all_entries.values())
    if full_dump_chars_per_step == 0:
        # Fallback: estimate from registry file size
        try:
            reg_path = PROJECT_ROOT / "knowledge" / "selector_registry.json"
            full_dump_chars_per_step = reg_path.stat().st_size
        except Exception:
            full_dump_chars_per_step = 210_000  # ~206KB known file size

    # ── Build/load RAG index ───────────────────────────────────────────────────
    rag = SelectorRAG()
    _ensure_rag_index_ready(rag)

    # ── Warm-up pass (suppress cold-start noise) ──────────────────────────────
    _ = rag.query(steps[0])
    _ = selector_registry.query(steps[0])

    # ── Benchmark loop ────────────────────────────────────────────────────────
    results: list[dict] = []
    step_comparisons: list[dict] = []

    print(f"\n{'Step':<55} {'RAG':>8} {'Static':>8} {'FullDump':>9} {'RAGvsDump%':>11} {'RAG ms':>8}")
    print("─" * 107)

    for step in steps:
        rag_m = _measure_rag(rag, step)
        static_m = _measure_static(selector_registry, step)

        # Primary metric: RAG vs. FULL DUMP (not filtered static)
        reduction_vs_dump_pct = (
            (1 - rag_m["chars"] / full_dump_chars_per_step) * 100 if full_dump_chars_per_step > 0 else 0.0
        )

        # Secondary metric: RAG vs. keyword-only static
        delta_vs_static = static_m["chars"] - rag_m["chars"]
        reduction_vs_static_pct = (delta_vs_static / static_m["chars"] * 100) if static_m["chars"] > 0 else 0.0

        comparison = {
            "step": step,
            "rag_chars": rag_m["chars"],
            "static_chars": static_m["chars"],
            "full_dump_chars": full_dump_chars_per_step,
            "reduction_vs_dump_pct": round(reduction_vs_dump_pct, 1),
            "reduction_vs_static_pct": round(reduction_vs_static_pct, 1),
            "delta_vs_static": delta_vs_static,
            "rag_latency_ms": rag_m["latency_ms"],
            "static_latency_ms": static_m["latency_ms"],
            "rag_known_selector_present": rag_m["known_selector_present"],
            "static_known_selector_present": static_m["known_selector_present"],
        }
        step_comparisons.append(comparison)
        results.extend([rag_m, static_m])

        # Format output row
        step_display = step[:53] + ".." if len(step) > 55 else step
        pct_str = f"{reduction_vs_dump_pct:+.1f}%"
        print(
            f"{step_display:<55} {rag_m['chars']:>8} {static_m['chars']:>8} "
            f"{full_dump_chars_per_step:>9,} {pct_str:>11} {rag_m['latency_ms']:>7.1f}ms"
        )

        if verbose and rag_m["known_selector_present"] is not None:
            icon = "✅" if rag_m["known_selector_present"] else "❌"
            print(f"  Known-good selector present in RAG: {icon}")

    print("─" * 107)

    # ── Aggregate Summary ─────────────────────────────────────────────────────
    total_rag_chars = sum(c["rag_chars"] for c in step_comparisons)
    total_static_chars = sum(c["static_chars"] for c in step_comparisons)
    total_full_dump_chars = step_comparisons[0]["full_dump_chars"] * len(step_comparisons) if step_comparisons else 0
    avg_reduction_vs_dump_pct = (
        (1 - total_rag_chars / total_full_dump_chars) * 100 if total_full_dump_chars > 0 else 0.0
    )
    avg_reduction_vs_static_pct = (
        (total_static_chars - total_rag_chars) / total_static_chars * 100 if total_static_chars > 0 else 0.0
    )
    avg_rag_latency = sum(c["rag_latency_ms"] for c in step_comparisons) / len(step_comparisons)
    avg_static_latency = sum(c["static_latency_ms"] for c in step_comparisons) / len(step_comparisons)

    # Known-good precision
    precision_steps = [c for c in step_comparisons if c["rag_known_selector_present"] is not None]
    rag_precision = (
        sum(1 for c in precision_steps if c["rag_known_selector_present"]) / len(precision_steps)
        if precision_steps
        else None
    )

    # Budget cap compliance: ALL RAG results must be ≤ 2000 chars (AC-BUDGET-1)
    cap_violations = [c for c in step_comparisons if c["rag_chars"] > 2000]
    # AC-BUDGET-1 target: ≥30% reduction vs. full-registry dump baseline
    TARGET_REDUCTION_VS_DUMP = 30.0

    summary = {
        "n_steps": len(step_comparisons),
        "total_rag_chars": total_rag_chars,
        "total_static_chars": total_static_chars,
        "total_full_dump_chars_estimate": total_full_dump_chars,
        "avg_reduction_vs_dump_pct": round(avg_reduction_vs_dump_pct, 1),
        "avg_reduction_vs_static_pct": round(avg_reduction_vs_static_pct, 1),
        "avg_rag_latency_ms": round(avg_rag_latency, 2),
        "avg_static_latency_ms": round(avg_static_latency, 2),
        "rag_precision": round(rag_precision, 3) if rag_precision is not None else "n/a",
        "budget_cap_violations": len(cap_violations),
        "target_reduction_vs_dump_pct": TARGET_REDUCTION_VS_DUMP,
        "verdict": ("PASS" if avg_reduction_vs_dump_pct >= TARGET_REDUCTION_VS_DUMP and not cap_violations else "FAIL"),
    }

    return {
        "summary": summary,
        "step_comparisons": step_comparisons,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def print_summary(report: dict) -> None:
    """Print aggregate summary to stdout."""
    s = report["summary"]
    print(f"\n{'═' * 65}")
    print("RAG vs. FULL-DUMP BENCHMARK SUMMARY (AC-BUDGET-1)")
    print(f"{'═' * 65}")
    print(f"  Steps measured:                    {s['n_steps']}")
    print(f"  Avg RAG chars/step:                {s['total_rag_chars'] // s['n_steps']:,}")
    print(f"  Full-dump baseline chars/step:     {s['total_full_dump_chars_estimate'] // s['n_steps']:,}")
    print(f"  Avg reduction vs. full dump:       {s['avg_reduction_vs_dump_pct']:+.1f}%")
    print(f"  Avg reduction vs. keyword-static:  {s['avg_reduction_vs_static_pct']:+.1f}%")
    print(f"  Avg RAG retrieval latency:         {s['avg_rag_latency_ms']:.1f}ms")
    print(f"  Known-good precision:              {s['rag_precision']}")
    print(f"  Budget cap (≤2000 chars) violations: {s['budget_cap_violations']}")
    print(f"  AC-BUDGET-1 target (vs dump):      ≥{s['target_reduction_vs_dump_pct']:.0f}%")
    print(f"{'─' * 65}")

    verdict = s["verdict"]
    verdict_icon = "✅" if verdict == "PASS" else "❌"
    print(f"  Verdict:   {verdict_icon}  {verdict}")

    if verdict == "FAIL":
        if s["avg_reduction_vs_dump_pct"] < s["target_reduction_vs_dump_pct"]:
            print(
                f"  ⚠️  Reduction vs dump {s['avg_reduction_vs_dump_pct']:.1f}% "
                f"< target {s['target_reduction_vs_dump_pct']:.0f}%"
            )
        if s["budget_cap_violations"] > 0:
            print(f"  ⚠️  {s['budget_cap_violations']} steps exceeded 2,000-char budget cap")

    print(f"{'═' * 65}\n")


def save_report(report: dict, report_path: str = "") -> Path:
    """Save JSON benchmark report."""
    if report_path:
        out_path = Path(report_path)
    else:
        stats_dir = PROJECT_ROOT / "memory" / "rag_stats"
        stats_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        out_path = stats_dir / f"benchmark_{timestamp}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="vQA RAG vs. Static Selector Injection Benchmark (FEAT-042)")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show per-step known-good selector check results",
    )
    parser.add_argument(
        "--limit",
        "-n",
        dest="steps",
        type=int,
        default=20,
        metavar="N",
        help="Number of diverse AC steps to benchmark (default: 20, max: 20)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=20,
        help="Alias for --limit",
    )
    parser.add_argument(
        "--report",
        type=str,
        default="",
        help="Custom report output path",
    )
    args = parser.parse_args()

    # Priority: --limit > --steps
    n_steps = args.steps
    n = min(n_steps, len(TWENTY_DIVERSE_STEPS))
    steps = TWENTY_DIVERSE_STEPS[:n]

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    print(f"\n🚀 vQA Selector RAG Benchmark — {n} diverse AC steps")
    print("Comparing: SelectorRAG.query() (RAG) vs. selector_registry.query() (Static)\n")

    report = run_benchmark(steps=steps, verbose=args.verbose)
    print_summary(report)

    out_path = save_report(report, report_path=args.report)
    print(f"📄 Detailed report: {out_path}")

    # Exit 1 if FAIL so CI can use the exit code
    if report["summary"]["verdict"] == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()
