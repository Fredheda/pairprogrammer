import httpx
import pytest

from pairprogrammer.remote import (
    ReadOnlyHttp,
    ReadOnlyViolation,
    RemoteError,
    RemoteRef,
    read_only_client,
)


def make(handler: httpx.MockTransport) -> ReadOnlyHttp:
    return ReadOnlyHttp(read_only_client("https://api.example.test", {}, transport=handler))


def test_only_get_requests_leave_the_client() -> None:
    client = read_only_client(
        "https://api.example.test", {}, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(ReadOnlyViolation):
            client.request(method, "/x")
    assert client.get("/x").status_code == 200


def test_read_only_http_exposes_no_write_methods() -> None:
    public = {name for name in dir(ReadOnlyHttp) if not name.startswith("_")}
    assert public == {"get"}


@pytest.mark.parametrize(
    ("status", "headers", "kind"),
    [
        (401, {}, "unauthorized"),
        (403, {}, "forbidden"),
        (404, {}, "not_found"),
        (429, {"Retry-After": "30"}, "rate_limited"),
        (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}, "rate_limited"),
        (500, {}, "http_error"),
    ],
)
def test_http_errors_become_structured_errors(
    status: int, headers: dict[str, str], kind: str
) -> None:
    http = make(httpx.MockTransport(lambda r: httpx.Response(status, headers=headers)))

    result = http.get("/x", ref=RemoteRef("jira", "PAIR-1"))

    assert isinstance(result, RemoteError)
    assert result.kind == kind
    assert result.status == status
    assert "jira:PAIR-1" in result.message
    if status == 429:
        assert result.retry_after == 30


def test_network_failure_becomes_structured_error() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    result = make(httpx.MockTransport(fail)).get("/x", ref=RemoteRef("github", "o/r#1"))

    assert isinstance(result, RemoteError)
    assert result.kind == "unreachable"


def test_ref_cites() -> None:
    assert RemoteRef("jira", "PAIR-7", comment="10479").cite() == "jira:PAIR-7 (comment 10479)"
    assert RemoteRef("github", "Fredheda/pairprogrammer#2").cite() == (
        "github:Fredheda/pairprogrammer#2"
    )
