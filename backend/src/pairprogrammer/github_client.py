"""Read-only GitHub access to the owner's repos over the REST API."""

import os
import re
from collections.abc import Mapping
from typing import Any

import httpx

from pairprogrammer.remote import (
    ReadOnlyHttp,
    RemoteError,
    RemoteRef,
    RemoteResult,
    Result,
    read_only_client,
)

API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
DEFAULT_OWNER = "Fredheda"
_REPO = re.compile(r"^[A-Za-z0-9._-]+$")


class GitHubClient:
    def __init__(self, http: ReadOnlyHttp, owner: str = DEFAULT_OWNER) -> None:
        self._http = http
        self.owner = owner

    def list_open_prs(self, repo: str) -> Result:
        if error := self._check(repo):
            return error
        ref = self._ref(repo)
        data = self._http.get(
            f"/repos/{self.owner}/{repo}/pulls", ref=ref, params={"state": "open", "per_page": 50}
        )
        if isinstance(data, RemoteError):
            return data
        if not data:
            return RemoteResult("no open PRs", (ref,))
        lines = [
            f"#{pr['number']} {pr['title']}{' (draft)' if pr.get('draft') else ''}"
            f" by {pr['user']['login']}"
            for pr in data
        ]
        return RemoteResult("\n".join(lines), tuple(self._ref(repo, pr["number"]) for pr in data))

    def get_pr(self, repo: str, number: int) -> Result:
        pr = self._pr(repo, number)
        if isinstance(pr, RemoteError):
            return pr
        state = f"{pr['state']}, draft" if pr.get("draft") else pr["state"]
        lines = [
            f"#{number} {pr['title']}",
            f"State: {state}",
            f"Author: {pr['user']['login']}",
            f"URL: {pr['html_url']}",
        ]
        if body := (pr.get("body") or "").strip():
            lines += ["", body]
        return RemoteResult("\n".join(lines), (self._ref(repo, number),))

    def pr_files(self, repo: str, number: int) -> Result:
        if error := self._check(repo):
            return error
        ref = self._ref(repo, number)
        data = self._http.get(
            f"/repos/{self.owner}/{repo}/pulls/{number}/files", ref=ref, params={"per_page": 100}
        )
        if isinstance(data, RemoteError):
            return data
        lines = [
            f"{f['status']} {f['filename']} (+{f['additions']}/-{f['deletions']})" for f in data
        ]
        return RemoteResult("\n".join(lines) or "no files changed", (ref,))

    def pr_checks(self, repo: str, number: int) -> Result:
        pr = self._pr(repo, number)
        if isinstance(pr, RemoteError):
            return pr
        ref = self._ref(repo, number)
        data = self._http.get(
            f"/repos/{self.owner}/{repo}/commits/{pr['head']['sha']}/check-runs",
            ref=ref,
            params={"per_page": 100},
        )
        if isinstance(data, RemoteError):
            return data
        lines = [
            f"{run['name']}: {run.get('conclusion') or run['status']}"
            for run in data.get("check_runs") or []
        ]
        return RemoteResult("\n".join(lines) or "no checks", (ref,))

    def _pr(self, repo: str, number: int) -> Any | RemoteError:
        if error := self._check(repo):
            return error
        return self._http.get(
            f"/repos/{self.owner}/{repo}/pulls/{number}", ref=self._ref(repo, number)
        )

    def _ref(self, repo: str, number: int | None = None) -> RemoteRef:
        suffix = f"#{number}" if number is not None else ""
        return RemoteRef("github", f"{self.owner}/{repo}{suffix}")

    def _check(self, repo: str) -> RemoteError | None:
        if _REPO.fullmatch(repo) and repo not in {".", ".."}:
            return None
        return RemoteError("invalid", f"not a repo name under {self.owner}: {repo!r}")


def make_github_client(
    env: Mapping[str, str] = os.environ, transport: httpx.BaseTransport | None = None
) -> GitHubClient | RemoteError:
    token = env.get("GITHUB_TOKEN")
    if not token:
        return RemoteError("not_configured", "GitHub is not configured: set GITHUB_TOKEN")
    client = read_only_client(
        API_URL,
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
        },
        transport=transport,
    )
    return GitHubClient(ReadOnlyHttp(client), env.get("GITHUB_OWNER") or DEFAULT_OWNER)
