"""
backend/engine/review_rule_additions.py
=======================================
Hard checks, code assignment, and checklist writes for new AI Review rules.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from backend.engine.review_rule_summaries import save_plain_language
from backend.engine.review_rules import (
    _ITEM_RE,
    _SECTION_RE,
    checklist_path_for,
)

MIN_IDEA_CHARS = 24
MAX_IDEA_CHARS = 1200
MAX_IDEA_WORDS = 160
MAX_WORDING_CHARS = 480
PROPOSAL_TTL_SEC = 30 * 60
OTHER_SECTION = "__other__"

_REJECT_PATTERNS = (
    re.compile(r"\bignore (all )?((the )?rules|the checklist)\b", re.I),
    re.compile(r"\bdelete all rules\b", re.I),
    re.compile(r"\bskip (all )?(the )?(rules|checklist)\b", re.I),
    re.compile(r"\bdo not (score|check|review)\b", re.I),
    re.compile(r"\boverride (all )?existing rules\b", re.I),
    re.compile(r"\bjailbreak\b", re.I),
    re.compile(r"\blorem ipsum\b", re.I),
    re.compile(r"lazy dogs? jumps over", re.I),
    re.compile(r"quick brown fox", re.I),
)

_SECTION_PREFIXES = (
    ("open-ended", "OE"),
    ("deep dive", "LD"),
    ("logic", "LD"),
    ("hygiene", "PH"),
    ("collaboration", "PH"),
    ("test", "T"),
    ("doc", "D"),
    ("function", "F"),
    ("code quality", "CQ"),
)

_proposal_lock = threading.Lock()
_proposals: dict[str, dict[str, Any]] = {}
_file_lock = threading.Lock()


class ReviewRuleIdeaError(Exception):
    """Raised when a proposed idea is not allowed to become a rule."""


def sanitize_rule_idea(raw: str) -> str:
    """
    Trim and reject empty, huge, or jailbreak-style ideas.

    @param raw: User text
    @returns Cleaned idea
    """
    idea = re.sub(r"\s+", " ", (raw or "")).strip()
    if len(idea) < MIN_IDEA_CHARS:
        raise ReviewRuleIdeaError(
            "That is too short to be a review rule. Say what should be checked on a PR."
        )
    if len(idea) > MAX_IDEA_CHARS or len(idea.split()) > MAX_IDEA_WORDS:
        raise ReviewRuleIdeaError(
            "That is too long. Paste the idea in a few sentences, not a full Copilot dump."
        )
    for pattern in _REJECT_PATTERNS:
        if pattern.search(idea):
            raise ReviewRuleIdeaError("No. That is not a valid review rule.")
    return idea


def prefix_for_section(section_name: str) -> str:
    """
    Pick the checklist family for a section heading.

    @param section_name: Section label or Other
    @returns Prefix such as CQ or F
    """
    lowered = (section_name or "").strip().lower()
    if not lowered or lowered == OTHER_SECTION:
        return "NR"
    for needle, prefix in _SECTION_PREFIXES:
        if needle in lowered:
            return prefix
    return "NR"


def next_rule_id(prefix: str, existing_ids: list[str]) -> str:
    """
    Return the next unused id for a prefix (max existing + 1).

    @param prefix: CQ, F, NR, ...
    @param existing_ids: Ids already in the checklist
    @returns Next id such as CQ-34
    """
    safe_prefix = re.sub(r"[^A-Z]", "", (prefix or "NR").upper()) or "NR"
    numbers: list[int] = []
    pattern = re.compile(rf"^{re.escape(safe_prefix)}-(\d+)$", re.I)
    for rule_id in existing_ids:
        match = pattern.match(rule_id)
        if match:
            numbers.append(int(match.group(1)))
    nxt = (max(numbers) if numbers else 0) + 1
    return f"{safe_prefix}-{nxt:02d}"


def resolve_section_name(section: str, other_name: str) -> str:
    """
    Use the picked section, or a new heading when Other is chosen.

    @param section: Dropdown value
    @param other_name: Name typed for Other
    @returns Section heading to save under
    """
    picked = (section or "").strip()
    if picked and picked != OTHER_SECTION:
        return picked
    custom = re.sub(r"\s+", " ", (other_name or "")).strip()
    if len(custom) < 3:
        raise ReviewRuleIdeaError("Name the new section in a few words.")
    if len(custom) > 60:
        raise ReviewRuleIdeaError("Section name is too long.")
    return custom


def append_rule_bullet(markdown: str, section_name: str, rule_id: str, wording: str) -> str:
    """
    Insert one checklist bullet under a ### section (creating it if needed).

    @param markdown: Full checklist file
    @param section_name: Heading without the number
    @param rule_id: Assigned code
    @param wording: Official rule sentence
    @returns Updated markdown
    """
    bullet = f"- **[{rule_id}]** {wording.strip()}"
    text = markdown.replace("\r\n", "\n")
    ended_with_newline = text.endswith("\n")
    lines = text.split("\n")
    headers: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = _SECTION_RE.match(line)
        if match:
            headers.append((index, match.group(1).strip()))

    target_start: int | None = None
    target_end = len(lines)
    for idx, (line_no, name) in enumerate(headers):
        if name.lower() == section_name.lower():
            target_start = line_no
            if idx + 1 < len(headers):
                target_end = headers[idx + 1][0]
            break

    if target_start is None:
        next_num = 1
        for line_no, _name in headers:
            numbered = re.match(r"^###\s+(\d+)", lines[line_no])
            if numbered:
                next_num = max(next_num, int(numbered.group(1)) + 1)
        while lines and lines[-1] == "":
            lines.pop()
        lines.extend(["", f"### {next_num}. {section_name}", bullet, ""])
        return "\n".join(lines) + "\n"

    insert_at = target_start + 1
    last_item = target_start
    for cursor in range(target_start + 1, target_end):
        if _ITEM_RE.match(lines[cursor]):
            last_item = cursor
    if last_item > target_start:
        cursor = last_item + 1
        while (
            cursor < target_end
            and lines[cursor].strip()
            and not lines[cursor].startswith("#")
            and not _ITEM_RE.match(lines[cursor])
        ):
            cursor += 1
        insert_at = cursor
    lines.insert(insert_at, bullet)
    result = "\n".join(lines)
    if ended_with_newline and not result.endswith("\n"):
        result += "\n"
    return result


def store_proposal(payload: dict[str, Any]) -> str:
    """
    Keep an accepted proposal until the user picks a wording.

    @param payload: App, section, code, suggestions
    @returns Proposal id
    """
    _expire_proposals()
    proposal_id = f"rp-{uuid.uuid4().hex[:8]}"
    record = dict(payload)
    record["expires_at"] = time.time() + PROPOSAL_TTL_SEC
    with _proposal_lock:
        _proposals[proposal_id] = record
    return proposal_id


def take_proposal(proposal_id: str) -> dict[str, Any] | None:
    """
    Pop a still-valid proposal (one-time use).

    @param proposal_id: rp- + 8 hex chars
    @returns Stored payload, or None
    """
    _expire_proposals()
    with _proposal_lock:
        record = _proposals.pop(proposal_id, None)
    if record is None:
        return None
    if record.get("expires_at", 0) < time.time():
        return None
    return record


def _expire_proposals() -> None:
    now = time.time()
    with _proposal_lock:
        stale = [key for key, value in _proposals.items() if value.get("expires_at", 0) < now]
        for key in stale:
            _proposals.pop(key, None)


def save_rule_to_checklist(
    app: str,
    section_name: str,
    rule_id: str,
    wording: str,
    plain: str,
    *,
    checklist_path: Path | None = None,
    summaries_path: Path | None = None,
) -> None:
    """
    Append the approved bullet and store the plain-language line.

    @param app: platform or vcapi
    @param section_name: Checklist section
    @param rule_id: Assigned code
    @param wording: Official sentence
    @param plain: Plain explanation
    """
    path = checklist_path or checklist_path_for(app)
    with _file_lock:
        markdown = path.read_text(encoding="utf-8")
        updated = append_rule_bullet(markdown, section_name, rule_id, wording)
        path.write_text(updated, encoding="utf-8")
        try:
            save_plain_language(app, rule_id, plain, summaries_path=summaries_path)
        except ValueError as extra:
            raise ReviewRuleIdeaError(str(extra)) from extra
