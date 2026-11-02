"use client";

import { CopilotKitProvider } from "@copilotkit/react-core/v2";
import type { ReactNode } from "react";
import { AGENT_ID } from "@/lib/agent";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <CopilotKitProvider runtimeUrl="/api/copilotkit" agentId={AGENT_ID}>
      {children}
    </CopilotKitProvider>
  );
}
