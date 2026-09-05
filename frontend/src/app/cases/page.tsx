import { CaseInbox } from "@/components/cases/CaseInbox";
import { getFrontendConfig } from "@/lib/config";

export default function CasesPage() {
  return <CaseInbox tenantId={getFrontendConfig().tenantId} />;
}
