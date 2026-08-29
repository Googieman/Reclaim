/** Typed, public frontend configuration. Secrets never belong in this module. */

export type RunMode = "live" | "replay";

export interface FrontendConfig {
  readonly tenantId: string;
  readonly runMode: RunMode;
  readonly replayLabel: RunMode;
  readonly liveActionsEnabled: boolean;
}

const asRunMode = (value: string | undefined): RunMode =>
  value === "live" ? "live" : "replay";

const asBoolean = (value: string | undefined, fallback: boolean): boolean => {
  if (value === undefined) return fallback;
  return value.toLowerCase() === "true";
};

export const getFrontendConfig = (): FrontendConfig => ({
  tenantId: process.env.NEXT_PUBLIC_TENANT_ID ?? "demo-tenant",
  runMode: asRunMode(process.env.NEXT_PUBLIC_RUN_MODE),
  replayLabel: asRunMode(process.env.NEXT_PUBLIC_REPLAY_LABEL ?? "replay"),
  liveActionsEnabled: asBoolean(process.env.NEXT_PUBLIC_LIVE_ACTIONS_ENABLED, false),
});
