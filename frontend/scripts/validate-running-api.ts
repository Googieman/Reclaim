import { modeAvailabilitySchema, operatorCaseViewSchema } from "../src/lib/api";

const baseUrl = process.env.RECLAIM_SMOKE_BASE_URL ?? "http://127.0.0.1:3000";
const tenantId = "tenant-canonical-demo";
const caseId = "case-canonical-demo-001";
const headers = { Authorization: `Bearer ${process.env.RECLAIM_SMOKE_TOKEN ?? "demo-reviewer"}` };

const [viewResponse, modeResponse] = await Promise.all([
  fetch(`${baseUrl}/tenants/${tenantId}/cases/${caseId}/operator-view`, { headers }),
  fetch(`${baseUrl}/tenants/${tenantId}/demo/mode`, { headers }),
]);

if (!viewResponse.ok || !modeResponse.ok) {
  throw new Error(`RECLAIM smoke request failed: view=${viewResponse.status} mode=${modeResponse.status}`);
}

const viewResult = operatorCaseViewSchema.safeParse(await viewResponse.json());
const modeResult = modeAvailabilitySchema.safeParse(await modeResponse.json());
if (!viewResult.success) {
  console.error(viewResult.error.issues);
  throw new Error("operator view does not satisfy the browser contract");
}
if (!modeResult.success) {
  console.error(modeResult.error.issues);
  throw new Error("mode response does not satisfy the browser contract");
}

console.log(
  JSON.stringify({
    caseId: viewResult.data.case.case_id,
    mode: modeResult.data.final_mode,
    readOnly: viewResult.data.read_only,
    authoritative: viewResult.data.authoritative,
    remoteSideEffects: viewResult.data.remote_side_effects.length,
  }),
);
