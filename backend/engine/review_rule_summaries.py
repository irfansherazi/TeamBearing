"""
backend/engine/review_rule_summaries.py
=======================================
Plain-language restatements for checklist IDs.

Official wording still comes from pr-review-checklist.md.
Keys without an app prefix apply to both apps. App-specific keys
use ``platform:CQ-05`` / ``vcapi:CQ-05``.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

PLAIN_BY_ID: dict[str, str] = {
    "CQ-01": "Changed code should match how this team already names, formats, and structures files.",
    "CQ-02": "No leftover commented-out code or unused dead code.",
    "CQ-03": "Optional or missing values are read safely so the page does not crash.",
    "CQ-04": "The changed logic was read end to end, not only the surface of the diff.",
    "CQ-10": "Optional chaining (?.) is used correctly where a value might be missing.",
    "F-01": "The change does not alter other features by accident.",
    "F-02": "The change does not introduce unexpected side effects.",
    "F-03": "The feature does what it is supposed to do.",
    "F-04": "Edge cases and error paths are handled.",
    "F-05": "No obvious performance problems were introduced.",
    "F-06": "Dates, lead times, and order rules match the established product path, not a one-off shortcut.",
    "F-07": "Business rules that create or reject drafts are enforced on both sides that need to enforce them.",
    "F-08": "User-facing errors sound like the rest of the product, not a raw API dump.",
    "D-01": "The code is readable on its own, or it has a useful comment.",
    "D-02": "Readme or other docs were updated when the change needs it.",
    "D-03": "New or changed methods have a JSDoc block: what it does, params, and return.",
    "D-04": "Comments sit next to the code they describe, not somewhere unrelated.",
    "PH-01": "The PR title and description are clear.",
    "PH-02": "The related ticket or story is linked.",
    "LD-01": "New logic matches the pattern already used in the same file for the same job.",
    "LD-02": "Sorting arrays of objects always uses an explicit comparator, never a bare sort().",
    "LD-03": "Optional-property checks stay consistent in the same handler (do not mix styles).",
    "LD-04": "If items are split, transformed, then merged, none of them disappear in the middle.",
    "LD-05": "Do not take [0] from match() or find() without checking for a missing result first.",
    "LD-06": "Code that needs a looked-up object runs inside the null check, not after it.",
    "platform:CQ-05": "No leftover console.log or debugger statements.",
    "platform:CQ-06": "Linting passes (npm run lint).",
    "platform:CQ-07": "Unit tests were added or updated when the change needs them.",
    "platform:CQ-08": "When you leave the page, timers, polls, listeners, and pending requests must stop.",
    "platform:CQ-09": "User-facing text in TypeScript uses the translation service, not hardcoded English.",
    "platform:CQ-11": "New or changed API calls go through vcAPI, not the old doRequest helper.",
    "platform:CQ-12": "Defaults use ?? so a real false value is not treated as missing.",
    "platform:CQ-13": "Browser stop/abort is wrapped in try/catch, and listening flags are always cleared.",
    "platform:CQ-14": "Soft errors (mic, permission, voice) must not kick the user off the page.",
    "platform:CQ-15": "Helpers under a Private helpers section are private or protected, not public by accident.",
    "platform:CQ-16": "Holidays like Thanksgiving are computed for that year, not hardcoded as a calendar date.",
    "platform:CQ-17": "Indentation matches the real nesting after merges.",
    "platform:CQ-19": "Do not type browser SpeechRecognition (or similar) as any. Use a real type or narrow first.",
    "platform:CQ-20": "API list rows get numeric ids, and invalid rows are filtered out before the UI uses them.",
    "platform:CQ-21": "Do not pre-translate messages passed into ErrorService.logError. Pass the key and let it translate once.",
    "platform:CQ-22": "New HTML controls that show content have a unique hyphenated id.",
    "platform:CQ-23": "No async/await in Angular frontend code. Use .then() and .catch().",
    "platform:CQ-24": "Do not use hasOwnProperty. Use optional chaining or an explicit structure check.",
    "platform:CQ-25": "Do not disable ESLint in the changed code. Fix the underlying issue.",
    "platform:CQ-26": "Build strings with template literals, not plus-sign concatenation.",
    "platform:CQ-27": "Class members are public or private based on real usage, not left public by default.",
    "platform:CQ-28": "Observable properties (Subject, BehaviorSubject, and similar) end with a $ suffix.",
    "platform:CQ-29": "} else { stays on the same line as the closing brace.",
    "platform:CQ-30": "Long if/else chains should be a switch or a lookup map when that fits.",
    "platform:CQ-31": "Callbacks use arrow functions, not anonymous function expressions.",
    "platform:CQ-32": "Reuse existing helpers instead of copying the same logic.",
    "platform:CQ-33": "User-facing text in HTML uses | language_pipe.",
    "platform:T-01": "Existing unit tests still pass.",
    "platform:T-03": "Relevant Cypress / E2E tests were added or updated.",
    "platform:T-04": "The feature was tested across roles or users when that applies.",
    "platform:T-05": "Spec setup awaits async helpers, and tests use known CI seed emails.",
    "platform:T-06": "Tests do not pass a missing user fixture into code that reads .user.",
    "platform:T-07": "New unit tests use description / setup / expectations arrays, not one-off it() blocks.",
    "platform:T-08": "Tests cover valid, invalid, and real edge cases — not only the happy path.",
    "platform:T-09": "Test names are descriptive, and setup/expectations helpers do one job each.",
    "platform:PH-03": "Screenshots or video are attached for UI changes.",
    "platform:PH-04": "Required SQL is added to Jira Dev Notes, not in PR comments.",
    "platform:LD-07": "JSON.parse results are checked for the expected shape before the UI or business logic uses them.",
    "platform:OE-01": "Anything else risky in the diff (bugs, security, unsafe types) that no other code covers.",
    "vcapi:CQ-05": "No console.log / warn / error / debugger inside NestJS services or controllers.",
    "vcapi:CQ-06": "NestJS services log with request.emit('addLog', message), not console or NestJS Logger.",
    "vcapi:CQ-07": "Queue and background work uses fakeRequest so service methods still get a request to log with.",
    "vcapi:CQ-08": "Linting passes (npm run lint).",
    "vcapi:CQ-09": "Unit tests were added or updated when the change needs them.",
    "vcapi:CQ-11": "Defaults use ?? so a real false value is not treated as missing.",
    "vcapi:CQ-12": "Helpers under a Private helpers section are private or protected, not public by accident.",
    "vcapi:CQ-13": "Holidays like Thanksgiving are computed for that year, not hardcoded as a calendar date.",
    "vcapi:CQ-14": "Indentation matches the real nesting after merges.",
    "vcapi:CQ-15": "API list rows get numeric ids, and invalid rows are filtered out.",
    "vcapi:CQ-16": "Do not use hasOwnProperty. Use optional chaining or an explicit structure check.",
    "vcapi:CQ-17": "Do not disable ESLint in the changed code. Fix the underlying issue.",
    "vcapi:CQ-18": "Build strings with template literals, not plus-sign concatenation.",
    "vcapi:CQ-19": "Class members are public or private based on real usage, not left public by default.",
    "vcapi:CQ-20": "} else { stays on the same line as the closing brace.",
    "vcapi:CQ-21": "Long if/else chains should be a switch or a lookup map when that fits.",
    "vcapi:CQ-22": "Callbacks use arrow functions, not anonymous function expressions.",
    "vcapi:CQ-23": "Reuse existing helpers instead of copying the same logic.",
    "vcapi:CQ-24": "Never leave an empty catch. Log or handle the error.",
    "vcapi:T-01": "Relevant unit tests pass via npm test (not npx jest directly).",
    "vcapi:T-02": "The feature was tested across roles or users when that applies.",
    "vcapi:T-03": "New unit tests prefer description / setup / expectations arrays when that pattern fits.",
    "vcapi:T-04": "Tests cover valid, invalid, and real edge cases — not only the happy path.",
    "vcapi:T-05": "Test names are descriptive, and setup/expectations helpers do one job each.",
    "vcapi:T-06": "If a describe adds Jest spies, restore them in afterEach with jest.restoreAllMocks().",
    "vcapi:PH-03": "Required SQL is added to Jira Dev Notes, not in PR comments.",
    "vcapi:PH-04": "New feature branches use --no-track, and the first push uses -u to set tracking.",
}


_SUMMARIES_PATH = Path(__file__).resolve()
_PLAIN_KEY_RE = re.compile(r"^[A-Za-z0-9:_-]+$")
_DICT_CLOSE_RE = re.compile(r"^}\s*$", re.M)


def summary_key_for(app: str, rule_id: str) -> str:
    """
    Build the PLAIN_BY_ID key for a saved rule.

    @param app: platform or vcapi
    @param rule_id: Checklist id such as CQ-34
    @returns App-prefixed key
    """
    return f"{app}:{rule_id}"


def upsert_plain_entry(source: str, key: str, plain: str) -> str:
    """
    Insert or replace one PLAIN_BY_ID line in the summaries module text.

    @param source: Full review_rule_summaries.py contents
    @param key: Dict key such as platform:CQ-34
    @param plain: Plain-language sentence
    @returns Updated file text
    """
    if not _PLAIN_KEY_RE.match(key):
        raise ValueError("Invalid summary key")
    text = (plain or "").strip()
    if not text:
        raise ValueError("Plain explanation is empty")
    new_line = f"    {json.dumps(key)}: {json.dumps(text, ensure_ascii=False)},"
    existing = re.compile(rf"^    {re.escape(json.dumps(key))}: .*$", re.M)
    if existing.search(source):
        return existing.sub(new_line, source, count=1)
    marker = "PLAIN_BY_ID: dict[str, str] = {"
    start = source.find(marker)
    if start < 0:
        raise ValueError("PLAIN_BY_ID dict was not found")
    close = _DICT_CLOSE_RE.search(source[start:])
    if close is None:
        raise ValueError("PLAIN_BY_ID dict has no closing brace")
    at = start + close.start()
    prefix = source[:at]
    if not prefix.endswith("\n"):
        prefix = f"{prefix}\n"
    return f"{prefix}{new_line}\n{source[at:]}"


def save_plain_language(
    app: str,
    rule_id: str,
    plain: str,
    *,
    summaries_path: Path | None = None,
) -> None:
    """
    Persist a new rule's plain explanation in review_rule_summaries.py.

    @param app: platform or vcapi
    @param rule_id: Checklist id
    @param plain: Plain-language sentence
    @param summaries_path: Override path for tests
    @returns None
    """
    path = summaries_path or _SUMMARIES_PATH
    source = path.read_text(encoding="utf-8")
    updated = upsert_plain_entry(source, summary_key_for(app, rule_id), plain)
    path.write_text(updated, encoding="utf-8")
    if summaries_path is None:
        importlib.reload(sys.modules[__name__])


def plain_language_for(app: str, rule_id: str, official: str) -> str:
    """
    Return a short plain-language line for a checklist ID.

    @param app: platform or vcapi
    @param rule_id: Checklist id such as CQ-01
    @param official: Official checklist sentence (fallback)
    @returns Plain explanation
    """
    keyed = PLAIN_BY_ID.get(f"{app}:{rule_id}")
    if keyed:
        return keyed
    shared = PLAIN_BY_ID.get(rule_id)
    if shared:
        return shared
    return official
