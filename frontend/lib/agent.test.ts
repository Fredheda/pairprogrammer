import { HttpAgent } from "@ag-ui/client";
import { describe, expect, it } from "vitest";
import { AGENT_ID, createAgents } from "./agent";

describe("createAgents", () => {
  it("registers the backend agent under the shared id", () => {
    const agents = createAgents("http://localhost:8123");

    expect(Object.keys(agents)).toEqual([AGENT_ID]);
    expect(agents[AGENT_ID]).toBeInstanceOf(HttpAgent);
    expect(agents[AGENT_ID].url).toBe("http://localhost:8123/agent");
  });

  it("tolerates a trailing slash on the backend URL", () => {
    expect(createAgents("http://localhost:8123/")[AGENT_ID].url).toBe(
      "http://localhost:8123/agent",
    );
  });
});
