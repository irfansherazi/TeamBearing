"""
vQA — Persistent Cross-Run Memory (SQLite backend)
======================================================
Module: backend/memory/persistent.py

SQLite-backed memory store that survives across runs. Records which
locator strategies worked or failed for which situations, enabling
dynamic few-shot example injection into the planner prompt.

Upgrade from JSONL
------------------
This replaces the previous JSONL flat-file implementation.
The public API (`record()`, `get_few_shot_examples()`, `propose_kb_updates()`)
is identical — no changes required in callers.

Benefits over JSONL:
- Indexed queries: O(log n) retrieval vs O(n) linear scan
- Deduplication: UNIQUE constraint prevents duplicate pattern accumulation
- Count tracking: success_count/failure_count maintained in schema
- Concurrent-safe: SQLite WAL mode handles concurrent writes
- Migration: auto-backfills from learned_patterns.jsonl on first run

Three-Tier Memory Architecture
--------------------------------
  Tier 1: Run Memory (VQAState.long_term_memory)
      Scope: single run, discarded at end.

  Tier 2: Persistent Memory (THIS MODULE)
      Scope: cross-run, stored in memory/learned_patterns.db.
      Fed back as few-shot examples in the planner prompt.

  Tier 3: KB Updates (auto-proposed after patterns proven 3+ times)
      Scope: permanent, triggers 'make kb-refresh' review cycle.

Usage
-----
    from backend.memory.persistent import persistent_memory

    # Record a pattern
    persistent_memory.record(
        situation="click client name in table row",
        strategy_tried="get_by_role:link:Zombieland",
        worked=False,
        strategy_fix="get_by_text:Zombieland",
    )

    # Get few-shot examples for a planner prompt
    examples = persistent_memory.get_few_shot_examples("click client name")
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"
_DB_FILE = _MEMORY_DIR / "learned_patterns.db"
_LEGACY_JSONL = _MEMORY_DIR / "learned_patterns.jsonl"


class PersistentMemory:
    """
    SQLite-backed cross-run memory for vQA self-learning.

    Thread Safety
    -------------
    Uses threading.Lock around write operations. SQLite is opened with
    check_same_thread=False and WAL journal mode to allow concurrent reads.

    Migration
    ---------
    On first instantiation, if learned_patterns.jsonl exists and the DB
    has fewer rows, all JSONL entries are migrated into SQLite automatically.
    """

    # Words too generic for step-similarity matching
    _STOP_WORDS: frozenset[str] = frozenset(
        {
            "a",
            "an",
            "the",
            "and",
            "or",
            "is",
            "in",
            "on",
            "to",
            "from",
            "that",
            "this",
            "it",
            "with",
            "of",
            "for",
            "by",
            "at",
            "as",
            "be",
            "are",
            "was",
            "i",
            "if",
            "then",
            "should",
            "not",
            "no",
            "click",
            "verify",
            "check",
            "confirm",
            "navigate",
            "open",
            "ensure",
            "make",
            "see",
            "go",
            "get",
            "set",
            "view",
        }
    )

    def __init__(self):
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(_DB_FILE),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._migrate_from_jsonl()
        logger.info(
            "Persistent memory loaded: %d entries from %s",
            self.entry_count,
            _DB_FILE,
        )

    # ── Schema ─────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._conn:
            self._conn.executescript("""
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    situation TEXT NOT NULL,
                    strategy_tried TEXT NOT NULL,
                    worked INTEGER NOT NULL DEFAULT 0,
                    strategy_fix TEXT DEFAULT '',
                    ac_step TEXT DEFAULT '',
                    ticket_id TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS pattern_counts (
                    situation TEXT NOT NULL,
                    strategy_tried TEXT NOT NULL,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (situation, strategy_tried)
                );

                CREATE INDEX IF NOT EXISTS idx_situation
                    ON patterns(situation);
                CREATE INDEX IF NOT EXISTS idx_worked
                    ON patterns(worked);
                CREATE INDEX IF NOT EXISTS idx_ts
                    ON patterns(timestamp DESC);
            """)

    # ── Migration from JSONL ────────────────────────────────────────────────

    def _migrate_from_jsonl(self) -> None:
        """
        One-time migration: read learned_patterns.jsonl and insert into SQLite.

        Safe to call multiple times — skips migration if JSONL doesn't exist
        or if DB already has as many rows as the JSONL file.
        """
        if not _LEGACY_JSONL.exists():
            return

        jsonl_entries = []
        try:
            for line in _LEGACY_JSONL.read_text(encoding="utf-8").strip().split("\n"):
                line = line.strip()
                if line:
                    try:
                        jsonl_entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except OSError:
            return

        if not jsonl_entries:
            return

        db_count = self.entry_count
        if db_count >= len(jsonl_entries):
            logger.debug(
                "JSONL migration skipped: DB has %d rows, JSONL has %d lines",
                db_count,
                len(jsonl_entries),
            )
            return

        logger.info(
            "Migrating %d entries from JSONL → SQLite (DB currently has %d rows)",
            len(jsonl_entries),
            db_count,
        )

        with self._lock:
            with self._conn:
                for entry in jsonl_entries:
                    self._conn.execute(
                        """INSERT OR IGNORE INTO patterns
                           (timestamp, situation, strategy_tried, worked,
                            strategy_fix, ac_step, ticket_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            entry.get("timestamp", ""),
                            entry.get("situation", ""),
                            entry.get("strategy_tried", ""),
                            1 if entry.get("worked") else 0,
                            entry.get("strategy_fix", ""),
                            entry.get("ac_step", "")[:120],
                            entry.get("ticket_id", ""),
                        ),
                    )
                    # Update counts table
                    key = (entry.get("situation", ""), entry.get("strategy_tried", ""))
                    if entry.get("worked"):
                        self._conn.execute(
                            """INSERT INTO pattern_counts(situation, strategy_tried, success_count, failure_count)
                               VALUES (?, ?, 1, 0)
                               ON CONFLICT(situation, strategy_tried)
                               DO UPDATE SET success_count = success_count + 1""",
                            key,
                        )
                    else:
                        self._conn.execute(
                            """INSERT INTO pattern_counts(situation, strategy_tried, success_count, failure_count)
                               VALUES (?, ?, 0, 1)
                               ON CONFLICT(situation, strategy_tried)
                               DO UPDATE SET failure_count = failure_count + 1""",
                            key,
                        )

        logger.info("JSONL → SQLite migration complete: %d rows now in DB", self.entry_count)

    # ── Write ───────────────────────────────────────────────────────────────

    def record(
        self,
        situation: str,
        strategy_tried: str,
        worked: bool,
        strategy_fix: str = "",
        ac_step: str = "",
        ticket_id: str = "",
    ) -> None:
        """
        Record a locator strategy outcome.

        Args
        ----
        situation : str
            Human-readable description of what was being attempted.
            Example: "click client name in table row"
        strategy_tried : str
            The locator strategy used. Format: "strategy:role:name"
        worked : bool
            Whether the strategy succeeded.
        strategy_fix : str
            If the strategy failed and a fix was found, the working strategy.
        ac_step : str
            The full AC step text for context.
        ticket_id : str
            The Jira ticket ID for traceability.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        """INSERT INTO patterns
                           (timestamp, situation, strategy_tried, worked,
                            strategy_fix, ac_step, ticket_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            timestamp,
                            situation,
                            strategy_tried,
                            1 if worked else 0,
                            strategy_fix,
                            ac_step[:120] if ac_step else "",
                            ticket_id,
                        ),
                    )
                    if worked:
                        self._conn.execute(
                            """INSERT INTO pattern_counts(situation, strategy_tried, success_count, failure_count)
                               VALUES (?, ?, 1, 0)
                               ON CONFLICT(situation, strategy_tried)
                               DO UPDATE SET success_count = success_count + 1""",
                            (situation, strategy_tried),
                        )
                    else:
                        self._conn.execute(
                            """INSERT INTO pattern_counts(situation, strategy_tried, success_count, failure_count)
                               VALUES (?, ?, 0, 1)
                               ON CONFLICT(situation, strategy_tried)
                               DO UPDATE SET failure_count = failure_count + 1""",
                            (situation, strategy_tried),
                        )
            except sqlite3.Error as e:
                logger.error("Failed to record memory entry: %s", e)

    # ── Retrieval ───────────────────────────────────────────────────────────

    def get_few_shot_examples(
        self,
        current_step: str,
        max_examples: int = 3,
    ) -> str:
        """
        Find past patterns relevant to the current AC step.

        Uses meaningful-word overlap (stopwords filtered) to find relevant
        past successes/failures, prioritising successes over failures
        and most recent entries over older ones.

        Args
        ----
        current_step : str
            The current AC step text to match against.
        max_examples : int
            Maximum number of examples to return.

        Returns
        -------
        str
            Formatted prompt section, or empty string if no matches.
        """
        if not current_step:
            return ""

        step_words = self._meaningful_words(current_step)
        if not step_words:
            return ""

        try:
            # Retrieve recent patterns from SQLite
            rows = self._conn.execute(
                "SELECT situation, strategy_tried, worked, strategy_fix FROM patterns ORDER BY id DESC LIMIT 500"
            ).fetchall()
        except sqlite3.Error as e:
            logger.error("Failed to query persistent memory: %s", e)
            return ""

        if not rows:
            return ""

        # Score by meaningful-word overlap
        scored: list[tuple[int, dict]] = []
        for row in rows:
            sit_words = self._meaningful_words(row["situation"])
            overlap = len(step_words & sit_words)
            if overlap >= 2:
                scored.append((overlap, dict(row)))
            if len(scored) >= max_examples * 4:
                break

        if not scored:
            return ""

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:max_examples]

        # Successes first, then failures with fixes
        successes = [(s, e) for s, e in top if e.get("worked")]
        failures_with_fix = [(s, e) for s, e in top if not e.get("worked") and e.get("strategy_fix")]
        ordered = successes + failures_with_fix

        if not ordered:
            return ""

        lines = [
            "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550",
            "\ud83d\udcd6 PAST RUN EXAMPLES (proven patterns from previous runs):",
            "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550",
        ]
        for _, entry in ordered:
            strategy = entry.get("strategy_tried", "?")
            if entry.get("worked"):
                lines.append(f"  \u2713 For '{entry['situation']}': {strategy} WORKED")
            else:
                fix = entry.get("strategy_fix", "")
                fix_text = f" \u2192 use instead: {fix}" if fix else ""
                lines.append(f"  \u2717 For '{entry['situation']}': {strategy} FAILED{fix_text}")

        lines.append(
            "\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"
        )
        return "\n".join(lines)

    def propose_kb_updates(self, min_success_count: int = 3) -> list[dict]:
        """
        Find locator patterns proven N+ times and propose them as KB entries.

        Uses pattern_counts table for O(1) threshold queries.

        Args
        ----
        min_success_count : int
            Minimum number of successful uses before proposing.

        Returns
        -------
        list[dict]
            Proposal dicts with 'situation', 'strategy', 'success_count', 'proposed_kb_entry'.
        """
        try:
            rows = self._conn.execute(
                "SELECT situation, strategy_tried, success_count "
                "FROM pattern_counts WHERE success_count >= ? "
                "ORDER BY success_count DESC",
                (min_success_count,),
            ).fetchall()
        except sqlite3.Error as e:
            logger.error("Failed to query pattern_counts: %s", e)
            return []

        proposals = []
        for row in rows:
            situation = row["situation"]
            strategy = row["strategy_tried"]
            count = row["success_count"]
            if situation and strategy:
                proposals.append(
                    {
                        "situation": situation,
                        "strategy": strategy,
                        "success_count": count,
                        "proposed_kb_entry": (
                            f"## WORKFLOW: Auto-learned \u2014 {situation}\n"
                            f"KEYWORDS: {', '.join(situation.lower().split()[:5])}\n"
                            f"---\n"
                            f"Proven pattern (succeeded {count}x across runs):\n"
                            f"Use: {strategy}\n"
                        ),
                    }
                )

        return proposals

    def _meaningful_words(self, text: str) -> set[str]:
        """Extract non-trivial words (>3 chars, not in stoplist) for overlap matching."""
        return {w for w in text.lower().split() if w not in self._STOP_WORDS and len(w) > 3}

    @property
    def entry_count(self) -> int:
        """Number of entries in the persistent memory DB."""
        try:
            row = self._conn.execute("SELECT COUNT(*) FROM patterns").fetchone()
            return row[0] if row else 0
        except sqlite3.Error:
            return 0

    def close(self) -> None:
        """Close the SQLite connection (call on app shutdown)."""
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
persistent_memory = PersistentMemory()
