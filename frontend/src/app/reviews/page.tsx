import { RouteSurface } from "@/components/navigation/RouteSurface";
import { getFrontendConfig } from "@/lib/config";

export default function ReviewsPage() {
  return <RouteSurface tenantId={getFrontendConfig().tenantId} title="Review queue" description="Find cases that require an authorized human decision." sourceNote="Review records are currently available through each case's authoritative read model, not as a standalone collection." />;
}
