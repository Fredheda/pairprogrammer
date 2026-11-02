import { HealthStatus } from "./health-status";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4">
      <h1 className="text-3xl font-semibold">pairprogrammer</h1>
      <HealthStatus />
    </main>
  );
}
