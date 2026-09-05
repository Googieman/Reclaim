import { RouteSurface } from "@/components/navigation/RouteSurface";
import { getFrontendConfig } from "@/lib/config";

export default function RunsPage() {
  return <RouteSurface tenantId={getFrontendConfig().tenantId} title="Run history" description="Trace durable orchestration stages and their recovery state." sourceNote="Run records are currently returned with the tenant-scoped case inbox and case detail read models, not as a standalone collection." />;
}
