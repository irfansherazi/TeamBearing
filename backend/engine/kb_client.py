"""
vQA — Bedrock Knowledge Base Client
=====================================
Module: backend/engine/kb_client.py

Queries the AWS Bedrock Knowledge Base (Roles KB: JXMMTMTI06) to
retrieve role credentials, permission matrices, and context documents.

Architecture Context
--------------------
The Roles KB contains documents describing each vProMedia user role:
  - Login email addresses
  - Default password
  - Permission flags (RBAC matrix)
  - Role descriptions and constraints

This replaces the previous approach of hardcoding credentials in env
vars.  At startup, ``fetch_role_credentials()`` queries the KB and
parses the response to extract structured credential data.

The KB is hosted in ``us-east-1`` (same region as the Bedrock agent).
The ``bedrock-agent-runtime:Retrieve`` API is used for direct retrieval
(no RAG generation — just document chunks).

Query Pattern
-------------
::

    bedrock-agent-runtime.retrieve(
        knowledgeBaseId="JXMMTMTI06",
        retrievalQuery={"text": "test credentials for Account Executive role"}
    )

The response contains ``retrievalResults`` — a list of text chunks
ranked by relevance.  We concatenate and parse these chunks to extract
email addresses and passwords.

Caching
-------
KB query results are cached at two levels to prevent repeated Bedrock calls:

1. **In-memory** (``_kb_cache`` dict) — fast path within a single process.
2. **On-disk** (``/tmp/vqa_kb_cache.json``) — survives uvicorn restarts within
   the same container.  TTL defaults to 24 h; configurable via
   ``KB_DISK_CACHE_TTL_HOURS``.  Path configurable via ``KB_DISK_CACHE_PATH``.

Disable
-------
Set ``DISABLE_BEDROCK_ROLES_KB=true`` to skip all KB queries and use only
local persona files / env vars / hardcoded fallbacks.  Useful when the
credentials are already correct in those fallbacks and you want to stop the
ECS startup from hitting Bedrock on every task deployment or restart.

Fallback
--------
If the KB query fails (network error, permissions, KB not found), the
module falls back to environment variables (``ROLE_EMAIL_*``) so the
system can still boot in environments without KB access.

Dependencies
------------
  - ``boto3`` — AWS SDK for Bedrock Agent Runtime
  - ``backend/config.py`` — KB ID and AWS region settings

See Also
--------
  - ``backend/engine/roles.py``    — consumes the parsed credentials
  - ``vProMediaRegressionAgent/agent-brains/kb_utils.py`` — original impl
"""

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

from backend.config import settings

if TYPE_CHECKING:
    from backend.config.product_registry import ProductRegistry

logger = logging.getLogger(__name__)

#: Repo root — used to resolve product-scoped persona directories.
_REPO_ROOT = Path(__file__).parent.parent.parent

#: Legacy flat personas directory (kept for backward compatibility — no .md files live
#: here after Phase 3; all persona files are under product subdirectories).
_PERSONAS_DIR = _REPO_ROOT / "knowledge" / "personas"

#: Maps role_key → persona filename stem within a product's personas_dir.
#: Used by load_local_persona_credentials() to discover per-role files.
_PERSONA_FILE_MAP: dict[str, str] = {
    "account_executive": "account_executive",
    "sales_manager": "sales_manager",
    "sales_assistant": "sales_assistant",
    "production_manager": "production_manager",
    "producer": "producer",
    "gm_gsm": "gm_gsm",
    "dubber": "dubber",
    "digital_director": "digital_director",
    "traffic_manager": "traffic_manager",
    "voice_talent": "voicer",
    "writer": "writer",
}


# ---------------------------------------------------------------------------
# Disk cache configuration
# ---------------------------------------------------------------------------

#: When True, skip all Bedrock Roles KB queries and use local/env fallbacks.
#: Set DISABLE_BEDROCK_ROLES_KB=true to silence the repeated startup Bedrock
#: calls whenever the ECS task restarts or a new task instance starts.
_KB_DISABLED: bool = os.getenv("DISABLE_BEDROCK_ROLES_KB", "").lower() in ("true", "1", "yes")

#: Path for persistent disk cache — survives uvicorn restarts within the same container.
_DISK_CACHE_PATH = Path(os.getenv("KB_DISK_CACHE_PATH", "/tmp/vqa_kb_cache.json"))

#: TTL for disk cache entries in seconds (default: 24 hours).
_DISK_CACHE_TTL: float = float(os.getenv("KB_DISK_CACHE_TTL_HOURS", "24")) * 3600

#: Lock protecting disk cache writes.
_disk_cache_lock = threading.Lock()


def _load_disk_cache() -> dict[str, tuple[str, float]]:
    """Load the on-disk cache file. Returns {query: (result, timestamp)}."""
    try:
        if _DISK_CACHE_PATH.exists():
            return json.loads(_DISK_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("KB disk cache read failed: %s", exc)
    return {}


def _save_disk_cache(cache: dict[str, tuple[str, float]]) -> None:
    """Persist the cache dict to disk (best-effort, no exception propagation)."""
    try:
        _DISK_CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    except Exception as exc:
        logger.debug("KB disk cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

#: Cache for KB query results.  Maps query string → response text.
_kb_cache: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Local persona file loader
# ---------------------------------------------------------------------------


def load_local_persona_credentials(
    personas_dir: Path | None = None,
) -> dict[str, dict[str, str]]:
    """
    Parse credentials from persona Markdown files in a product-scoped directory.

    Used as a second-tier fallback when the Bedrock Roles KB is unavailable
    (no AWS credentials, CI without secrets, local dev).

    After Phase 3, persona files live under product-scoped subdirectories
    (e.g. ``knowledge/personas/vpromedia/``). Pass the absolute path to the
    product's personas directory via ``personas_dir``.

    Backward compatibility: when ``personas_dir`` is ``None``, falls back to
    the legacy flat ``knowledge/personas/`` directory. After Phase 3 this
    directory contains no ``.md`` files (they were moved to product subdirs),
    so the no-arg call returns ``{}`` for any product — callers should migrate
    to passing an explicit ``personas_dir``.

    Parameters
    ----------
    personas_dir : Path | None
        Absolute path to a product's persona directory (e.g.
        ``/repo/knowledge/personas/vpromedia``). When ``None``, uses the
        legacy flat directory ``knowledge/personas/`` (no .md files after
        Phase 3 migration).

    Returns
    -------
    dict[str, dict[str, str]]
        Mapping of role_key → {"email": ..., "password": ...}.
        Roles whose persona file is missing or unparseable are omitted.
        Returns ``{}`` when ``personas_dir`` does not exist or is empty.
    """
    target_dir = personas_dir if personas_dir is not None else _PERSONAS_DIR

    if not target_dir.is_dir():
        logger.debug("Personas dir not found: %s — skipping local fallback", target_dir)
        return {}

    credentials: dict[str, dict[str, str]] = {}

    for role_key, stem in _PERSONA_FILE_MAP.items():
        path = target_dir / f"{stem}.md"
        if not path.exists():
            logger.debug("No persona file for %s (%s) in %s", role_key, path.name, target_dir)
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read persona file %s: %s", path, exc)
            continue

        email = _parse_email_from_text(text, role_key.replace("_", " ").title()) or ""
        password = _parse_password_from_text(text) or ""

        if email:
            credentials[role_key] = {"email": email, "password": password}
            logger.debug("Local persona: %s → %s", role_key, email)

    logger.info("Local persona files loaded: %d roles from %s", len(credentials), target_dir)
    return credentials


def resolve_persona_dir(
    product_slug: str,
    registry: "ProductRegistry | None" = None,
    repo_root: Path | None = None,
) -> Path | None:
    """
    Resolve the absolute filesystem path for a product's persona directory.

    Uses the ``personas_dir`` field from the product registry entry for
    ``product_slug`` and joins it with ``repo_root`` (or ``_REPO_ROOT`` when
    not specified).

    Parameters
    ----------
    product_slug : str
        The product slug (e.g. ``"vpromedia"``, ``"vtrade"``).
    registry : ProductRegistry | None
        A pre-loaded registry. When ``None``, loads the default
        ``products.yaml`` registry lazily.
    repo_root : Path | None
        Absolute path to the repository root. Defaults to ``_REPO_ROOT``
        (the directory three levels above this module).

    Returns
    -------
    Path | None
        Absolute path to the product's personas directory, or ``None`` when
        ``product_slug`` is not registered or the product has an empty
        ``personas_dir`` field.
    """
    from backend.config.product_registry import load_product_registry

    root = repo_root if repo_root is not None else _REPO_ROOT

    if registry is None:
        try:
            registry = load_product_registry()
        except Exception as exc:
            logger.warning("Could not load product registry: %s", exc)
            return None

    try:
        product = registry.get(product_slug)
    except KeyError:
        logger.debug("resolve_persona_dir: unknown product slug '%s'", product_slug)
        return None

    if not product.personas_dir:
        logger.debug("resolve_persona_dir: product '%s' has no personas_dir configured", product_slug)
        return None

    return (root / product.personas_dir).resolve()


# ---------------------------------------------------------------------------
# Bedrock Agent Runtime client
# ---------------------------------------------------------------------------


def _get_kb_client():
    """
    Create a ``bedrock-agent-runtime`` client for KB retrieval.

    The KB is in ``us-east-1`` — this must be explicit regardless of
    the default AWS region in settings.

    Returns
    -------
    botocore.client.BedrockAgentRuntime
        A boto3 client for the ``bedrock-agent-runtime`` service.
    """
    kwargs: dict = {
        "service_name": "bedrock-agent-runtime",
        # KB is in us-east-1 — must specify explicitly
        "region_name": "us-east-1",
    }

    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

    return boto3.client(**kwargs)


# ---------------------------------------------------------------------------
# Core KB query function
# ---------------------------------------------------------------------------


def query_roles_kb(query: str) -> str:
    """
    Query the Bedrock Roles Knowledge Base and return concatenated results.

    Uses the ``bedrock-agent-runtime:Retrieve`` API to fetch relevant
    document chunks from the Roles KB (JXMMTMTI06).

    Args
    ----
    query : str
        The retrieval query string.
        Example: ``"test credentials for Account Executive role"``

    Returns
    -------
    str
        Concatenated text from all retrieval results, separated by
        ``\\n---\\n``.  Returns an empty string if the query fails.

    Notes
    -----
    Results are cached in ``_kb_cache`` (in-memory) and ``_DISK_CACHE_PATH``
    (on-disk, TTL-bounded) to avoid redundant API calls across process restarts.
    Set DISABLE_BEDROCK_ROLES_KB=true to skip all KB queries entirely.
    """
    if _KB_DISABLED:
        return ""

    # ── In-memory cache (fast path within a single process) ───────────────
    if query in _kb_cache:
        logger.debug("KB cache hit for query: '%s'", query[:60])
        return _kb_cache[query]

    # ── Persistent disk cache (survives uvicorn restarts within same container) ──
    with _disk_cache_lock:
        disk_cache = _load_disk_cache()
        entry = disk_cache.get(query)
        if entry is not None:
            result_text, saved_at = entry
            age = time.time() - saved_at
            if age < _DISK_CACHE_TTL:
                logger.debug(
                    "KB disk cache hit (age=%.0fs): '%s'",
                    age,
                    query[:60],
                )
                _kb_cache[query] = result_text
                return result_text

    kb_id = settings.bedrock_roles_kb_id
    if not kb_id:
        logger.warning("BEDROCK_ROLES_KB_ID not set — cannot query KB")
        return ""

    try:
        client = _get_kb_client()

        response = client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": query},
        )

        results = response.get("retrievalResults", [])
        text_chunks = [r.get("content", {}).get("text", "") for r in results if r.get("content", {}).get("text", "")]

        combined = "\n---\n".join(text_chunks)

        # ── Cache in memory and on disk ───────────────────────────────────
        _kb_cache[query] = combined
        with _disk_cache_lock:
            disk_cache = _load_disk_cache()
            disk_cache[query] = (combined, time.time())
            _save_disk_cache(disk_cache)

        logger.info(
            "KB query returned %d chunks (%d chars) for: '%s'",
            len(text_chunks),
            len(combined),
            query[:60],
        )

        return combined

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "unknown")
        logger.error(
            "KB query failed: code=%s, query='%s', error=%s",
            error_code,
            query[:60],
            str(e),
        )
        return ""

    except Exception as e:
        logger.error(
            "KB query failed unexpectedly: query='%s', error=%s",
            query[:60],
            str(e),
        )
        return ""


# ---------------------------------------------------------------------------
# Credential parsing
# ---------------------------------------------------------------------------


def _parse_email_from_text(text: str, role_name: str) -> str | None:
    """
    Extract the login email for a specific role from KB text.

    Prioritises the vCreative ``imail-test+*@vcreativeinc.com`` pattern
    over generic email addresses to avoid false positives from surrounding
    KB document text (e.g. author emails, example addresses).

    Search strategy:
    1. imail-test pattern near role name mention (highest confidence)
    2. Any imail-test pattern associated with role via keyword matching
    3. Any @vcreativeinc.com address near the role name
    4. Generic email near the role name as a last resort

    Args
    ----
    text : str
        Raw text from the KB response.
    role_name : str
        The role name to search for (e.g. "Account Executive").

    Returns
    -------
    str | None
        The extracted email address, or None if not found.
    """
    if not text:
        return None

    # ── Strategy 0: KB native format ─────────────────────────────────
    # The KB stores credentials in Markdown format:
    #   # <Role Name>\n# Login Email: email@domain.com
    # Search for the role section header then the Login Email line below it.
    login_email_pattern = re.compile(r"#\s*Login\s*Email\s*:\s*([\w.+-]+@[\w.-]+\.[a-z]{2,})", re.IGNORECASE)

    role_lower = role_name.lower()
    text_lower = text.lower()

    # Find the role name as a heading, then extract Login Email below it
    pos = 0
    while True:
        idx = text_lower.find(role_lower, pos)
        if idx == -1:
            break
        # Look for Login Email in a window just after the role name
        window_end = min(len(text), idx + len(role_name) + 400)
        window = text[idx:window_end]
        match = login_email_pattern.search(window)
        if match:
            email = match.group(1)
            logger.debug("Email found via KB native format near '%s': %s", role_name, email)
            return email
        pos = idx + 1

    # Also try a global scan: find ALL Login Email lines and pick the one
    # whose surrounding context mentions the role name
    all_login_emails = list(login_email_pattern.finditer(text))
    for m in all_login_emails:
        # Context window: 200 chars before this email line
        start = max(0, m.start() - 200)
        context = text_lower[start : m.start()]
        if role_lower in context:
            email = m.group(1)
            logger.debug("Email found via global Login Email scan for '%s': %s", role_name, email)
            return email

    # ── Pattern definitions (fallback strategies) ───────────────────
    # Highest priority: vCreative test email format
    imail_pattern = re.compile(r"imail-test\+[\w]+@vcreativeinc\.com", re.IGNORECASE)
    # Medium priority: any vcreativeinc.com address
    vcreative_pattern = re.compile(r"[\w.+-]+@vcreativeinc\.com", re.IGNORECASE)

    # ── Strategy 1: imail-test near role name ─────────────────────────
    pos = 0
    while True:
        idx = text_lower.find(role_lower, pos)
        if idx == -1:
            break
        window_start = max(0, idx - 150)
        window_end = min(len(text), idx + len(role_name) + 300)
        window = text[window_start:window_end]

        imail_matches = imail_pattern.findall(window)
        if imail_matches:
            logger.debug("Email found via imail-near-role for '%s': %s", role_name, imail_matches[0])
            return imail_matches[0]

        pos = idx + 1

    # ── Strategy 2: imail-test keyword matching ───────────────────────
    # Build keywords from the role name to match against the Demo* suffix
    # e.g. "Account Executive" → ["accountexecutive", "ae", "account"]
    role_keywords = role_name.lower().replace("/", " ").split()
    role_abbrev = "".join(w[0] for w in role_keywords)  # e.g. "ae", "sm", "pm"
    role_full = "".join(role_keywords)  # e.g. "accountexecutive"

    all_imail = imail_pattern.findall(text)
    for email in all_imail:
        # Extract the Demo* portion: imail-test+DemoAE@... → "demoae"
        demo_part = email.split("+")[1].split("@")[0].lower()  # e.g. "demoae"
        stripped = demo_part.replace("demo", "")  # e.g. "ae"

        if (
            (role_abbrev and stripped == role_abbrev)
            or any(kw in stripped for kw in role_keywords if len(kw) > 2)
            or stripped in role_full
        ):
            logger.debug("Email matched via keyword for '%s': %s", role_name, email)
            return email

    # ── Strategy 3: any vcreativeinc near role name ───────────────────
    pos = 0
    while True:
        idx = text_lower.find(role_lower, pos)
        if idx == -1:
            break
        window_start = max(0, idx - 150)
        window_end = min(len(text), idx + len(role_name) + 300)
        window = text[window_start:window_end]

        vc_matches = vcreative_pattern.findall(window)
        if vc_matches:
            return vc_matches[0]

        pos = idx + 1

    # ── No match found ────────────────────────────────────────────────
    return None


def _parse_password_from_text(text: str) -> str | None:
    """
    Extract the default password from KB text.

    Searches for password patterns in the KB response:
    - ``Password: xxxxx``
    - ``password: xxxxx``
    - ``Default Password: xxxxx``

    Args
    ----
    text : str
        Raw text from the KB response.

    Returns
    -------
    str | None
        The extracted password, or None if not found.
    """
    if not text:
        return None

    # Common password patterns
    patterns = [
        re.compile(r"(?:default\s+)?password\s*[:=]\s*(\S+)", re.IGNORECASE),
        re.compile(r"login_password\s*[:=]\s*(\S+)", re.IGNORECASE),
        re.compile(r"pwd\s*[:=]\s*(\S+)", re.IGNORECASE),
    ]

    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1).strip().rstrip(",").rstrip(".")

    return None


# ---------------------------------------------------------------------------
# Public API: fetch all role credentials
# ---------------------------------------------------------------------------


def fetch_all_role_credentials() -> dict[str, dict[str, str]]:
    """
    Fetch login credentials for all vProMedia roles from the Roles KB.

    Queries the KB with targeted prompts and parses the responses to
    build a credential map.

    Returns
    -------
    dict[str, dict[str, str]]
        Mapping of role_key → {"email": ..., "password": ...}.
        Missing values will have empty strings.

    Example
    -------
    >>> creds = fetch_all_role_credentials()
    >>> creds["account_executive"]["email"]
    'imail-test+DemoAE@vcreativeinc.com'
    >>> creds["account_executive"]["password"]
    'Ep!cVCteam2026$'
    """
    logger.info("Fetching role credentials from Bedrock Roles KB...")

    # KB query strings — tuned to match how the KB documents describe each role
    role_queries: dict[str, str] = {
        "account_executive": "Account Executive AE login email credentials",
        "sales_manager": "Sales Manager login email test account credentials",
        "sales_assistant": "Sales Assistant login email test account credentials",
        "production_manager": "Production Manager login email test account credentials",
        "producer": "TV Producer video Producer login email test account credentials",
        "gm_gsm": "GM GSM General Manager Group Sales Manager login email demo account",
        "dubber": "Dubber login email test account credentials",
        "digital_director": "Digital Director Digital Producer login email test account credentials",
    }

    # Display names — passed to the email parser for role-name proximity matching
    role_display_names: dict[str, str] = {
        "account_executive": "Account Executive",
        "sales_manager": "Sales Manager",
        "sales_assistant": "Sales Assistant",
        "production_manager": "Production Manager",
        "producer": "Producer",
        "gm_gsm": "GM",
        "dubber": "Dubber",
        "digital_director": "Digital Director",
    }

    credentials: dict[str, dict[str, str]] = {}

    # First, do a broad query for all credentials
    broad_text = query_roles_kb("vsuitePlatform test credentials login emails and password for all user roles")

    # Also query for specific role details
    role_texts: dict[str, str] = {}
    for role_key, query in role_queries.items():
        role_text = query_roles_kb(f"login email credentials and permissions for {query}")
        role_texts[role_key] = role_text

    # Parse the default password from the broad query
    default_password = _parse_password_from_text(broad_text) or ""

    # Parse individual role emails — use display name not query string
    for role_key in role_queries:
        display_name = role_display_names[role_key]

        # Combine broad + role-specific text for best parsing
        combined_text = f"{broad_text}\n---\n{role_texts.get(role_key, '')}"

        email = _parse_email_from_text(combined_text, display_name) or ""
        password = _parse_password_from_text(role_texts.get(role_key, "")) or default_password

        credentials[role_key] = {
            "email": email,
            "password": password,
        }

        if email:
            logger.info(
                "  [KB] %s: email=%s",
                role_key,
                email[:25] + ("..." if len(email) > 25 else ""),
            )
        else:
            logger.warning(
                "  [KB] %s: no email found in KB response",
                role_key,
            )

    logger.info("KB credential fetch complete: %d roles processed", len(credentials))

    return credentials


def fetch_role_permissions_text(role_name: str) -> str:
    """
    Fetch the full permission matrix document for a role from the KB.

    Used by ``setup_role_node`` to supplement the static permission
    flags with the full RAG-retrieved permission document.

    Args
    ----
    role_name : str
        Display name of the role (e.g. "Account Executive").

    Returns
    -------
    str
        Raw text from the KB describing the role's permissions.

    Example
    -------
    >>> text = fetch_role_permissions_text("Account Executive")
    >>> "Quick Order" in text
    True
    """
    return query_roles_kb(
        f"Retrieve complete permissions and RBAC details for the {role_name} role in vProMedia vSuite platform"
    )
