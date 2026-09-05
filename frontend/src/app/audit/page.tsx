import { RouteSurface } from "@/components/navigation/RouteSurface";
import { getFrontendConfig } from "@/lib/config";

export default function AuditPage() {
  return <RouteSurface tenantId={getFrontendConfig().tenantId} title="Audit trace" description="Follow immutable provenance for case decisions, approvals, execution, and verification." sourceNote="Audit records require a case scope in the current API contract, so the standalone audit collection remains unavailable." />;
}
