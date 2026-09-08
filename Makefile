# vQA Makefile
# ========================================================
# Common tasks for developing and maintaining the vQA agent.
#
# Usage:
#   make kb-refresh       — Regenerate KB from Playwright branch
#   make kb-human-sync    — Upload human-learned selectors → Bedrock KB
#   make kb-human-peek    — Preview staging file contents without syncing
#   make test             — Run Python tests
#   make lint             — Run flake8
#
# Required env vars for kb-human-sync (set in .env):
#   S3_BUCKET, S3_PREFIX
#   BEDROCK_ROLES_KB_ID
#   BEDROCK_KB_DATA_SOURCE_ID   ← add this if not already in .env

.PHONY: kb-refresh kb-rag-build kb-human-sync kb-human-peek test lint

# Python interpreter — use project venv if available, else system python3
PYTHON ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

# Default Playwright branch worktree path
PW_ROOT ?= /tmp/vqa-pw-branch

# ── kb-refresh ─────────────────────────────────────────────────────────────
# Regenerates the selector registry and workflow KB files from the
# vsuitePlatform Playwright branch.
#
# Now uses sync_playwright.py for selectors (with backup and protected support)
# and extract_playwright_kb.py for workflows and timing.
#
kb-refresh:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  vQA KB Refresh — Playwright Branch Extraction"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@if [ ! -d "$(PW_ROOT)" ]; then \
		echo "  → Checking out Playwright branch to $(PW_ROOT)..."; \
		cd .. && git worktree add $(PW_ROOT) remotes/origin/Doc/qa-playwright-test-creation || \
		(echo "ERROR: Could not create worktree. Ensure remote branch exists." && exit 1); \
	else \
		echo "  → Using existing checkout at $(PW_ROOT)"; \
	fi
	@echo "  → Running Sync Tool for Selectors..."
	$(PYTHON) scripts/sync_playwright.py \
		--playwright-root $(PW_ROOT) \
		--kb-path knowledge/selector_registry.json
	@echo "  → Running KB extractor for Workflows..."
	$(PYTHON) scripts/extract_playwright_kb.py \
		--playwright-root $(PW_ROOT) \
		--output-dir knowledge \
		--skip-existing \
		--append-timing
	@echo "  → Cleaning up worktree..."
	@if [ "$(PW_ROOT)" = "/tmp/vqa-pw-branch" ]; then \
		cd .. && git worktree remove $(PW_ROOT) --force 2>/dev/null || true; \
	fi
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  ✓ KB refresh complete. Review knowledge/ and commit:"
	@echo "    git add knowledge/ && git commit -m 'chore: refresh KB from Playwright branch'"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

sync-playwright:
	$(PYTHON) scripts/sync_playwright.py --playwright-root playwright

# ── kb-rag-build ────────────────────────────────────────────────────────────
# Builds the TF-IDF + BM25 index for selector registry and blueprint skills.
# Run after 'make kb-refresh' to update the RAG index with new selectors.
# The engine also auto-rebuilds when it detects a stale index at startup.
#
# Usage:
#   make kb-rag-build
#
kb-rag-build:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  vQA RAG Index Build — Selector Registry & Blueprints"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	$(PYTHON) scripts/build_selector_rag.py

# ── test ───────────────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest tests/ -v

# ── lint ───────────────────────────────────────────────────────────────────
lint:
	$(PYTHON) -m ruff check backend/ tests/ scripts/

ruff-fix:
	$(PYTHON) -m ruff check backend/ tests/ scripts/ --fix
	$(PYTHON) -m ruff format backend/ tests/ scripts/

# ── kb-human-sync ──────────────────────────────────────────────────────────
# Upload human-learned selectors from knowledge/human_learned.jsonl to S3
# and trigger a Bedrock Knowledge Base ingestion job.
#
# Run this after any human takeover session to teach the agent the correct
# selectors it was stuck on. Ingestion takes ~2-5 minutes to complete.
#
# Requires in .env (or exported shell env):
#   S3_BUCKET                  — target S3 bucket
#   S3_PREFIX                  — S3 key prefix (e.g. "vqa")
#   BEDROCK_ROLES_KB_ID        — Bedrock KB ID
#   BEDROCK_KB_DATA_SOURCE_ID  — Data source ID within the KB
#   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_BEDROCK_REGION
#
# Advanced usage:
#   make kb-human-sync DRY_RUN=--dry-run    # preview without uploading
#   make kb-human-sync NO_ARCHIVE=--no-archive  # keep staging file intact
#
DRY_RUN    ?=
NO_ARCHIVE ?=

kb-human-sync:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  vQA KB Human Sync — uploading human-learned selectors"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@. .env 2>/dev/null || true; \
	$(PYTHON) scripts/sync_human_kb.py $(DRY_RUN) $(NO_ARCHIVE)


# ── kb-human-peek ─────────────────────────────────────────────────────────
# Pretty-print the current staging file without syncing.
# Useful for reviewing what selectors will be uploaded before running sync.
#
kb-human-peek:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  vQA KB Human Staging — $(shell wc -l < knowledge/human_learned.jsonl 2>/dev/null || echo 0) record(s)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@if [ -s knowledge/human_learned.jsonl ]; then \
		$(PYTHON) scripts/sync_human_kb.py --dry-run --no-archive; \
	else \
		echo "  (staging file is empty — run the agent and perform a takeover first)"; \
	fi
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
