"""Read-only Jira Cloud access over the REST API v3 (basic auth with an API token)."""

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

PROJECTS = ("PW", "CKE", "TA", "PP", "RR", "PAIR")
ISSUE_FIELDS = "summary,description,status,labels,parent,issuelinks"
_KEY = re.compile(rf"^(?:{'|'.join(PROJECTS)})-\d+$")
_ORDER_BY = re.compile(r"\s+ORDER\s+BY\s+.*$", re.IGNORECASE | re.DOTALL)


class JiraClient:
    def __init__(self, http: ReadOnlyHttp) -> None:
        self._http = http

    def get_issue(self, key: str) -> Result:
        if error := _check_key(key):
            return error
        ref = RemoteRef("jira", key)
        data = self._http.get(f"/rest/api/3/issue/{key}", ref=ref, params={"fields": ISSUE_FIELDS})
        if isinstance(data, RemoteError):
            return data
        fields = data["fields"]
        lines = [
            f"{key}: {fields.get('summary', '')}",
            f"Status: {_status(fields)}",
            f"Labels: {', '.join(fields.get('labels') or []) or 'none'}",
        ]
        if parent := fields.get("parent"):
            lines.append(f"Epic: {parent['key']} ({parent.get('fields', {}).get('summary', '')})")
        if links := [_link(link) for link in fields.get("issuelinks") or []]:
            lines += ["Links:", *links]
        if description := adf_to_text(fields.get("description")):
            lines += ["", description]
        return RemoteResult("\n".join(lines), (ref,))

    def get_comments(self, key: str) -> Result:
        if error := _check_key(key):
            return error
        ref = RemoteRef("jira", key)
        data = self._http.get(
            f"/rest/api/3/issue/{key}/comment",
            ref=ref,
            params={"maxResults": 100, "orderBy": "created"},
        )
        if isinstance(data, RemoteError):
            return data
        comments = data.get("comments") or []
        if not comments:
            return RemoteResult("no comments", (ref,))
        lines = [
            f"[comment {c['id']}] {c.get('author', {}).get('displayName', 'unknown')}, "
            f"{str(c.get('created', ''))[:10]}: {adf_to_text(c.get('body'))}"
            for c in comments
        ]
        refs = tuple(RemoteRef("jira", key, comment=str(c["id"])) for c in comments)
        return RemoteResult("\n".join(lines), refs)

    def search(self, jql: str, max_results: int = 20) -> Result:
        if not jql.strip():
            return RemoteError("invalid", "jql must not be empty")
        order = _ORDER_BY.search(jql)
        condition = jql[: order.start()] if order else jql
        scoped = f"project in ({', '.join(PROJECTS)}) AND ({condition.strip()})"
        if order:
            scoped += f" {order.group().strip()}"
        data = self._http.get(
            "/rest/api/3/search/jql",
            ref=RemoteRef("jira", "search"),
            params={"jql": scoped, "fields": "summary,status", "maxResults": max_results},
        )
        if isinstance(data, RemoteError):
            return data
        issues = data.get("issues") or []
        if not issues:
            return RemoteResult(f"no issues for {jql!r}", (RemoteRef("jira", "search"),))
        lines = [
            f"{i['key']}: {i['fields'].get('summary', '')} ({_status(i['fields'])})" for i in issues
        ]
        return RemoteResult("\n".join(lines), tuple(RemoteRef("jira", i["key"]) for i in issues))


def make_jira_client(
    env: Mapping[str, str] = os.environ, transport: httpx.BaseTransport | None = None
) -> JiraClient | RemoteError:
    names = ("JIRA_SITE", "JIRA_EMAIL", "JIRA_API_TOKEN")
    if missing := [name for name in names if not env.get(name)]:
        return RemoteError("not_configured", f"Jira is not configured: set {', '.join(missing)}")
    client = read_only_client(
        env["JIRA_SITE"].rstrip("/"),
        {"Accept": "application/json"},
        auth=(env["JIRA_EMAIL"], env["JIRA_API_TOKEN"]),
        transport=transport,
    )
    return JiraClient(ReadOnlyHttp(client))


def adf_to_text(node: Any) -> str:
    """Plain text from an Atlassian Document Format node."""
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return str(node.get("text", ""))
    if kind == "hardBreak":
        return "\n"
    children = [adf_to_text(child) for child in node.get("content") or []]
    if kind == "listItem":
        return "- " + "\n".join(c for c in children if c)
    if kind in {"doc", "bulletList", "orderedList", "blockquote", "panel", "table", "tableRow"}:
        return "\n".join(c for c in children if c)
    return "".join(children)


def _check_key(key: str) -> RemoteError | None:
    if _KEY.fullmatch(key):
        return None
    return RemoteError("invalid", f"not an issue key in {', '.join(PROJECTS)}: {key!r}")


def _status(fields: Mapping[str, Any]) -> str:
    return (fields.get("status") or {}).get("name", "unknown")


def _link(link: Mapping[str, Any]) -> str:
    if "outwardIssue" in link:
        verb, issue = link["type"]["outward"], link["outwardIssue"]
    else:
        verb, issue = link["type"]["inward"], link["inwardIssue"]
    fields = issue.get("fields", {})
    return f"- {verb} {issue['key']}: {fields.get('summary', '')} ({_status(fields)})"
