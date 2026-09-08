#!/usr/bin/env python3
"""
vQA — Build Selector RAG Index (Offline Pipeline)
==================================================
Script: scripts/build_selector_rag.py

Builds the TF-IDF + BM25 index for the selector registry and blueprint skills.
Run this script after updating knowledge/selector_registry.json or blueprints/*.yaml.

The engine also auto-rebuilds the index on startup when it detects a stale index
(registry mtime > .last_built). This script is for explicit manual rebuilds.

Usage
-----
    python scripts/build_selector_rag.py
    make kb-rag-build

Makefile target
---------------
    kb-rag-build:
        $(PYTHON) scripts/build_selector_rag.py

Exit codes
----------
    0 — success
    1 — failure (missing registry, build error)
"""

import logging
import sys
import time
from pathlib import Path

# ── Bootstrap: add project root to sys.path ───────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("build_selector_rag")


def main() -> int:
    """Build the selector RAG index. Returns 0 on success, 1 on failure."""
    from backend.kb.selector_rag import SelectorRAG

    registry_path = _PROJECT_ROOT / "knowledge" / "selector_registry.json"
    blueprints_dir = _PROJECT_ROOT / "knowledge" / "blueprints"
    index_dir = _PROJECT_ROOT / "memory" / "selector_rag"

    if not registry_path.exists():
        logger.error(
            "selector_registry.json not found at %s\nRun 'make kb-refresh' to generate it from the Playwright branch.",
            registry_path,
        )
        return 1

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  vQA RAG Index Build — Selector Registry & Blueprints")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  Registry : %s", registry_path)
    logger.info("  Blueprints: %s", blueprints_dir)
    logger.info("  Index dir : %s", index_dir)
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    rag = SelectorRAG(
        registry_path=registry_path,
        blueprints_dir=blueprints_dir,
        index_dir=index_dir,
    )

    start = time.monotonic()
    try:
        rag.build_index()
    except Exception as exc:
        logger.error("Index build failed: %s", exc)
        return 1

    elapsed = time.monotonic() - start

    # Verify output files
    for fname in ("selector_index.pkl", "skill_index.pkl", ".last_built"):
        if not (index_dir / fname).exists():
            logger.error("Expected output file missing: %s/%s", index_dir, fname)
            return 1

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  ✅ Index build complete in %.1fs", elapsed)
    logger.info("  Output: %s", index_dir)
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return 0


if __name__ == "__main__":
    sys.exit(main())
