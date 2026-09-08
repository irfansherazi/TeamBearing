"""
vQA — Fixture Manager (Objective 3)
=====================================
Module: backend/engine/fixture_manager.py

Provides run-scoped unique suffixes that the **executor** appends to all
``fill`` action values (titles, names, free-text) to prevent state collisions
across repeated test runs against the same database.

Design
------
Every test run already has a UUID ``run_id`` (e.g.
``"f56eb8d7-6e4b-4cf4-99e6-b9cc95c6c847"``).  We extract the last 8 hex
characters as a human-readable, compact suffix::

    run_id  = "f56eb8d7-6e4b-4cf4-99e6-b9cc95c6c847"
    suffix  = "_b9cc95c6"   (last 8 chars of the UUID, after removing dashes)

Enforcement is **hard** — the executor calls ``FixtureManager.stamp()``
inside the ``fill`` branch of ``_dispatch_action`` before passing the value
to ``locator.fill()``.  The LLM does not need to remember to type the suffix;
it is invisible to the planner.

Skipped fields
--------------
The following fill targets are never stamped because they must match exact
values in the database or authentication system:

- **Email addresses** — contains ``@``
- **Passwords / secrets** — field name/label contains "password"
- **Search / autocomplete bars** — field name/label contains "search" or
  "client" (client-name lookups must match existing DB records)
- **Date fields** — value looks like a date (``/`` or ``-`` separators with
  digit patterns)
- **Numeric values** — pure digits or decimal numbers
- **URLs** — starts with ``http``

Usage
-----
The ``FixtureManager`` is instantiated once per executor call using the
``run_id`` from ``VQAState``.  Only ``stamp()`` and ``suffix`` are needed
by external callers::

    from backend.engine.fixture_manager import FixtureManager

    fm = FixtureManager(run_id)
    stamped_value = fm.stamp(value, field_name=action.get("name", ""))
"""

import re

__all__ = ["FixtureManager"]

# ---------------------------------------------------------------------------
# Patterns that mark a fill value as un-stampable
# ---------------------------------------------------------------------------

# Date-like: "04/13/2026", "2026-04-13", "13-04-26"
_DATE_PATTERN = re.compile(r"\d{1,4}[/\-]\d{1,2}[/\-]\d{2,4}")

# Pure numeric or decimal: "42", "3.14", "$1,000"
_NUMERIC_PATTERN = re.compile(r"^[\$€£]?[\d,]+\.?\d*$")

# Field-name keywords that indicate the field must receive exact values
_SKIP_NAME_KEYWORDS: tuple[str, ...] = (
    "password",
    "search",
    "client",  # client autocomplete — must match existing record
    "email",
    "username",
    "user name",
    "login",
    "token",
    "api key",
    "api_key",
    "due date",
    "date",
    "phone",
    "zip",
    "postal",
    # Pickers / filters — the field selects an EXISTING record, so a stamped
    # value would never match. Covers ghost-panel ("Select Person..."), user
    # autocompletes, role dropdowns, and generic "assign X" selectors.
    "person",
    "select person",
    "role",
    "user",  # note: "username" already skipped above; this catches "Assign User", "User to Ghost", etc.
    "impersonate",
    "ghost",
    "assign",  # "Assign Producer", "Assign Coordinator" — always picks existing users
    "producer",
    "coordinator",
    "manager",
)

# AC step_types whose fill values are always filter/search inputs into
# existing-record pickers — never data-creation fills. When the executor
# sees any of these types on the current step, FixtureManager skips
# stamping entirely regardless of field name.
_SKIP_STEP_TYPES: frozenset[str] = frozenset({"GHOST_LOGIN", "PERSONA_SWITCH", "ACCOUNT_SWITCH"})


class FixtureManager:
    """
    Provides a run-scoped suffix and stamps fill values with it.

    Parameters
    ----------
    run_id : str
        The UUID-formatted run identifier from ``VQAState["run_id"]``.
        The suffix is the last 8 hex characters of the UUID (dashes removed).

    Attributes
    ----------
    suffix : str
        The compact unique suffix appended to stampable fill values,
        e.g. ``"_b9cc95c6"``.
    """

    def __init__(self, run_id: str) -> None:
        # Strip dashes and take the last 8 chars of the hex UUID
        hex_only = run_id.replace("-", "")
        self.suffix: str = f"_{hex_only[-8:]}" if hex_only else ""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def stamp(self, value: str, field_name: str = "", step_type: str = "") -> str:
        """
        Append the run suffix to ``value`` if the field is stampable.

        Parameters
        ----------
        value : str
            The raw fill value from the planner's JSON action.
        field_name : str
            The locator name/label of the target field (used to detect
            fields that must NOT be stamped, e.g. email, password, search).
        step_type : str
            Optional AC step_type from the current test plan step. When it
            is a picker/switch step (GHOST_LOGIN / PERSONA_SWITCH /
            ACCOUNT_SWITCH), stamping is always skipped — those step types
            fill filter inputs that must match existing records.

        Returns
        -------
        str
            ``value + self.suffix`` if stampable, otherwise ``value`` unchanged.
        """
        if not self.suffix:
            return value

        if step_type and step_type in _SKIP_STEP_TYPES:
            return value

        if self._should_skip(value, field_name):
            return value

        return f"{value}{self.suffix}"

    # ------------------------------------------------------------------ #
    # Internal skip logic                                                  #
    # ------------------------------------------------------------------ #

    def _should_skip(self, value: str, field_name: str) -> bool:
        """Return True if this fill value must NOT receive the suffix."""
        # ── Value-based checks ─────────────────────────────────────────
        v = value.strip()

        # Email address — must match exact DB record
        if "@" in v:
            return True

        # URL — never stamp URLs
        if v.startswith(("http://", "https://")):
            return True

        # Date-like string — MM/DD/YYYY, YYYY-MM-DD, etc.
        if _DATE_PATTERN.search(v):
            return True

        # Pure numeric / currency — "42", "$1,000"
        if _NUMERIC_PATTERN.match(v):
            return True

        # Short value (<= 3 chars) — likely a code or abbreviation
        if len(v) <= 3:
            return True

        # ── Field-name-based checks ────────────────────────────────────
        fn = field_name.lower()
        if any(kw in fn for kw in _SKIP_NAME_KEYWORDS):
            return True

        return False
