"""
backend/engine/review_rules.py
================================
Parse AI Review checklists into the Review rules page payload.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.engine.ai_review_runner import AiReviewValidationError, validate_app
from backend.engine.review_rule_summaries import plain_language_for

_VREVIEW_ROOT = Path(__file__).resolve().parents[2]
_ITEM_RE = re.compile(r"^-\s+\*\*\[([A-Z]+-\d+)\]\*\*\s*(.*)$")
_SECTION_RE = re.compile(r"^###\s+\d+\.\s+(.+)$")
_MD_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")

CHECKLIST_RELATIVE: dict[str, Path] = {
    "platform": Path("standards") / "platform" / "pr-review-checklist.md",
    "vcapi": Path("standards") / "vcapi" / "pr-review-checklist.md",
}

APP_LABELS: dict[str, str] = {
    "platform": "vsuitePlatform",
    "vcapi": "vcapi",
}


class ReviewRulesError(Exception):
    """Raised when a checklist file cannot be loaded or parsed."""


def checklist_path_for(app: str) -> Path:
    """
    Return the on-disk checklist path for a review app.

    @param app: platform or vcapi
    @returns Absolute markdown path
    """
    relative = CHECKLIST_RELATIVE.get(app)
    if relative is None:
        raise AiReviewValidationError("App must be platform or vcapi")
    return (_VREVIEW_ROOT / relative).resolve()


def strip_markdown_bold(text: str) -> str:
    """
    Remove **bold** markers from checklist wording.

    @param text: Official checklist text
    @returns Text without bold markers
    """
    return _MD_BOLD_RE.sub(r"\1", text).strip()


def first_sentence(text: str) -> str:
    """
    Take the lead sentence and drop scoring notes.

    @param text: Official checklist text
    @returns Short official lead-in
    """
    cleaned = re.sub(r"\s+", " ", strip_markdown_bold(text)).strip()
    cleaned = re.split(r"\s+If not in scope", cleaned, maxsplit=1)[0]
    cleaned = re.split(r"\s+Score \*\*once\*\*", cleaned, maxsplit=1)[0]
    cleaned = re.split(r"\s+Score once", cleaned, maxsplit=1)[0]
    match = re.match(r"(.+?[.!?])(?:\s|$)", cleaned)
    return (match.group(1) if match else cleaned).strip()


def parse_checklist_markdown(markdown: str) -> list[dict[str, str]]:
    """
    Parse ``- **[CQ-01]** text`` items grouped by ``### N. Section``.

    @param markdown: Full checklist file contents
    @returns Flat rule dicts in file order
    """
    items: list[dict[str, str]] = []
    section = ""
    current_id = ""
    current_section = ""
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal current_id, current_section, body_lines
        if not current_id:
            return
        official = " ".join(part for part in body_lines if part).strip()
        items.append(
            {
                "id": current_id,
                "section": current_section,
                "rule": official,
            }
        )
        current_id = ""
        current_section = ""
        body_lines = []

    for raw_line in markdown.splitlines():
        section_match = _SECTION_RE.match(raw_line)
        if section_match:
            flush()
            section = section_match.group(1).strip()
            continue
        item_match = _ITEM_RE.match(raw_line)
        if item_match:
            flush()
            current_id = item_match.group(1)
            current_section = section
            body_lines = [item_match.group(2).strip()]
            continue
        if current_id:
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                flush()
                continue
            body_lines.append(stripped)

    flush()
    if not items:
        raise ReviewRulesError(
            "No checklist items with IDs found. Expected format: - **[CQ-01]** description"
        )
    return items


def group_rules(
    app: str,
    items: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """
    Attach plain-language text and group items by section.

    @param app: platform or vcapi
    @param items: Flat parsed rules
    @returns Section list for the API payload
    """
    sections: list[dict[str, Any]] = []
    by_name: dict[str, list[dict[str, str]]] = {}
    for item in items:
        section_name = item["section"] or "Other"
        official = strip_markdown_bold(item["rule"])
        rule = {
            "id": item["id"],
            "plain": plain_language_for(app, item["id"], first_sentence(official)),
            "rule": official,
        }
        if section_name not in by_name:
            by_name[section_name] = []
            sections.append({"name": section_name, "rules": by_name[section_name]})
        by_name[section_name].append(rule)
    return sections


def load_review_rules(app_value: str) -> dict[str, Any]:
    """
    Load and parse the checklist for one review app.

    @param app_value: Raw app query (platform or vcapi)
    @returns Payload with sections and rules
    """
    app = validate_app(app_value)
    path = checklist_path_for(app)
    if not path.is_file():
        raise ReviewRulesError(f"Checklist file not found: {path}")
    markdown = path.read_text(encoding="utf-8")
    items = parse_checklist_markdown(markdown)
    relative = CHECKLIST_RELATIVE[app].as_posix()
    return {
        "app": app,
        "label": APP_LABELS[app],
        "source": relative,
        "sections": group_rules(app, items),
    }
