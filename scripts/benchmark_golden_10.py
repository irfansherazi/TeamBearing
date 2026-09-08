#!/usr/bin/env python3
"""
scripts/benchmark_golden_10.py
================================
TASK-106 Smoke Test — Golden 10 Benchmark

Runs all 10 cards from tests/benchmarks/golden_10_data.json against the
live FastAPI backend using execution_engine='linear'.

Each card is run sequentially. The script polls /status/{run_id} every 5s
until the run reaches a terminal state (completed | failed | timeout | error).

Usage:
    source .venv/bin/activate
    python3 scripts/benchmark_golden_10.py

Environment variables:
    VQA_BASE_URL   Backend URL (default: http://localhost:8000)
    VQA_API_KEY    API key for X-API-Key header (default: empty — omits header)

Output:
    Per-card results printed to stdout.
    Final pass/fail summary with elapsed time.
    Exit code 0 if ALL cards pass, 1 if any fail.
"""

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("VQA_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("VQA_API_KEY", "")
CORPUS_FILE = pathlib.Path(__file__).parent.parent / "tests" / "benchmarks" / "golden_10_data.json"
POLL_INTERVAL_S = 5
PER_CARD_TIMEOUT_S = 360  # 6 minutes hard cap (pipeline itself is 5min)


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def _post_json(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _get_json(path: str) -> dict:
    req = urllib.request.Request(f"{BASE_URL}{path}", method="GET", headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _poll_run(run_id: str, ticket_id: str, timeout_s: float) -> dict:
    """Poll /status/{run_id} until terminal state or timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            status = _get_json(f"/status/{run_id}")
            state = status.get("status", "unknown")
            if state in ("completed", "failed", "timeout", "error"):
                return status
            elapsed = round(time.monotonic() - (deadline - timeout_s), 1)
            print(f"  [{ticket_id}] {state} ... ({elapsed}s)", flush=True)
        except Exception as e:
            print(f"  [{ticket_id}] poll error: {e}", flush=True)
        time.sleep(POLL_INTERVAL_S)

    return {"status": "timeout", "error": "benchmark poll timeout"}


def run_card(card: dict, index: int, total: int) -> dict:
    """Execute a single card and return the result dict."""
    ticket_id = card["ticket_id"]
    print(f"\n[{index}/{total}] Starting {ticket_id}: {card.get('summary', '')}")

    t0 = time.monotonic()
    try:
        resp = _post_json("/execute", {
            "jira_ticket_id": ticket_id,
            "role": "production_manager",
            "execution_engine": "linear",
            "tenant_id": "vpromedia",
        })
    except urllib.error.URLError as e:
        return {
            "ticket_id": ticket_id,
            "status": "error",
            "error": f"POST /execute failed: {e}",
            "elapsed_s": round(time.monotonic() - t0, 1),
        }

    run_id = resp.get("run_id")
    if not run_id:
        return {
            "ticket_id": ticket_id,
            "status": "error",
            "error": f"No run_id in response: {resp}",
            "elapsed_s": round(time.monotonic() - t0, 1),
        }

    print(f"  [{ticket_id}] run_id={run_id}")
    final_status = _poll_run(run_id, ticket_id, PER_CARD_TIMEOUT_S)
    elapsed = round(time.monotonic() - t0, 1)

    result = {
        "ticket_id": ticket_id,
        "run_id": run_id,
        "status": final_status.get("status", "unknown"),
        "pipeline_status": final_status.get("pipeline_status", ""),
        "elapsed_s": elapsed,
        "error": final_status.get("error", ""),
        "analysis": final_status.get("analysis", ""),
    }

    icon = "✅" if result["status"] == "completed" else "❌"
    print(
        f"  {icon} [{ticket_id}] {result['status'].upper()} "
        f"pipeline={result['pipeline_status']} elapsed={elapsed}s"
    )
    if result["error"]:
        print(f"     error: {result['error'][:200]}")
    if result["analysis"]:
        print(f"     analysis: {result['analysis'][:200]}")

    return result


def main():
    print("=" * 60)
    print("TASK-106 SMOKE TEST — Golden 10 Benchmark")
    print(f"Backend: {BASE_URL}")
    print(f"Auth:    {'X-API-Key set' if API_KEY else 'no API key (open endpoint)'}")
    print(f"Corpus:  {CORPUS_FILE}")
    print("=" * 60)

    # Verify backend is alive
    try:
        health = _get_json("/health")
        print(f"Backend health: {health.get('status', 'unknown')}\n")
    except Exception as e:
        print(f"ERROR: Backend not reachable at {BASE_URL}: {e}")
        print("Is ./start.sh running?")
        sys.exit(1)

    cards = json.loads(CORPUS_FILE.read_text())
    total = len(cards)
    results = []

    global_start = time.monotonic()
    for i, card in enumerate(cards, start=1):
        result = run_card(card, i, total)
        results.append(result)

    global_elapsed = round(time.monotonic() - global_start, 1)

    # Summary
    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    passed = [r for r in results if r["status"] == "completed"]
    failed = [r for r in results if r["status"] != "completed"]

    print(f"{'Ticket':<12} {'Status':<12} {'Pipeline':<20} {'Time':>8}")
    print("-" * 56)
    for r in results:
        icon = "✅" if r["status"] == "completed" else "❌"
        print(
            f"{icon} {r['ticket_id']:<10} {r['status']:<12} "
            f"{r.get('pipeline_status',''):<20} {r['elapsed_s']:>6.1f}s"
        )

    print("-" * 56)
    print(f"PASSED: {len(passed)}/{total}")
    print(f"FAILED: {len(failed)}/{total}")
    print(f"Total elapsed: {global_elapsed}s")

    if failed:
        print("\nFailed cards:")
        for r in failed:
            print(f"  - {r['ticket_id']}: {r.get('pipeline_status','')} — {r.get('error','')[:100]}")

    # Write results JSON
    out_path = pathlib.Path(__file__).parent.parent / "tests" / "benchmarks" / "benchmark_golden10_linear.json"
    out_path.write_text(json.dumps({
        "engine": "linear",
        "total": total,
        "passed": len(passed),
        "failed": len(failed),
        "pass_rate": f"{len(passed)}/{total}",
        "elapsed_s": global_elapsed,
        "results": results,
    }, indent=2))
    print(f"\nResults written to: {out_path}")

    sys.exit(0 if len(failed) == 0 else 1)


if __name__ == "__main__":
    main()
