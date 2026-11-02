from typing import Any

import pytest
from fake_http import FakeApi

from pairprogrammer.github_client import GitHubClient, make_github_client
from pairprogrammer.remote import RemoteError, RemoteRef, RemoteResult

REPO = "/repos/Fredheda/pairprogrammer"
PR = {
    "number": 2,
    "title": "PAIR-7: Public-repo baseline",
    "state": "open",
    "draft": False,
    "user": {"login": "devin-ai-integration[bot]"},
    "html_url": "https://github.com/Fredheda/pairprogrammer/pull/2",
    "body": "Adds security scans.",
    "head": {"sha": "abc123"},
}


def client(routes: dict[str, Any]) -> tuple[GitHubClient, FakeApi]:
    api = FakeApi(routes)
    made = make_github_client({"GITHUB_TOKEN": "fake-token"}, transport=api.transport())
    assert isinstance(made, GitHubClient)
    return made, api


def test_factory_reports_missing_token() -> None:
    result = make_github_client({})

    assert isinstance(result, RemoteError)
    assert result.kind == "not_configured"


def test_factory_sends_token_and_api_version() -> None:
    gh, api = client({f"{REPO}/pulls": (200, [])})

    gh.list_open_prs("pairprogrammer")

    request = api.requests[0]
    assert request.method == "GET"
    assert request.url.host == "api.github.com"
    assert request.headers["authorization"] == "Bearer fake-token"
    assert request.headers["x-github-api-version"] == "2022-11-28"
    assert request.url.params["state"] == "open"


def test_list_open_prs() -> None:
    draft = PR | {"number": 3, "title": "PAIR-8", "draft": True}
    gh, _ = client({f"{REPO}/pulls": (200, [PR, draft])})

    result = gh.list_open_prs("pairprogrammer")

    assert isinstance(result, RemoteResult)
    assert result.text.splitlines() == [
        "#2 PAIR-7: Public-repo baseline by devin-ai-integration[bot]",
        "#3 PAIR-8 (draft) by devin-ai-integration[bot]",
    ]
    assert result.refs == (
        RemoteRef("github", "Fredheda/pairprogrammer#2"),
        RemoteRef("github", "Fredheda/pairprogrammer#3"),
    )


def test_list_open_prs_when_there_are_none() -> None:
    gh, _ = client({f"{REPO}/pulls": (200, [])})

    result = gh.list_open_prs("pairprogrammer")

    assert isinstance(result, RemoteResult)
    assert result.text == "no open PRs"
    assert result.refs == (RemoteRef("github", "Fredheda/pairprogrammer"),)


def test_get_pr() -> None:
    gh, _ = client({f"{REPO}/pulls/2": (200, PR)})

    result = gh.get_pr("pairprogrammer", 2)

    assert isinstance(result, RemoteResult)
    assert result.text == (
        "#2 PAIR-7: Public-repo baseline\n"
        "State: open\n"
        "Author: devin-ai-integration[bot]\n"
        "URL: https://github.com/Fredheda/pairprogrammer/pull/2\n"
        "\n"
        "Adds security scans."
    )
    assert result.refs == (RemoteRef("github", "Fredheda/pairprogrammer#2"),)


def test_pr_files() -> None:
    files = [
        {
            "filename": ".github/workflows/security.yml",
            "status": "added",
            "additions": 90,
            "deletions": 0,
        },
        {"filename": "AGENTS.md", "status": "modified", "additions": 12, "deletions": 3},
    ]
    gh, _ = client({f"{REPO}/pulls/2/files": (200, files)})

    result = gh.pr_files("pairprogrammer", 2)

    assert isinstance(result, RemoteResult)
    assert result.text.splitlines() == [
        "added .github/workflows/security.yml (+90/-0)",
        "modified AGENTS.md (+12/-3)",
    ]
    assert result.refs == (RemoteRef("github", "Fredheda/pairprogrammer#2"),)


def test_pr_checks_reads_check_runs_of_the_head_commit() -> None:
    runs = {
        "total_count": 2,
        "check_runs": [
            {"name": "backend", "status": "completed", "conclusion": "success"},
            {"name": "bandit", "status": "in_progress", "conclusion": None},
        ],
    }
    gh, _ = client({f"{REPO}/pulls/2": (200, PR), f"{REPO}/commits/abc123/check-runs": (200, runs)})

    result = gh.pr_checks("pairprogrammer", 2)

    assert isinstance(result, RemoteResult)
    assert result.text.splitlines() == ["backend: success", "bandit: in_progress"]
    assert result.refs == (RemoteRef("github", "Fredheda/pairprogrammer#2"),)


@pytest.mark.parametrize("repo", ["../other", "Other/repo", "repo?x=1", ""])
def test_rejects_repo_names_outside_the_owner(repo: str) -> None:
    gh, api = client({})

    result = gh.list_open_prs(repo)

    assert isinstance(result, RemoteError)
    assert result.kind == "invalid"
    assert api.requests == []


def test_missing_pr_is_returned_not_raised() -> None:
    gh, _ = client({})

    result = gh.pr_checks("pairprogrammer", 99)

    assert isinstance(result, RemoteError)
    assert result.kind == "not_found"
    assert "github:Fredheda/pairprogrammer#99" in result.message


def test_rate_limit_is_returned() -> None:
    headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}

    def limited(request: Any) -> Any:
        import httpx

        return httpx.Response(403, headers=headers)

    gh, _ = client({f"{REPO}/pulls": limited})

    result = gh.list_open_prs("pairprogrammer")

    assert isinstance(result, RemoteError)
    assert result.kind == "rate_limited"
