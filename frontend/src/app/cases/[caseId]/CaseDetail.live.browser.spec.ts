import { expect, test, type Page } from "@playwright/test";

const TENANT_ID = "tenant-canonical-demo";
const LIVE_BASE_URL = process.env.RECLAIM_T153_WEB_BASE_URL;

if (!LIVE_BASE_URL) {
  throw new Error("RECLAIM_T153_WEB_BASE_URL is required for the live browser suite.");
}

function marker(): string {
  return `browser-t153-detail-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function submitIncident(page: Page, externalReference: string) {
  await page.getByRole("button", { name: "New incident" }).click();
  const dialog = page.getByRole("dialog", { name: "Report an incident" });
  await dialog.getByLabel("Source").fill("merchant_portal");
  await dialog.getByLabel("Incident type").selectOption("unauthorized_payment");
  await dialog.getByLabel("When did it occur?").fill("2026-09-04T12:00");
  await dialog.getByLabel("Narrative").fill("Operator supplied validation narrative.");
  await dialog.getByRole("textbox", { name: "Payment", exact: true }).fill(externalReference);
  await dialog.getByLabel("External ref.").fill(externalReference);
  await dialog.getByLabel("Amount").fill("123.45");
  await dialog.getByLabel("Currency").selectOption("INR");
  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes(`/tenants/${TENANT_ID}/incidents`),
  );
  await dialog.getByRole("button", { name: "Accept incident" }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  return (await response.json()) as { case_id: string; status: string };
}

async function waitForTerminalOnInbox(page: Page, caseId: string): Promise<void> {
  await expect
    .poll(
      async () =>
        (await page.locator("[data-case-row]").filter({ hasText: caseId }).first().textContent()) ??
        "",
      { timeout: 120_000, intervals: [1_000, 2_000, 5_000] },
    )
    .toMatch(/Awaiting human|Requires attention/i);
}

test("opens the real highlighted case and exposes safe terminal metadata", async ({ page }, testInfo) => {
  await page.goto("/cases");
  await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
  const externalReference = marker();
  const accepted = await submitIncident(page, externalReference);
  expect(accepted.status).toBe("accepted");
  await waitForTerminalOnInbox(page, accepted.case_id);

  const caseLink = testInfo.project.name === "mobile"
    ? page.locator("[data-case-card].case-card--highlighted").getByRole("link", { name: accepted.case_id })
    : page.locator("[data-case-row].case-row--highlighted").getByRole("link", { name: accepted.case_id });
  await caseLink.click();
  await expect(page).toHaveURL(new RegExp(`/cases/${accepted.case_id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
  await expect(page.getByRole("heading", { name: accepted.case_id })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Reported incident" })).toBeVisible();
  await expect(page.locator(".top-bar__context strong")).toHaveText(/\S+/);
  await expect(page.getByText("Unauthorized Payment", { exact: true })).toBeVisible();
  await expect(page.getByText(externalReference, { exact: true })).toBeVisible();
  await expect(page.getByText(/INR|₹/).filter({ hasText: /unverified/i })).toBeVisible();
  await expect(page.getByText("incident-analysis-handoff.v1", { exact: true })).toBeVisible();
  await expect(page.getByText(/awaiting human|requires attention/i).first()).toBeVisible();
  await expect(page.getByText("Operator supplied validation narrative.", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve exact action" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Run approved action in simulator/i })).toHaveCount(0);
});
