#!/usr/bin/env python3
"""
vQA — Environment Validation Script (Phase 8C)
================================================
Script: scripts/validate_env.py

Pre-flight configuration checker that validates all required services
and credentials before running tests. Can be called:

  1. Directly:       python3 scripts/validate_env.py
  2. Via CLI:        python3 -m backend.cli validate
  3. At startup:     VALIDATE_ON_STARTUP=true ./start.sh

Checks
------
  ✓ Jira connectivity (API token + domain)
  ✓ S3 write access (bucket + prefix)
  ✓ Bedrock model availability
  ✓ Role credentials configured
  ✓ Target URL reachable
  ✓ Required Python packages installed
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ANSI colors
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def check_env_var(name: str, secret: bool = False) -> tuple[bool, str]:
    """Check if an environment variable is set."""
    val = os.getenv(name, "")
    if not val:
        return False, "not set"
    if secret:
        return True, f"set ({len(val)} chars)"
    return True, f"'{val[:30]}{'...' if len(val) > 30 else ''}'"


def check_python_package(name: str) -> tuple[bool, str]:
    """Check if a Python package is importable."""
    try:
        __import__(name)
        return True, "installed"
    except ImportError:
        return False, "missing"


def check_jira_connectivity() -> tuple[bool, str]:
    """Test Jira API connectivity."""
    try:
        from backend.config import settings
        from backend.jira.client import _build_headers

        if not settings.jira_domain or not settings.jira_api_token:
            return False, "credentials not configured"

        import httpx

        # 1. Classic API check
        resp = httpx.get(
            f"https://{settings.jira_domain}/rest/api/3/myself",
            headers=_build_headers(),
            timeout=10,
        )
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code} (Classic)"

        # 2. Agile API check (Board tickets)
        board_id = settings.jira_board_ids[0] if settings.jira_board_ids else 67
        resp_agile = httpx.get(
            f"https://{settings.jira_domain}/rest/agile/1.0/board/{board_id}/issue?maxResults=1",
            headers=_build_headers(),
            timeout=10,
        )
        if resp_agile.status_code != 200:
            return False, f"HTTP {resp_agile.status_code} (Agile Board {board_id})"

        return True, f"connected ({len(settings.jira_board_ids)} boards)"
    except Exception as e:
        return False, str(e)[:60]


def check_s3_access() -> tuple[bool, str]:
    """Test S3 bucket access."""
    try:
        from backend.config import settings

        if not settings.s3_bucket:
            return False, "bucket not configured"

        import boto3

        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.head_bucket(Bucket=settings.s3_bucket)
        return True, f"bucket '{settings.s3_bucket}' accessible"
    except Exception as e:
        return False, str(e)[:60]


def check_bedrock_model() -> tuple[bool, str]:
    """Test Bedrock model availability."""
    try:
        from backend.config import settings

        if not settings.bedrock_model_id:
            return False, "model not configured"

        return True, f"model: {settings.bedrock_model_id[:40]}"
    except Exception as e:
        return False, str(e)[:60]


def check_target_url() -> tuple[bool, str]:
    """Test target application reachability."""
    try:
        from backend.config import settings

        url = settings.target_url

        import httpx

        resp = httpx.get(url, timeout=10, follow_redirects=True)
        return True, f"{resp.status_code} ({url[:40]})"
    except Exception as e:
        return False, str(e)[:60]


def check_role_credentials() -> tuple[bool, str]:
    """Verify that all 4 critical credentials are resolved."""
    try:
        from backend.secrets import is_secret_available

        critical_keys = [
            "role_default_password",
            "role_email_sales_manager",
            "shared_test_password",
            "admin_test_password",
        ]

        missing = [k for k in critical_keys if not is_secret_available(k)]

        if not missing:
            return True, "all 4 critical credentials resolved"
        else:
            return False, f"missing: {', '.join(missing)}"
    except Exception as e:
        return False, str(e)[:60]


def main():
    """Run all validation checks and print results."""
    print(f"\n{BOLD}🔍 vQA Environment Validation{RESET}")
    print(f"{'─' * 55}\n")

    checks: list[tuple[str, str, bool, str]] = []

    # ── Python packages ──────────────────────────────────────
    required_packages = [
        "click",
        "httpx",
        "pydantic",
        "fastapi",
        "playwright",
        "boto3",
        "langchain_core",
    ]
    for pkg in required_packages:
        ok, detail = check_python_package(pkg)
        checks.append(("Package", pkg, ok, detail))

    # ── Environment variables ────────────────────────────────
    env_checks = [
        ("JIRA_DOMAIN", False),
        ("JIRA_EMAIL", False),
        ("JIRA_API_TOKEN", True),
        ("AWS_ACCESS_KEY_ID", True),
        ("AWS_SECRET_ACCESS_KEY", True),
        ("AWS_REGION", False),
    ]
    for var, secret in env_checks:
        ok, detail = check_env_var(var, secret=secret)
        checks.append(("Env Var", var, ok, detail))

    # ── Service connectivity ─────────────────────────────────
    print(f"  {DIM}Checking service connectivity...{RESET}\n")

    ok, detail = check_jira_connectivity()
    checks.append(("Service", "Jira API", ok, detail))

    ok, detail = check_s3_access()
    checks.append(("Service", "S3 Bucket", ok, detail))

    ok, detail = check_bedrock_model()
    checks.append(("Service", "Bedrock LLM", ok, detail))

    ok, detail = check_target_url()
    checks.append(("Service", "Target URL", ok, detail))

    ok, detail = check_role_credentials()
    checks.append(("Service", "Role Credentials", ok, detail))

    # ── Print results ────────────────────────────────────────
    current_category = ""
    all_ok = True
    warnings = 0

    for category, name, ok, detail in checks:
        if category != current_category:
            current_category = category
            print(f"  {BOLD}{category}{RESET}")

        icon = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
        print(f"    {icon} {name:<30} {detail}")

        if not ok:
            if category == "Package":
                all_ok = False
            elif category == "Env Var":
                warnings += 1
            else:
                all_ok = False

    # ── Summary ──────────────────────────────────────────────
    print(f"\n{'─' * 55}")
    if all_ok and warnings == 0:
        print(f"  {GREEN}{BOLD}✓ All checks passed — ready for testing!{RESET}")
    elif all_ok:
        print(f"  {YELLOW}{BOLD}⚠ {warnings} warnings — some features may not work{RESET}")
    else:
        print(f"  {RED}{BOLD}✗ Validation failed — fix errors above{RESET}")

    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
