"""
vQA — Secrets Manager (AWS SSM Parameter Store)
================================================
Module: backend/secrets.py

Resolves sensitive credentials from AWS SSM Parameter Store so that
operators never need to configure Jira tokens, API keys, or passwords
manually.  This is the "no auth required" layer for vQA.

Why SSM?
--------
The team already uses AWS for Bedrock (LLM), S3 (artifacts), and the
Roles KB.  SSM Parameter Store is the AWS-native solution for storing
secrets that are:

  * Encrypted at rest (SecureString type uses KMS)
  * Access-controlled via IAM (same role that accesses Bedrock/S3)
  * Not stored in source code or .env files
  * Auditable via CloudTrail

Parameter Paths
---------------
All vQA parameters live under the ``/vQA/`` prefix::

    /vQA/jira/email           — Jira service account email
    /vQA/jira/api_token       — Jira API token (SecureString)
    /vQA/jira/domain          — Atlassian domain (e.g. vcreative.atlassian.net)
    /vQA/roles/default_password — Shared test account password (SecureString)
    /vQA/roles/sales_manager_email — Sales Manager email (KB gap)

Resolution Priority
-------------------
For each credential, the priority order is:

  1. **AWS SSM Parameter Store** (primary) — fetched at startup
  2. **Environment variable** (fallback) — for local dev / CI without SSM
  3. **Empty string** — system logs a warning; run will fail at auth step

Usage
-----
    from backend.secrets import get_secret

    jira_token = get_secret("jira_api_token")
    # → reads /vQA/jira/api_token from SSM, or JIRA_API_TOKEN from env

Bootstrapping
-------------
``load_all_secrets()`` is called once from ``config.py`` via the Pydantic
``model_post_init`` hook.  The resolved values override the empty defaults
set in ``Settings``, so the rest of the codebase continues to use
``settings.jira_api_token`` without any change.

Local Dev Setup
---------------
To store parameters in SSM::

    aws ssm put-parameter \\
        --name "/vQA/jira/email" \\
        --value "svc-vqa@vcreativeinc.com" \\
        --type "String" \\
        --overwrite

    aws ssm put-parameter \\
        --name "/vQA/jira/api_token" \\
        --value "your-jira-token" \\
        --type "SecureString" \\
        --overwrite

    aws ssm put-parameter \\
        --name "/vQA/jira/domain" \\
        --value "vcreative.atlassian.net" \\
        --type "String" \\
        --overwrite

    aws ssm put-parameter \\
        --name "/vQA/roles/default_password" \\
        --value "Ep!cVCteam2026$" \\
        --type "SecureString" \\
        --overwrite

    # Only needed because SSM has a gap for this role (not in KB):
    aws ssm put-parameter \\
        --name "/vQA/roles/sales_manager_email" \\
        --value "imail-test+DemoSalesManager@vcreativeinc.com" \\
        --type "String" \\
        --overwrite

Dependencies
------------
  - ``boto3`` — AWS SDK for SSM
  - No imports from other vQA modules (prevents circular imports with config.py)

See Also
--------
  - ``backend/config.py``         — Settings singleton that consumes these values
  - ``backend/engine/kb_client.py``— KB-based role credential fetching
"""

import logging
import os

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSM parameter path registry
# ---------------------------------------------------------------------------

#: Mapping of logical secret name → SSM parameter path.
#: All parameters live under the /vQA/ prefix.
PARAMETER_PATHS: dict[str, str] = {
    # Jira integration
    "jira_email": "/vQA/jira/email",
    "jira_api_token": "/vQA/jira/api_token",
    "jira_domain": "/vQA/jira/domain",
    # Role credentials
    "role_default_password": "/vQA/roles/default_password",
    "role_email_sales_manager": "/vQA/roles/sales_manager_email",
    # Playwright Standard Library
    "shared_test_password": "/vQA/playwright/shared_test_password",
    "admin_test_password": "/vQA/playwright/admin_test_password",
    # Nightly scheduled Playwright test suite
    "nightly_slack_webhook_url": "/vQA/slack/nightly_webhook_url",
}

#: Env var fallback names for each secret key.
#: Used when SSM is unavailable (local dev without AWS, etc.).
ENV_VAR_FALLBACKS: dict[str, str] = {
    "jira_email": "JIRA_EMAIL",
    "jira_api_token": "JIRA_API_TOKEN",
    "jira_domain": "JIRA_DOMAIN",
    "role_default_password": "ROLE_DEFAULT_PASSWORD",
    "role_email_sales_manager": "ROLE_EMAIL_SALES_MANAGER",
    "shared_test_password": "SHARED_TEST_PASSWORD",
    "admin_test_password": "ADMIN_TEST_PASSWORD",
    "nightly_slack_webhook_url": "NIGHTLY_SLACK_WEBHOOK_URL",
}


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

#: Resolved secret values, populated by ``load_all_secrets()``.
_secrets_cache: dict[str, str] = {}

#: True after ``load_all_secrets()`` has been called.
_loaded: bool = False


# ---------------------------------------------------------------------------
# SSM client
# ---------------------------------------------------------------------------


def _get_ssm_client():
    """
    Create a boto3 SSM client using available credentials.

    Returns
    -------
    botocore.client.SSM
        A boto3 client for ``ssm`` in the primary AWS region.
    """
    kwargs: dict = {
        "service_name": "ssm",
        "region_name": os.getenv("AWS_REGION", "us-east-1"),
    }

    key = os.getenv("AWS_ACCESS_KEY_ID")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    if key and secret:
        kwargs["aws_access_key_id"] = key
        kwargs["aws_secret_access_key"] = secret

    return boto3.client(**kwargs)


# ---------------------------------------------------------------------------
# Core fetch function
# ---------------------------------------------------------------------------


def _fetch_from_ssm(path: str) -> str | None:
    """
    Fetch a single SecureString or String parameter from SSM.

    Args
    ----
    path : str
        Full SSM parameter path, e.g. ``/vQA/jira/api_token``.

    Returns
    -------
    str | None
        The decrypted parameter value, or None if not found / error.
    """
    try:
        client = _get_ssm_client()
        response = client.get_parameter(
            Name=path,
            WithDecryption=True,  # Decrypt SecureString values
        )
        value = response["Parameter"]["Value"]
        logger.info("  [SSM] Loaded: %s", path)
        return value

    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ParameterNotFound":
            logger.debug("  [SSM] Not found: %s", path)
        elif code in ("AccessDeniedException", "UnauthorizedException"):
            logger.warning("  [SSM] Access denied: %s", path)
        else:
            logger.warning("  [SSM] Error fetching %s: %s", path, str(e))
        return None

    except NoCredentialsError:
        logger.debug("  [SSM] No AWS credentials — skipping SSM fetch")
        return None

    except Exception as e:
        logger.warning("  [SSM] Unexpected error for %s: %s", path, str(e))
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_all_secrets() -> dict[str, str]:
    """
    Load all vQA secrets from SSM with env var fallback.

    Called once at startup (from ``config.py``) to resolve all sensitive
    credentials.  Results are cached in ``_secrets_cache``.

    Resolution for each secret:
      1. AWS SSM Parameter Store (``/vQA/...``) — skipped if SKIP_SSM=1
      2. Environment variable (e.g. ``JIRA_API_TOKEN``)
      3. Empty string (warning logged)

    Environment Variables
    ---------------------
    SKIP_SSM : str
        Set to ``"1"`` or ``"true"`` to bypass SSM and use only env var
        fallback.  Useful for local dev when AWS credentials are
        unavailable or expired.  Example::

            SKIP_SSM=1 bash start.sh

    Returns
    -------
    dict[str, str]
        Mapping of secret key → resolved value.

    Example
    -------
    >>> secrets = load_all_secrets()
    >>> secrets["jira_email"]
    'svc-vqa@vcreativeinc.com'
    >>> secrets["jira_api_token"]
    'ATATT...'
    """
    global _loaded, _secrets_cache

    if _loaded:
        return _secrets_cache

    # ── SKIP_SSM shortcut for local dev ──────────────────────────────
    skip_ssm = os.getenv("SKIP_SSM", "").lower() in ("1", "true", "yes")
    if skip_ssm:
        logger.info("SKIP_SSM=1 — bypassing AWS SSM, using env vars only")

    logger.info("Loading vQA secrets%s...", " (env-only mode)" if skip_ssm else " from SSM Parameter Store")

    resolved: dict[str, str] = {}
    ssm_count = 0
    env_count = 0
    missing = []

    for key, ssm_path in PARAMETER_PATHS.items():
        env_var = ENV_VAR_FALLBACKS.get(key, "")

        # 1. Try SSM (unless skipped)
        if not skip_ssm:
            value = _fetch_from_ssm(ssm_path)
            if value:
                resolved[key] = value
                ssm_count += 1
                continue

        # 2. Try env var
        env_value = os.getenv(env_var, "")
        if env_value:
            resolved[key] = env_value
            env_count += 1
            logger.info("  [ENV] Loaded: %s (from %s)", key, env_var)
            continue

        # 3. Missing — log warning
        resolved[key] = ""
        missing.append(key)
        logger.warning(
            "  [MISSING] %s — not in SSM (%s) or env (%s). Run will fail at authentication.",
            key,
            ssm_path,
            env_var,
        )

    # ── Injected into os.environ ─────────────────────────────────────
    # Standardize by ensuring all resolved secrets are available via os.getenv.
    # This allows modules like backend/engine/roles.py that use os.getenv
    # directly to benefit from SSM resolution without logic changes.
    for key, val in resolved.items():
        if val:
            env_var = ENV_VAR_FALLBACKS.get(key)
            if env_var:
                os.environ[env_var] = val

    logger.info(
        "Secrets loaded: %d from SSM, %d from env vars, %d missing",
        ssm_count,
        env_count,
        len(missing),
    )

    _secrets_cache = resolved
    _loaded = True
    return _secrets_cache


def get_secret(key: str) -> str:
    """
    Return a resolved secret value by key.

    If ``load_all_secrets()`` has not been called yet, calls it first.

    Args
    ----
    key : str
        One of the keys in ``PARAMETER_PATHS``
        (e.g. ``"jira_api_token"``).

    Returns
    -------
    str
        The resolved secret value, or ``""`` if not found.

    Example
    -------
    >>> from backend.secrets import get_secret
    >>> get_secret("jira_domain")
    'vcreative.atlassian.net'
    """
    if not _loaded:
        load_all_secrets()
    return _secrets_cache.get(key, "")


def is_secret_available(key: str) -> bool:
    """
    Check whether a secret was successfully resolved.

    Args
    ----
    key : str
        One of the keys in ``PARAMETER_PATHS``.

    Returns
    -------
    bool
        True if the secret has a non-empty value.
    """
    return bool(get_secret(key))
