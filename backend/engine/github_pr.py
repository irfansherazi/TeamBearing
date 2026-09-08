"""
vQA — GitHub PR Helper
=======================
Module: backend/engine/github_pr.py

Generalized GitHub REST API helper that commits one-or-more files to a fresh
branch and opens a pull request. Used by both the record-demo codegen flow
and the CU save-as-test flow so their PR mechanics stay in one place.

No git binary required — commits go through the blob/tree/commit REST API.
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class CommitFile(TypedDict):
    """One file to include in the commit."""

    repo_path: str
    """Path relative to the repo root — e.g. 'playwright/tests/foo.spec.ts'."""
    content_bytes: bytes


class CommitResult(TypedDict):
    commit_hash: str
    branch: str
    pr_url: str


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50]


async def commit_files_and_open_pr(
    *,
    files: list[CommitFile],
    branch_prefix: str,
    branch_key: str,
    commit_message: str,
    pr_title: str,
    pr_body: str,
) -> CommitResult:
    """
    Commit the given files to a new branch and open a PR against the default branch.

    Parameters
    ----------
    files
        List of files (repo-relative path + raw bytes) to include in the commit.
    branch_prefix
        Namespace for the new branch — e.g. ``"codegen"`` or ``"cu-save"``.
    branch_key
        Identifier appended to the branch name (typically ticket ID or slug).
    commit_message
        Full commit message (title on first line, optional body after blank line).
    pr_title
        Title of the PR.
    pr_body
        Body markdown for the PR.

    Returns
    -------
    CommitResult with the short commit hash, branch name, and PR URL.

    Raises
    ------
    RuntimeError
        If ``GITHUB_TOKEN`` / ``GITHUB_REPO`` are not configured.
    httpx.HTTPStatusError
        If any GitHub REST call fails.
    """
    token = settings.github_token
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN is not configured — cannot commit via GitHub API. "
            "Set the GITHUB_TOKEN environment variable."
        )

    repo = settings.github_repo
    if not repo or "/" not in repo:
        raise RuntimeError(
            f"GITHUB_REPO is not a valid 'owner/repo' value: {repo!r}. "
            "Set the GITHUB_REPO environment variable."
        )

    if not files:
        raise ValueError("commit_files_and_open_pr: 'files' must be non-empty")

    api_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base_url = f"https://api.github.com/repos/{repo}"

    async with httpx.AsyncClient(timeout=30, headers=api_headers) as client:
        # 1. Default branch + HEAD SHA
        repo_resp = await client.get(base_url)
        repo_resp.raise_for_status()
        default_branch: str = repo_resp.json()["default_branch"]

        ref_resp = await client.get(f"{base_url}/git/ref/heads/{default_branch}")
        ref_resp.raise_for_status()
        base_sha: str = ref_resp.json()["object"]["sha"]

        # 2. Create a fresh branch
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        branch = f"{branch_prefix}/{_slugify(branch_key)}-{timestamp}"

        branch_resp = await client.post(
            f"{base_url}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        branch_resp.raise_for_status()

        # 3. Create blobs for each file
        tree_entries: list[dict] = []
        for f in files:
            blob_resp = await client.post(
                f"{base_url}/git/blobs",
                json={
                    "content": base64.b64encode(f["content_bytes"]).decode(),
                    "encoding": "base64",
                },
            )
            blob_resp.raise_for_status()
            tree_entries.append(
                {
                    "path": f["repo_path"],
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_resp.json()["sha"],
                }
            )

        # 4. Base tree SHA from HEAD commit
        commit_resp = await client.get(f"{base_url}/git/commits/{base_sha}")
        commit_resp.raise_for_status()
        base_tree_sha: str = commit_resp.json()["tree"]["sha"]

        # 5. New tree
        tree_resp = await client.post(
            f"{base_url}/git/trees",
            json={"base_tree": base_tree_sha, "tree": tree_entries},
        )
        tree_resp.raise_for_status()
        tree_sha: str = tree_resp.json()["sha"]

        # 6. Commit
        new_commit_resp = await client.post(
            f"{base_url}/git/commits",
            json={"message": commit_message, "tree": tree_sha, "parents": [base_sha]},
        )
        new_commit_resp.raise_for_status()
        commit_sha: str = new_commit_resp.json()["sha"]
        commit_hash = commit_sha[:7]

        # 7. Fast-forward the branch ref
        update_ref_resp = await client.patch(
            f"{base_url}/git/refs/heads/{branch}", json={"sha": commit_sha}
        )
        update_ref_resp.raise_for_status()

        # 8. Open PR
        pr_resp = await client.post(
            f"{base_url}/pulls",
            json={
                "title": pr_title,
                "body": pr_body,
                "head": branch,
                "base": default_branch,
            },
        )
        pr_resp.raise_for_status()
        pr_url: str = pr_resp.json()["html_url"]

        logger.info("[github_pr] PR opened: %s (branch=%s, commit=%s)", pr_url, branch, commit_hash)
        return {"commit_hash": commit_hash, "branch": branch, "pr_url": pr_url}


def read_file_for_commit(abs_path: Path, repo_root: Path) -> CommitFile:
    """
    Helper that turns an on-disk absolute path into a CommitFile with the
    correct repo-relative path.
    """
    return {
        "repo_path": str(abs_path.relative_to(repo_root)),
        "content_bytes": abs_path.read_bytes(),
    }
