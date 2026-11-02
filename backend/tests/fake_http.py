"""Offline HTTP fakes: an httpx transport that answers from a routing table."""

import json
from collections.abc import Callable
from typing import Any

import httpx

Route = tuple[int, Any] | Callable[[httpx.Request], httpx.Response]


class FakeApi:
    def __init__(self, routes: dict[str, Route]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if callable(route):
            return route(request)
        status, body = route
        return httpx.Response(status, content=json.dumps(body).encode())
