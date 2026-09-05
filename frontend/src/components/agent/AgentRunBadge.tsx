import type { FreshAgentRun } from "@/lib/api";

export function AgentRunBadge({ run }: { readonly run: FreshAgentRun }) {
  const label = run.status.replaceAll("_", " ");
  return <span className={`state-label state-label--${run.status === "completed" ? "legitimate" : "uncertain"}`} aria-label={`Fresh agent run ${label}`}>{label}</span>;
}
