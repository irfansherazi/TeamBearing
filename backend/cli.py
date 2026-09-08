"""
vQA — Command-Line Interface (Phase 8A)
==========================================
Module: backend/cli.py

Terminal-based interface for running vQA tests, checking status, and
validating configuration — designed for CI/CD pipelines and developers.

Usage
-----
    # Single test run
    python3 -m backend.cli run QA-280 --role account_executive

    # Run a named suite
    python3 -m backend.cli suite run "Smoke Suite"

    # Check run status
    python3 -m backend.cli status run-abc12345

    # Health check
    python3 -m backend.cli health

    # Validate environment
    python3 -m backend.cli validate

    # List suites
    python3 -m backend.cli suite list

Requirements
------------
    pip install click httpx
"""

from __future__ import annotations

import sys
import time

try:
    import click
except ImportError:
    print("ERROR: 'click' package required. Run: pip install click")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("ERROR: 'httpx' package required. Run: pip install httpx")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "http://localhost:8000"

# ANSI color codes
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _api(method: str, path: str, base_url: str = DEFAULT_BASE_URL, **kwargs) -> httpx.Response:
    """Make an API call with error handling."""
    url = f"{base_url}{path}"
    try:
        with httpx.Client(timeout=30) as client:
            return getattr(client, method)(url, **kwargs)
    except httpx.ConnectError:
        click.echo(f"{RED}✗ Cannot connect to vQA at {base_url}{RESET}")
        click.echo(f"  Start the server: {CYAN}./start.sh{RESET}")
        sys.exit(1)
    except Exception as e:
        click.echo(f"{RED}✗ API error: {e}{RESET}")
        sys.exit(1)


def _format_duration(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    if ms < 60000:
        return f"{ms / 1000:.1f}s"
    return f"{ms // 60000}m {(ms % 60000) // 1000}s"


def _format_status(status: str) -> str:
    colors = {"passed": GREEN, "completed": GREEN, "running": CYAN, "failed": RED, "error": RED}
    color = colors.get(status, YELLOW)
    return f"{color}{status.upper()}{RESET}"


# ---------------------------------------------------------------------------
# CLI Group
# ---------------------------------------------------------------------------


@click.group()
@click.option("--url", default=DEFAULT_BASE_URL, envvar="VQA_URL", help="vQA API base URL")
@click.pass_context
def cli(ctx, url):
    """🔬 vQA — Autonomous QA Agent CLI"""
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = url


# ---------------------------------------------------------------------------
# run — execute a single ticket
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("ticket_id")
@click.option("--role", "-r", default="account_executive", help="User role to test as")
@click.option("--target", "-t", default="", help="Target URL override")
@click.option("--headless", is_flag=True, help="Run in headless mode")
@click.option("--wait", "-w", is_flag=True, help="Wait for completion and show results")
@click.option("--poll-interval", default=5, help="Status poll interval in seconds (with --wait)")
@click.pass_context
def run(ctx, ticket_id, role, target, headless, wait, poll_interval):
    """Execute a test run for a Jira ticket.

    Example: vqa run QA-280 --role account_executive --wait
    """
    base = ctx.obj["base_url"]
    click.echo(f"\n{BOLD}🔬 vQA — Starting Test Run{RESET}")
    click.echo(f"  Ticket:  {CYAN}{ticket_id}{RESET}")
    click.echo(f"  Role:    {role}")
    if target:
        click.echo(f"  Target:  {target}")
    click.echo()

    body = {
        "jira_ticket_id": ticket_id,
        "role": role,
    }
    if target:
        body["target_url"] = target
    if headless:
        body["mode"] = "headless"

    resp = _api("post", "/execute", base, json=body)
    if resp.status_code != 200:
        click.echo(f"{RED}✗ Execute failed: {resp.text}{RESET}")
        sys.exit(1)

    data = resp.json()
    run_id = data.get("run_id", "")
    click.echo(f"  {GREEN}✓{RESET} Run started: {BOLD}{run_id}{RESET}")
    click.echo(f"  Stream:  {data.get('stream_url', '')}")
    click.echo()

    if not wait:
        click.echo(f"  Check status: {CYAN}vqa status {run_id}{RESET}")
        return

    # Poll until completion
    click.echo(f"  {DIM}Polling every {poll_interval}s...{RESET}")
    while True:
        time.sleep(poll_interval)
        status_resp = _api("get", f"/status/{run_id}", base)
        if status_resp.status_code != 200:
            click.echo(f"{RED}✗ Status check failed{RESET}")
            sys.exit(1)

        status_data = status_resp.json()
        status = status_data.get("status", "")
        click.echo(f"  → {_format_status(status)}", nl=False)

        if status in ("completed", "failed", "error", "cancelled"):
            click.echo()
            _print_run_result(status_data)
            sys.exit(0 if status == "completed" else 1)

        click.echo(f" {DIM}(elapsed: {_format_duration(status_data.get('elapsed_ms', 0))}){RESET}")


def _print_run_result(data: dict):
    """Print formatted run results."""
    click.echo(f"\n{BOLD}{'═' * 50}{RESET}")
    click.echo(f"{BOLD}  Run Results{RESET}")
    click.echo(f"{'═' * 50}")

    status = data.get("status", "unknown")
    click.echo(f"  Status:     {_format_status(status)}")

    report_url = data.get("report_url", "")
    video_url = data.get("video_url", "")
    if report_url:
        click.echo(f"  Report:     {CYAN}{report_url}{RESET}")
    if video_url:
        click.echo(f"  Recording:  {CYAN}{video_url}{RESET}")

    click.echo(f"{'═' * 50}\n")


# ---------------------------------------------------------------------------
# status — check run status
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("run_id")
@click.pass_context
def status(ctx, run_id):
    """Check the status of a test run.

    Example: vqa status run-abc12345
    """
    base = ctx.obj["base_url"]
    resp = _api("get", f"/status/{run_id}", base)
    if resp.status_code == 404:
        click.echo(f"{RED}✗ Run '{run_id}' not found{RESET}")
        sys.exit(1)

    data = resp.json()
    click.echo(f"\n{BOLD}Run Status: {run_id}{RESET}")
    click.echo(f"  Status:  {_format_status(data.get('status', 'unknown'))}")

    report_url = data.get("report_url", "")
    if report_url:
        click.echo(f"  Report:  {CYAN}{report_url}{RESET}")
    click.echo()


# ---------------------------------------------------------------------------
# health — check system health
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--ready", is_flag=True, help="Use readiness probe (checks external services)")
@click.pass_context
def health(ctx, ready):
    """Check vQA system health.

    Use --ready to include Jira/S3/Bedrock connectivity checks.
    """
    base = ctx.obj["base_url"]
    endpoint = "/health/ready" if ready else "/health"
    resp = _api("get", endpoint, base)
    data = resp.json()

    status = data.get("status", "unknown")
    click.echo(f"\n{BOLD}🔬 vQA Health Check{RESET}")
    click.echo(f"  Status:   {_format_status(status)}")
    click.echo(f"  Mode:     {data.get('mode', '?')}")
    click.echo(f"  Version:  {data.get('version', '?')}")
    click.echo(f"  Uptime:   {_format_duration(int(data.get('uptime_seconds', 0) * 1000))}")
    click.echo(f"  Active:   {data.get('active_runs', 0)} runs")
    click.echo(f"  Total:    {data.get('total_runs_completed', 0)} completed")

    checks = data.get("checks", {})
    if checks:
        click.echo(f"\n  {BOLD}Service Checks:{RESET}")
        for svc, svc_status in checks.items():
            icon = "✓" if svc_status in ("connected", "configured", "not_checked") else "✗"
            color = (
                GREEN if svc_status in ("connected", "configured") else (YELLOW if svc_status == "not_checked" else RED)
            )
            click.echo(f"    {color}{icon}{RESET} {svc}: {svc_status}")
    click.echo()


# ---------------------------------------------------------------------------
# validate — check environment configuration
# ---------------------------------------------------------------------------


@cli.command()
@click.pass_context
def validate(ctx):
    """Validate environment configuration.

    Checks Jira, S3, Bedrock, and role credentials.
    """
    base = ctx.obj["base_url"]

    click.echo(f"\n{BOLD}🔍 vQA Environment Validation{RESET}\n")

    # Check health/ready for deep service checks
    resp = _api("get", "/health/ready", base)
    data = resp.json()
    checks = data.get("checks", {})

    results = []
    for svc, svc_status in checks.items():
        ok = svc_status in ("connected", "configured")
        results.append((svc, ok, svc_status))

    # Additional check: can we fetch tickets?
    try:
        tickets_resp = _api("get", "/tickets?limit=1", base)
        tickets_ok = tickets_resp.status_code == 200
        results.append(("Jira Board Access", tickets_ok, "ok" if tickets_ok else "failed"))
    except Exception:
        results.append(("Jira Board Access", False, "error"))

    # Print results table
    click.echo(f"  {'Check':<25} {'Status':<15} {'Details'}")
    click.echo(f"  {'─' * 25} {'─' * 15} {'─' * 20}")

    all_ok = True
    for name, ok, detail in results:
        icon = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
        click.echo(f"  {icon} {name:<23} {_format_status(detail) if not ok else f'{GREEN}{detail}{RESET}':<15}")
        if not ok:
            all_ok = False

    click.echo()
    if all_ok:
        click.echo(f"  {GREEN}{BOLD}✓ All checks passed — ready for testing{RESET}")
    else:
        click.echo(f"  {YELLOW}{BOLD}⚠ Some checks failed — review configuration{RESET}")
    click.echo()

    sys.exit(0 if all_ok else 1)


# ---------------------------------------------------------------------------
# suite — test suite management
# ---------------------------------------------------------------------------


@cli.group()
def suite():
    """Manage test suites."""
    pass


@suite.command("list")
@click.pass_context
def suite_list(ctx):
    """List all test suites."""
    base = ctx.obj["base_url"]
    resp = _api("get", "/suites", base)
    data = resp.json()

    suites = data.get("suites", [])
    if not suites:
        click.echo(f"\n  {DIM}No suites found. Create one with: vqa suite create{RESET}\n")
        return

    click.echo(f"\n{BOLD}📋 Test Suites ({len(suites)}){RESET}\n")
    click.echo(f"  {'Name':<25} {'Tickets':<10} {'Schedule':<18} {'Last Status':<15} {'Enabled'}")
    click.echo(f"  {'─' * 25} {'─' * 10} {'─' * 18} {'─' * 15} {'─' * 8}")

    for s in suites:
        name = s.get("name", "?")[:24]
        tc = str(s.get("ticket_count", 0))
        cron = s.get("schedule_cron", "") or "—"
        last = s.get("last_status", "") or "—"
        enabled = f"{GREEN}yes{RESET}" if s.get("enabled", True) else f"{RED}no{RESET}"
        click.echo(f"  {name:<25} {tc:<10} {cron:<18} {_format_status(last) if last != '—' else last:<15} {enabled}")

    click.echo()


@suite.command("create")
@click.option("--name", "-n", required=True, help="Suite name")
@click.option("--description", "-d", default="", help="Description")
@click.option("--ticket", "-t", multiple=True, required=True, help="Ticket in format TICKET_ID:ROLE")
@click.option("--cron", default="", help="Cron schedule (e.g. '0 6 * * 1-5')")
@click.pass_context
def suite_create(ctx, name, description, ticket, cron):
    """Create a new test suite.

    Example: vqa suite create -n "Smoke" -t QA-280:account_executive -t QA-281:production_manager
    """
    base = ctx.obj["base_url"]

    tickets = []
    for t in ticket:
        parts = t.split(":", 1)
        tickets.append(
            {
                "jira_ticket_id": parts[0],
                "role": parts[1] if len(parts) > 1 else "account_executive",
            }
        )

    body = {
        "name": name,
        "description": description,
        "tickets": tickets,
        "schedule_cron": cron,
    }

    resp = _api("post", "/suites", base, json=body)
    if resp.status_code == 409:
        click.echo(f"{RED}✗ Suite '{name}' already exists{RESET}")
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"{RED}✗ Failed to create suite: {resp.text}{RESET}")
        sys.exit(1)

    data = resp.json()
    click.echo(f"\n  {GREEN}✓{RESET} Suite created: {BOLD}{data.get('name', name)}{RESET}")
    click.echo(f"    ID:      {data.get('id', '?')}")
    click.echo(f"    Tickets: {data.get('ticket_count', len(tickets))}")
    if cron:
        click.echo(f"    Cron:    {cron}")
    click.echo()


@suite.command("run")
@click.argument("name_or_id")
@click.option("--wait", "-w", is_flag=True, help="Wait for completion")
@click.option("--poll-interval", default=10, help="Status poll interval in seconds")
@click.pass_context
def suite_run(ctx, name_or_id, wait, poll_interval):
    """Run a test suite by name or ID.

    Example: vqa suite run "Smoke Suite" --wait
    """
    base = ctx.obj["base_url"]

    # Try by ID first, then by name lookup
    resp = _api("get", f"/suites/{name_or_id}", base)
    if resp.status_code == 404:
        # Try listing all and matching by name
        list_resp = _api("get", "/suites", base)
        suites = list_resp.json().get("suites", [])
        match = next((s for s in suites if s["name"].lower() == name_or_id.lower()), None)
        if not match:
            click.echo(f"{RED}✗ Suite '{name_or_id}' not found{RESET}")
            sys.exit(1)
        name_or_id = match["id"]

    # Trigger run
    run_resp = _api("post", f"/suites/{name_or_id}/run", base)
    if run_resp.status_code != 200:
        click.echo(f"{RED}✗ Failed to run suite: {run_resp.text}{RESET}")
        sys.exit(1)

    data = run_resp.json()
    batch_id = data.get("batch_id", "")
    click.echo(f"\n  {GREEN}✓{RESET} Suite triggered")
    click.echo(f"    Batch:   {BOLD}{batch_id}{RESET}")
    click.echo(f"    Tickets: {data.get('ticket_count', 0)}")
    click.echo()

    if not wait:
        click.echo(f"  Check status: {CYAN}vqa status-batch {batch_id}{RESET}")
        return

    # Poll batch status
    click.echo(f"  {DIM}Polling every {poll_interval}s...{RESET}")
    while True:
        time.sleep(poll_interval)
        status_resp = _api("get", f"/batch-status/{batch_id}", base)
        if status_resp.status_code != 200:
            click.echo(f"{RED}✗ Status check failed{RESET}")
            sys.exit(1)

        status_data = status_resp.json()
        batch_status = status_data.get("status", "")
        completed = status_data.get("completed_tickets", 0)
        total = status_data.get("total_tickets", 0)
        failed = status_data.get("failed_tickets", 0)

        click.echo(f"  → {_format_status(batch_status)} {completed}/{total} completed", nl=False)
        if failed > 0:
            click.echo(f" ({RED}{failed} failed{RESET})", nl=False)
        click.echo()

        if batch_status in ("completed", "failed"):
            click.echo()
            if batch_status == "completed" and failed == 0:
                click.echo(f"  {GREEN}{BOLD}✓ All tests passed!{RESET}")
            else:
                click.echo(f"  {RED}{BOLD}✗ {failed}/{total} tests failed{RESET}")
            click.echo()
            sys.exit(0 if failed == 0 else 1)


@suite.command("delete")
@click.argument("suite_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def suite_delete(ctx, suite_id, yes):
    """Delete a test suite."""
    base = ctx.obj["base_url"]

    if not yes:
        click.confirm(f"Delete suite {suite_id}?", abort=True)

    resp = _api("delete", f"/suites/{suite_id}", base)
    if resp.status_code == 404:
        click.echo(f"{RED}✗ Suite '{suite_id}' not found{RESET}")
        sys.exit(1)
    click.echo(f"  {GREEN}✓{RESET} Suite deleted: {suite_id}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
