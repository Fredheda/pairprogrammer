from typing import Any

import httpx
import pytest
from fake_http import FakeApi

from pairprogrammer.jira_client import JiraClient, adf_to_text, make_jira_client
from pairprogrammer.remote import RemoteError, RemoteRef, RemoteResult

ENV = {
    "JIRA_SITE": "https://example.atlassian.net",
    "JIRA_EMAIL": "owner@example.test",
    "JIRA_API_TOKEN": "fake-token",
}


def adf(*paragraphs: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs
        ],
    }


ISSUE = {
    "key": "PAIR-7",
    "fields": {
        "summary": "Public-repo baseline",
        "description": adf("Run gitleaks first.", "Then add scans."),
        "status": {"name": "In Progress"},
        "labels": ["Devin", "security"],
        "parent": {"key": "PAIR-2", "fields": {"summary": "v1 Brief me"}},
        "issuelinks": [
            {
                "type": {"outward": "blocks", "inward": "is blocked by"},
                "outwardIssue": {
                    "key": "PAIR-8",
                    "fields": {"summary": "Read-only sources", "status": {"name": "Backlog"}},
                },
            },
            {
                "type": {"outward": "blocks", "inward": "is blocked by"},
                "inwardIssue": {
                    "key": "PAIR-6",
                    "fields": {"summary": "Skeleton", "status": {"name": "Done"}},
                },
            },
        ],
    },
}

COMMENTS = {
    "comments": [
        {
            "id": "10479",
            "author": {"displayName": "Frederik"},
            "created": "2026-11-01T10:00:00.000+0000",
            "body": adf("Repo is public already."),
        }
    ]
}


def client(routes: dict[str, Any]) -> tuple[JiraClient, FakeApi]:
    api = FakeApi(routes)
    made = make_jira_client(ENV, transport=api.transport())
    assert isinstance(made, JiraClient)
    return made, api


def test_factory_reports_missing_config() -> None:
    result = make_jira_client({})

    assert isinstance(result, RemoteError)
    assert result.kind == "not_configured"
    assert "JIRA_API_TOKEN" in result.message


def test_factory_uses_basic_auth_against_the_site() -> None:
    jira, api = client({"/rest/api/3/issue/PAIR-7": (200, ISSUE)})

    jira.get_issue("PAIR-7")

    request = api.requests[0]
    assert request.method == "GET"
    assert request.url.host == "example.atlassian.net"
    assert request.headers["authorization"].startswith("Basic ")


def test_get_issue() -> None:
    jira, api = client({"/rest/api/3/issue/PAIR-7": (200, ISSUE)})

    result = jira.get_issue("PAIR-7")

    assert isinstance(result, RemoteResult)
    assert result.text == (
        "PAIR-7: Public-repo baseline\n"
        "Status: In Progress\n"
        "Labels: Devin, security\n"
        "Epic: PAIR-2 (v1 Brief me)\n"
        "Links:\n"
        "- blocks PAIR-8: Read-only sources (Backlog)\n"
        "- is blocked by PAIR-6: Skeleton (Done)\n"
        "\n"
        "Run gitleaks first.\n"
        "Then add scans."
    )
    assert result.refs == (RemoteRef("jira", "PAIR-7"),)
    fields = api.requests[0].url.params["fields"]
    assert set(fields.split(",")) == {
        "summary",
        "description",
        "status",
        "labels",
        "parent",
        "issuelinks",
    }


def test_get_comments_cite_each_comment() -> None:
    jira, _ = client({"/rest/api/3/issue/PAIR-7/comment": (200, COMMENTS)})

    result = jira.get_comments("PAIR-7")

    assert isinstance(result, RemoteResult)
    assert result.text == "[comment 10479] Frederik, 2026-11-01: Repo is public already."
    assert result.refs == (RemoteRef("jira", "PAIR-7", comment="10479"),)


def test_get_comments_when_there_are_none() -> None:
    jira, _ = client({"/rest/api/3/issue/PAIR-7/comment": (200, {"comments": []})})

    result = jira.get_comments("PAIR-7")

    assert isinstance(result, RemoteResult)
    assert result.text == "no comments"
    assert result.refs == (RemoteRef("jira", "PAIR-7"),)


def test_search_is_confined_to_the_owner_projects() -> None:
    body = {
        "issues": [
            {"key": "PAIR-8", "fields": {"summary": "Sources", "status": {"name": "Backlog"}}},
        ]
    }
    jira, api = client({"/rest/api/3/search/jql": (200, body)})

    result = jira.search("status = Backlog ORDER BY key")

    assert isinstance(result, RemoteResult)
    assert result.text == "PAIR-8: Sources (Backlog)"
    assert result.refs == (RemoteRef("jira", "PAIR-8"),)
    assert api.requests[0].url.params["jql"] == (
        "project in (PW, CKE, TA, PP, RR, PAIR) AND (status = Backlog) ORDER BY key"
    )


@pytest.mark.parametrize("key", ["PAIR-7/../../user", "pair-7", "OTHER-1", "PAIR-"])
def test_rejects_keys_outside_the_owner_projects(key: str) -> None:
    jira, api = client({})

    result = jira.get_issue(key)

    assert isinstance(result, RemoteError)
    assert result.kind == "invalid"
    assert api.requests == []


@pytest.mark.parametrize(("status", "kind"), [(401, "unauthorized"), (404, "not_found")])
def test_http_errors_are_returned(status: int, kind: str) -> None:
    jira, _ = client({"/rest/api/3/issue/PAIR-99": (status, {"errorMessages": ["nope"]})})

    result = jira.get_issue("PAIR-99")

    assert isinstance(result, RemoteError)
    assert result.kind == kind


def test_rate_limit_is_returned() -> None:
    def limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "12"})

    jira, _ = client({"/rest/api/3/issue/PAIR-7": limited})

    result = jira.get_issue("PAIR-7")

    assert isinstance(result, RemoteError)
    assert (result.kind, result.retry_after) == ("rate_limited", 12)


def test_adf_to_text_handles_lists_headings_and_code() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "heading", "content": [{"type": "text", "text": "Goal"}]},
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "one"}]}
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "two"}]}
                        ],
                    },
                ],
            },
            {"type": "codeBlock", "content": [{"type": "text", "text": "make test"}]},
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "a"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "b"},
                ],
            },
        ],
    }

    assert adf_to_text(doc) == "Goal\n- one\n- two\nmake test\na\nb"
    assert adf_to_text(None) == ""
