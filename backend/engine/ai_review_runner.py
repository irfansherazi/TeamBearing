"""
backend/engine/ai_review_runner.py
===================================
Thin wrapper around vReview ``npm run ai:review``.

The review engine and checklists live in this app. Target git repos
(vsuitePlatform, vcapi) are siblings under vcreative-apps.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_VREVIEW_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_RELATIVE = Path("scripts") / "ai-review.js"
_ALLOWED_APPS = frozenset({"platform", "vcapi"})

_SAFE_GIT_REF = re.compile(r"^[A-Za-z0-9._/\-]+$")
_SAFE_COMMITS = re.compile(r"^[A-Fa-f0-9,]+$")
_HEADER_ITEMS = frozenset({"check", "item", "id", "review", "review item"})
_TABLE_STATUSES = frozenset({"PASS", "FAIL", "N/A", "NA", "SKIP"})


class AiReviewConfigError(Exception):
    """Raised when the vReview ai:review tool cannot be used."""


class AiReviewValidationError(Exception):
    """Raised when branch / commits / base fail input validation."""


def has_ai_review_script(repo_dir: Path) -> bool:
    """
    Return True when repo_dir contains the ai:review entry script.

    @param repo_dir: Candidate vReview checkout
    @returns True if scripts/ai-review.js exists
    """
    return (repo_dir / SCRIPT_RELATIVE).is_file()


def validate_git_ref(value: str, field_name: str) -> str:
    """
    Strip and accept a git branch/ref that is safe to pass as an argv flag.

    @param value: Raw form field
    @param field_name: Field label for error text
    @returns Stripped ref
    """
    stripped = value.strip()
    if not stripped:
        raise AiReviewValidationError(f"{field_name} is required")
    if not _SAFE_GIT_REF.match(stripped):
        raise AiReviewValidationError(
            f"{field_name} contains unsupported characters. Use letters, digits, / _ . -"
        )
    return stripped


def validate_commits(value: str) -> str:
    """
    Strip optional commit list. Empty is allowed.

    @param value: Comma-separated SHAs
    @returns Stripped list, or empty string
    """
    stripped = value.strip()
    if not stripped:
        return ""
    if not _SAFE_COMMITS.match(stripped):
        raise AiReviewValidationError(
            "Commits must be comma-separated hex SHAs (no spaces or shell characters)"
        )
    return stripped


def validate_app(value: str) -> str:
    """
    Accept platform or vcapi as the review target.

    @param value: Raw app field
    @returns Normalized app id
    """
    stripped = (value or "platform").strip().lower()
    if stripped in {"vsuite", "vsuiteplatform"}:
        stripped = "platform"
    if stripped not in _ALLOWED_APPS:
        raise AiReviewValidationError("App must be platform or vcapi")
    return stripped


def build_ai_review_argv(
    branch: str, base: str, commits: str = "", app: str = "platform"
) -> list[str]:
    """
    Build subprocess argv for npm run ai:review (no shell).

    @param branch: --branch value
    @param base: --base value
    @param commits: Optional --commits value
    @param app: --app value (platform or vcapi)
    @returns Argv list
    """
    npm_bin = "npm.cmd" if os.name == "nt" else "npm"
    cmd = [
        npm_bin,
        "run",
        "ai:review",
        "--",
        f"--app={app}",
        f"--branch={branch}",
        f"--base={base}",
    ]
    if commits:
        cmd.append(f"--commits={commits}")
    return cmd


def parse_review_table_row(line: str) -> dict[str, str] | None:
    """
    Parse one markdown table row from ai:review stdout.

    @param line: A single log line
    @returns {item, status, evidence} or None
    """
    trimmed = line.strip()
    if not trimmed.startswith("|") or not trimmed.endswith("|"):
        return None
    cells = [cell.strip() for cell in trimmed[1:-1].split("|")]
    if len(cells) < 3:
        return None
    item = cells[0]
    status_raw = cells[1].upper().replace(" ", "")
    evidence = " | ".join(cells[2:]).strip()
    if item.startswith("-") or "---" in item:
        return None
    if item.lower() in _HEADER_ITEMS:
        return None
    if status_raw == "NA":
        status_raw = "N/A"
    if status_raw not in _TABLE_STATUSES:
        return None
    if not re.match(r"^[A-Za-z][A-Za-z0-9._-]*$", item):
        return None
    return {"item": item, "status": status_raw, "evidence": evidence}


def upsert_review_row(
    rows: list[dict[str, str]], next_row: dict[str, str]
) -> list[dict[str, str]]:
    """
    Merge a parsed checklist row into the list, replacing the same item id.

    @param rows: Current table rows
    @param next_row: Newly parsed row
    @returns Updated row list
    """
    index = next(
        (i for i, row in enumerate(rows) if row.get("item") == next_row.get("item")),
        -1,
    )
    if index < 0:
        return [*rows, next_row]
    updated = list(rows)
    updated[index] = next_row
    return updated


def summarize_review_rows(rows: list[dict[str, str]]) -> tuple[int, int, int]:
    """
    Count PASS / FAIL / other (SKIP, N/A) rows for a history summary.

    @param rows: Parsed checklist rows
    @returns (pass_count, fail_count, skip_count)
    """
    pass_count = 0
    fail_count = 0
    skip_count = 0
    for row in rows:
        status = row.get("status")
        match status:
            case "PASS":
                pass_count += 1
            case "FAIL":
                fail_count += 1
            case _:
                skip_count += 1
    return pass_count, fail_count, skip_count


def resolve_ai_review_cwd(configured_path: str = "") -> Path:
    """
    Resolve the vReview directory that can run npm run ai:review.

    @param configured_path: Optional explicit vReview path
    @returns Absolute cwd for the subprocess
    """
    if configured_path.strip():
        explicit = Path(configured_path.strip()).expanduser().resolve()
        if not has_ai_review_script(explicit):
            raise AiReviewConfigError(f"{explicit} does not contain {SCRIPT_RELATIVE}.")
        return explicit

    if has_ai_review_script(_VREVIEW_ROOT):
        return _VREVIEW_ROOT.resolve()

    raise AiReviewConfigError(
        f"vReview is missing {SCRIPT_RELATIVE} at {_VREVIEW_ROOT}."
    )
