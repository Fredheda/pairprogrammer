"use client";

import { useEffect, useState } from "react";

export function HealthStatus() {
  const [status, setStatus] = useState("checking");

  useEffect(() => {
    fetch("/backend/health")
      .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
      .then((body: { status: string }) => setStatus(body.status))
      .catch(() => setStatus("unreachable"));
  }, []);

  return <p>Backend: {status}</p>;
}
