import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { HealthStatus } from "./health-status";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("shows the backend health status", async () => {
  const fetchMock = vi.fn().mockResolvedValue(Response.json({ status: "ok" }));
  vi.stubGlobal("fetch", fetchMock);

  render(<HealthStatus />);

  expect(await screen.findByText("Backend: ok")).toBeDefined();
  expect(fetchMock).toHaveBeenCalledWith("/backend/health");
});

test("says when the backend is unreachable", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

  render(<HealthStatus />);

  expect(await screen.findByText("Backend: unreachable")).toBeDefined();
});
