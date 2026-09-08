"""
vQA — Skill Library (Agentic Memory Tier 3)
=============================================
Module: backend/memory/skill_library.py

Persists successful execution sequences ("Skills") extracted when an
AC step is marked SATISFIED by the evaluator.  Each Skill records the
exact parameterized browser actions that worked so the planner can
reuse them on future runs without re-exploring.

Architecture
------------
Storage: JSON-Lines file (skills.jsonl) — one JSON object per line.
  - Append-only writes: no lock contention, safe for concurrent runs.
  - TF-IDF index: rebuilt lazily on first query (or force-rebuild via reload()).
  - Deduplication: same ac_step_text + same action fingerprint → increment
    success_count instead of appending a duplicate.

Skill Schema
------------
{
  "id": "skill-<uuid4_hex8>",        # Unique ID for dedup/lookup
  "ac_step_text": "Click CLIENT...", # The AC step text this skill solves
  "jira_key": "QA-321",             # Ticket that produced this skill
  "role": "account_executive",       # Role logged in when skill was found
  "actions": [                       # Ordered list of executor steps
    {
      "action": "click",
      "strategy": "css_selector",
      "name": "th.po-col-clientCol",
      "value": null,
      "reasoning": "Click CLIENT column header (A-Z sort)"
    },
    ...
  ],
  "success_count": 3,               # How many runs have used this successfully
  "first_seen": "2026-04-17T...",
  "last_seen":  "2026-04-17T...",
}

Usage
-----
    from backend.memory.skill_library import skill_library

    # Write (called by evaluator on SATISFIED)
    skill_library.record_skill(
        ac_step_text="Click CLIENT column header to sort ascending",
        actions=[...],          # list of ExecutionStep dicts
        jira_key="QA-321",
        role="account_executive",
    )

    # Read (called by planner before each Bedrock call)
    prompt_block = skill_library.query(ac_step_text="Click CLIENT...")
"""

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"
_SKILLS_FILE = _MEMORY_DIR / "skills.jsonl"

# Maximum chars of prompt content per injected skill
_MAX_SKILL_PROMPT_CHARS = 1200
# Minimum TF-IDF cosine similarity score to consider a skill match
_SIMILARITY_THRESHOLD = 0.12
# Max skills injected per planner call
_MAX_INJECTED = 2

# Generic words filtered from TF-IDF corpus
_SKIP_WORDS: frozenset[str] = frozenset(
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
        "into",
        "its",
        "has",
        "have",
    }
)


class SkillLibrary:
    """
    Append-only skill store with TF-IDF retrieval.

    Thread Safety
    -------------
    Writes use threading.Lock.  Reads are lock-free (index is rebuilt
    atomically as a local variable then replaced).

    Lazy Indexing
    -------------
    The TF-IDF index is built on the first call to query() after any
    write, or after reload(). This avoids sklearn import overhead at
    startup if skills are never queried in a given process lifetime.
    """

    def __init__(self) -> None:
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._skills: list[dict] = []
        self._vectorizer = None  # sklearn TfidfVectorizer | None
        self._tfidf_matrix = None  # scipy sparse matrix | None
        self._index_dirty = True  # rebuild needed
        self._load()

    # ── I/O ────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load all skills from the JSONL file into memory."""
        if not _SKILLS_FILE.exists():
            logger.info("Skill library: no skills file yet at %s", _SKILLS_FILE)
            return
        loaded = 0
        with open(_SKILLS_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._skills.append(json.loads(line))
                    loaded += 1
                except json.JSONDecodeError:
                    pass
        logger.info("Skill library: loaded %d skill(s) from %s", loaded, _SKILLS_FILE)
        self._index_dirty = True

    def _append_to_disk(self, skill: dict) -> None:
        """Append a single skill record to the JSONL file (caller holds lock)."""
        with open(_SKILLS_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(skill, ensure_ascii=False) + "\n")

    def _flush_to_disk(self) -> None:
        """Rewrite the entire JSONL file (caller holds lock). Used for dedup updates."""
        with open(_SKILLS_FILE, "w", encoding="utf-8") as fh:
            for skill in self._skills:
                fh.write(json.dumps(skill, ensure_ascii=False) + "\n")

    # ── Write ───────────────────────────────────────────────────────────────

    def record_skill(
        self,
        ac_step_text: str,
        actions: list[dict],
        jira_key: str = "",
        role: str = "",
    ) -> str:
        """
        Persist a successful action sequence for an AC step.

        Filters out failed steps (success=False) and non-meaningful actions
        (wait, scroll) before storing.  If an identical fingerprint already
        exists, increments success_count instead of appending a duplicate.

        Args
        ----
        ac_step_text : str
            The AC step text that these actions satisfy.
        actions : list[dict]
            Raw ExecutionStep dicts from VQAState.detailed_execution_log.
            Only steps with success=True are retained.
        jira_key : str
            The Jira ticket ID (e.g. "QA-321").
        role : str
            The vProMedia role key (e.g. "account_executive").

        Returns
        -------
        str
            The skill ID ("skill-<hex>") of the stored or updated record.
        """
        # ── Filter to ONLY successful, meaningful actions ─────────────────
        _SKIP_ACTIONS = {"wait", "scroll", "wait_for_response"}
        clean_actions: list[dict] = []
        for step in actions:
            if not step.get("success", False):
                continue
            action_type = step.get("action_type", step.get("action", ""))
            if action_type in _SKIP_ACTIONS:
                continue
            clean_actions.append(
                {
                    "action": action_type,
                    "strategy": step.get("locator_strategy", ""),
                    "name": step.get("locator_value", ""),
                    "value": step.get("value", None),
                    "reasoning": (step.get("llm_reasoning") or "")[:120],
                }
            )

        if not clean_actions:
            logger.debug("Skill library: no meaningful actions for '%s' — skipping", ac_step_text[:60])
            return ""

        # ── Compute a fingerprint for dedup ──────────────────────────────
        # Fingerprint = sorted tuple of (action, strategy, name) triples.
        # Two runs that solve the same step with the same actions → same fingerprint.
        fingerprint = _make_fingerprint(clean_actions)

        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            # Check for existing skill with same step text + fingerprint
            for existing in self._skills:
                if (
                    _normalize(existing.get("ac_step_text", "")) == _normalize(ac_step_text)
                    and existing.get("fingerprint", "") == fingerprint
                ):
                    existing["success_count"] = existing.get("success_count", 1) + 1
                    existing["last_seen"] = now_iso
                    self._flush_to_disk()
                    self._index_dirty = True
                    logger.info(
                        "Skill library: incremented '%s' (count=%d)",
                        existing["id"],
                        existing["success_count"],
                    )
                    return existing["id"]

            # New skill
            skill_id = f"skill-{uuid.uuid4().hex[:8]}"
            skill: dict[str, Any] = {
                "id": skill_id,
                "ac_step_text": ac_step_text,
                "jira_key": jira_key,
                "role": role,
                "actions": clean_actions,
                "fingerprint": fingerprint,
                "success_count": 1,
                "first_seen": now_iso,
                "last_seen": now_iso,
            }
            self._skills.append(skill)
            self._append_to_disk(skill)
            self._index_dirty = True
            logger.info(
                "Skill library: recorded new skill %s for '%s' (%d actions)",
                skill_id,
                ac_step_text[:60],
                len(clean_actions),
            )
            return skill_id

    # ── Query ───────────────────────────────────────────────────────────────

    def query(self, ac_step_text: str) -> str:
        """
        Retrieve the most relevant skills for an AC step.

        Builds (or reuses) a TF-IDF index over skill ac_step_text fields,
        then returns ≤ _MAX_INJECTED formatted skill blocks for prompt
        injection.

        Args
        ----
        ac_step_text : str
            The current AC step the planner is about to plan.

        Returns
        -------
        str
            Formatted skill block for system prompt injection.
            Empty string if no relevant skills found.
        """
        if not ac_step_text or not self._skills:
            return ""

        self._maybe_rebuild_index()

        if self._vectorizer is None or self._tfidf_matrix is None:
            return ""

        try:
            import numpy as np
            from sklearn.metrics.pairwise import cosine_similarity

            query_vec = self._vectorizer.transform([ac_step_text])
            scores = cosine_similarity(query_vec, self._tfidf_matrix).flatten()
            top_indices = np.argsort(scores)[::-1]

            results: list[tuple[float, dict]] = []
            for idx in top_indices:
                if len(results) >= _MAX_INJECTED:
                    break
                score = float(scores[idx])
                if score < _SIMILARITY_THRESHOLD:
                    break
                results.append((score, self._skills[idx]))

        except Exception as e:
            logger.warning("Skill library query failed: %s", e)
            return ""

        if not results:
            return ""

        return _format_skills_for_prompt(results)

    def reload(self) -> None:
        """Reload from disk and mark index dirty."""
        with self._lock:
            self._skills.clear()
        self._load()

    @property
    def skill_count(self) -> int:
        return len(self._skills)

    # ── TF-IDF index ────────────────────────────────────────────────────────

    def _maybe_rebuild_index(self) -> None:
        """Rebuild TF-IDF index if dirty. No-op if clean."""
        if not self._index_dirty:
            return
        if not self._skills:
            return
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            corpus = [
                " ".join(
                    [
                        s.get("ac_step_text", ""),
                        s.get("jira_key", ""),
                        s.get("role", "").replace("_", " "),
                        " ".join(
                            f"{a.get('action', '')} {a.get('name', '')} {a.get('reasoning', '')}"
                            for a in s.get("actions", [])
                        ),
                    ]
                )
                for s in self._skills
            ]
            vec = TfidfVectorizer(
                stop_words="english",
                ngram_range=(1, 2),
                max_features=5000,
            )
            mat = vec.fit_transform(corpus)
            self._vectorizer = vec
            self._tfidf_matrix = mat
            self._index_dirty = False
            logger.debug(
                "Skill library: TF-IDF index rebuilt — %d skills, %d features",
                mat.shape[0],
                mat.shape[1],
            )
        except ImportError:
            logger.warning("Skill library: sklearn not available — query disabled")
        except Exception as e:
            logger.error("Skill library: index build failed: %s", e)


# ── Module-level helpers ────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace for dedup comparison."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _make_fingerprint(actions: list[dict]) -> str:
    """Stable fingerprint for a list of actions (order-sensitive)."""
    parts = []
    for a in actions:
        parts.append(f"{a.get('action', '')}/{a.get('strategy', '')}/{a.get('name', '')}")
    return "|".join(parts)


def _format_skills_for_prompt(results: list[tuple[float, dict]]) -> str:
    """Format retrieved skills as a system-prompt injection block."""
    separator = "═" * 63
    lines = [
        f"\n{separator}",
        "🧠 SKILL LIBRARY — Proven successful action sequences:",
        "(These EXACT steps solved this AC step in a previous run.",
        " Reuse them verbatim before trying other approaches.)",
        separator,
    ]
    for score, skill in results:
        lines.append(
            f"\n  [Skill: {skill['id']} | confidence={score:.2f} | "
            f"used {skill['success_count']}x | ticket={skill.get('jira_key', '')}]"
        )
        lines.append(f'  AC Step: "{skill["ac_step_text"][:100]}"')
        lines.append("  Proven steps (execute in order):")
        for i, action in enumerate(skill.get("actions", [])[:8], 1):
            action_str = json.dumps({k: v for k, v in action.items() if v and k != "reasoning"})
            action_str = action_str[: _MAX_SKILL_PROMPT_CHARS // max(len(skill["actions"]), 1)]
            reasoning = action.get("reasoning", "")
            lines.append(f"    {i}. {action_str}")
            if reasoning:
                lines.append(f"       # {reasoning[:80]}")
    lines.append(separator)
    return "\n".join(lines)


# ── Module-level singleton ──────────────────────────────────────────────────
skill_library = SkillLibrary()
