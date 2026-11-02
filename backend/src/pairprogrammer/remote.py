"""Shared read-only HTTP plumbing for the Jira and GitHub sources."""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import httpx

TIMEOUT = httpx.Timeout(15.0)


class ReadOnlyViolation(RuntimeError):
    """Raised before any non-GET request leaves the process."""


@dataclass(frozen=True)
class RemoteRef:
    system: Literal["jira", "github"]
    id: str
    comment: str | None = None

    def cite(self) -> str:
        ref = f"{self.system}:{self.id}"
        return f"{ref} (comment {self.comment})" if self.comment else ref


@dataclass(frozen=True)
class RemoteResult:
    text: str
    refs: tuple[RemoteRef, ...]


@dataclass(frozen=True)
class RemoteError:
    kind: Literal[
        "not_configured",
        "invalid",
        "unauthorized",
        "forbidden",
        "not_found",
        "rate_limited",
        "unreachable",
        "http_error",
    ]
    message: str
    status: int | None = None
    retry_after: int | None = None


Result = RemoteResult | RemoteError


def _reject_writes(request: httpx.Request) -> None:
    if request.method != "GET":
        raise ReadOnlyViolation(f"{request.method} {request.url.path} is not allowed")


def read_only_client(
    base_url: str,
    headers: Mapping[str, str],
    auth: httpx.Auth | tuple[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        headers=dict(headers),
        auth=auth,
        transport=transport,
        timeout=TIMEOUT,
        event_hooks={"request": [_reject_writes]},
    )


class ReadOnlyHttp:
    """GET-only access that turns every failure into a `RemoteError`."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def get(
        self, path: str, *, ref: RemoteRef, params: Mapping[str, str | int] | None = None
    ) -> Any | RemoteError:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as error:
            return RemoteError("unreachable", f"{ref.cite()}: {type(error).__name__}")
        if response.is_success:
            return response.json()
        return _error(response, ref)


def _error(response: httpx.Response, ref: RemoteRef) -> RemoteError:
    status = response.status_code
    where = f"{ref.cite()}: HTTP {status}"
    headers = response.headers
    if status == 429 or (status == 403 and headers.get("x-ratelimit-remaining") == "0"):
        return RemoteError("rate_limited", f"{where} rate limited", status, _retry_after(headers))
    kinds: dict[int, Literal["unauthorized", "forbidden", "not_found"]] = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
    }
    return RemoteError(kinds.get(status, "http_error"), where, status)


def _retry_after(headers: httpx.Headers) -> int | None:
    if (value := headers.get("retry-after")) and value.isdigit():
        return int(value)
    if (reset := headers.get("x-ratelimit-reset")) and reset.isdigit():
        return max(int(reset) - int(time.time()), 0)
    return None
