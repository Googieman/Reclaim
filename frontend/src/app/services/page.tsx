import { RouteSurface } from "@/components/navigation/RouteSurface";
import { getFrontendConfig } from "@/lib/config";

export default function ServicesPage() {
  return <RouteSurface tenantId={getFrontendConfig().tenantId} title="Services" description="Review connector scope and service readiness for this tenant." sourceNote="There is no authoritative service collection endpoint in the current API contract." />;
}
