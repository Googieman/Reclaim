import type { ModeAvailability } from "@/lib/api";

interface ModeBadgeProps {
  readonly mode: ModeAvailability;
  readonly compact?: boolean;
}

export function ModeBadge({ mode, compact = false }: ModeBadgeProps) {
  const isLive = mode.final_mode === "live";
  const isEscalation = mode.final_mode === "escalation";
  const isFreshAgent = mode.label === "fresh_agent";
  const label = isFreshAgent ? "FRESH AGENT" : isLive ? "LIVE" : isEscalation ? "UNAVAILABLE" : "REPLAY";
  const detail = isFreshAgent
    ? "simulator / no live merchant actions"
    : isLive
    ? mode.live_actions_enabled
      ? "qualified run"
      : "qualified run · live actions disabled"
    : isEscalation
      ? "escalation required"
      : "simulation / no merchant actions";

  return (
    <span
      className={`mode-badge mode-badge--${mode.final_mode}${compact ? " mode-badge--compact" : ""}`}
      title={mode.simulation_notice}
      aria-label={`${label}: ${detail}`}
    >
      <span className="mode-badge__mark" aria-hidden="true">
        {isLive ? "●" : isEscalation ? "!" : "◇"}
      </span>
      <span>{compact ? label : `${label} · ${detail}`}</span>
    </span>
  );
}
