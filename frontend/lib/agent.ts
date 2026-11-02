import { HttpAgent } from "@ag-ui/client";

// Must match AGENT_ID in backend/src/pairprogrammer/agent.py.
export const AGENT_ID = "pairprogrammer";

export function createAgents(backendUrl: string): Record<string, HttpAgent> {
  return { [AGENT_ID]: new HttpAgent({ url: `${backendUrl.replace(/\/+$/, "")}/agent` }) };
}
