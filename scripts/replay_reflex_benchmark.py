#!/usr/bin/env python3
"""
T3-c Reflex Layer Replay Benchmark — FEAT-118-vqa-tier3-architectural-hardening

Deterministic replay harness for the 5 synthetic 2026-07-27 session traces.
Measures reflex hit ratio (reflex_hits / total_retry_attempts) against the
stored .jsonl sessions without a live browser or Bedrock call.

Usage:
    python scripts/replay_reflex_benchmark.py [--replay-dir storage/replay/2026-07-27]
    python scripts/replay_reflex_benchmark.py --verbose

Exit code: 0 = pass (hit_ratio >= 0.40), 1 = fail
"""

import argparse
import json
import pathlib
import sys
import os

# Allow running from project root
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from backend.engine.reflex import attempt_short_circuit  # noqa: E402


def run_benchmark(replay_dir: pathlib.Path, verbose: bool = False) -> dict:
    """
    Load all session_*.jsonl files from replay_dir, run each retry_attempt event
    through reflex.attempt_short_circuit(), and compute the hit ratio.

    Returns a dict with: sessions, total_retries, reflex_hits, hit_ratio, pass
    """
    sessions = sorted(replay_dir.glob("session_*.jsonl"))
    if not sessions:
        return {
            "sessions": 0,
            "total_retries": 0,
            "reflex_hits": 0,
            "hit_ratio": 0.0,
            "pass": False,
            "error": f"No session files found in {replay_dir}",
        }

    reflex_hits = 0
    total_retries = 0
    per_session = []

    for session_file in sessions:
        session_hits = 0
        session_retries = 0
        lines = session_file.read_text().splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") != "retry_attempt":
                continue

            session_retries += 1
            total_retries += 1

            result = attempt_short_circuit(
                event.get("state", {}),
                event.get("error_msg", ""),
                event.get("planned_action", {}),
            )

            if result is not None:
                session_hits += 1
                reflex_hits += 1
                if verbose:
                    print(
                        f"  HIT  [{session_file.name}] signature={result.signature} "
                        f"error_prefix={event.get('error_msg', '')[:60]!r}"
                    )
            else:
                if verbose:
                    print(
                        f"  miss [{session_file.name}] "
                        f"error_prefix={event.get('error_msg', '')[:60]!r}"
                    )

        per_session.append({
            "file": session_file.name,
            "retries": session_retries,
            "hits": session_hits,
            "hit_ratio": session_hits / session_retries if session_retries else 0.0,
        })

    hit_ratio = reflex_hits / total_retries if total_retries > 0 else 0.0
    return {
        "sessions": len(sessions),
        "total_retries": total_retries,
        "reflex_hits": reflex_hits,
        "hit_ratio": hit_ratio,
        "pass": hit_ratio >= 0.40,
        "per_session": per_session,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reflex layer replay benchmark (T3-c)")
    parser.add_argument(
        "--replay-dir",
        default="storage/replay/2026-07-27",
        help="Directory containing session_*.jsonl replay files",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    replay_dir = pathlib.Path(args.replay_dir)
    if not replay_dir.exists():
        print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
        return 1

    print(f"Reflex Replay Benchmark — {replay_dir}")
    print(f"REFLEX_LAYER_ENABLED={os.getenv('REFLEX_LAYER_ENABLED', 'true')}")
    print()

    result = run_benchmark(replay_dir, verbose=args.verbose)

    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 1

    print(f"Sessions:      {result['sessions']}")
    print(f"Total retries: {result['total_retries']}")
    print(f"Reflex hits:   {result['reflex_hits']}")
    print(f"Hit ratio:     {result['hit_ratio']:.2%}")
    print()

    if args.verbose and "per_session" in result:
        print("Per-session breakdown:")
        for s in result["per_session"]:
            status = "PASS" if s["hit_ratio"] >= 0.40 else "----"
            print(f"  [{status}] {s['file']}: {s['hits']}/{s['retries']} ({s['hit_ratio']:.0%})")
        print()

    target = 0.40
    if result["pass"]:
        print(f"AC-INTEGRATION-3: PASS  (hit_ratio={result['hit_ratio']:.2%} >= {target:.0%} target)")
        return 0
    else:
        print(f"AC-INTEGRATION-3: FAIL  (hit_ratio={result['hit_ratio']:.2%} < {target:.0%} target)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
