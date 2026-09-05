import { expect, test, type Page } from "@playwright/test";

const TENANT_ID = "tenant-canonical-demo";
const LIVE_BASE_URL = process.env.RECLAIM_T153_WEB_BASE_URL;

if (!LIVE_BASE_URL) {
  throw new Error("RECLAIM_T153_WEB_BASE_URL is required for the live browser suite.");
}

function marker(): string {
  return `browser-t153-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function submitIncident(page: Page, externalReference: string) {
  await page.getByRole("button", { name: "New incident" }).click();
  const dialog = page.getByRole("dialog", { name: "Report an incident" });
  await expect(dialog).toBeVisible();
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

test.describe("T153 real case inbox", () => {
  test("accepts a unique incident, highlights it, and searches the real case", async ({ page }, testInfo) => {
    await page.goto("/cases");
    await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
    const modeBadge = page.getByLabel(/FRESH AGENT:.*no live merchant effects/i);
    if (testInfo.project.name === "mobile") {
      await expect(modeBadge).toHaveCount(1);
    } else {
      await expect(modeBadge).toBeVisible();
    }
    await expect(page.getByText(TENANT_ID, { exact: true }).first()).toBeVisible();

    const externalReference = marker();
    const accepted = await submitIncident(page, externalReference);
    expect(accepted.status).toBe("accepted");
    expect(accepted.case_id).toBeTruthy();
    await expect(page.getByRole("dialog", { name: "Report an incident" })).toBeHidden();
    await expect(page.locator('[role="status"].workspace-notice')).toContainText(
      `Incident accepted. Case ${accepted.case_id} is highlighted.`,
    );

    const highlightedRow = page.locator("[data-case-row].case-row--highlighted").filter({ hasText: accepted.case_id });
    await expect(highlightedRow).toHaveCount(1);
    if (testInfo.project.name === "mobile") {
      const highlightedCard = page.locator("[data-case-card].case-card--highlighted").filter({ hasText: accepted.case_id });
      await expect(highlightedCard).toBeVisible();
      await highlightedCard.getByRole("link", { name: accepted.case_id }).focus();
      await expect(highlightedCard.getByRole("link", { name: accepted.case_id })).toBeFocused();
    } else {
      await expect(highlightedRow).toBeVisible();
    }

    await page.getByLabel("Identifier search").fill(externalReference);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    const matches = page.locator("[data-case-row]").filter({ hasText: externalReference });
    await expect(matches).toHaveCount(1);
    await expect(matches.first()).toContainText(accepted.case_id);
  });

  test("stops browser polling after a real terminal orchestration state", async ({ page }) => {
    await page.goto("/cases");
    await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
    const accepted = await submitIncident(page, marker());
    expect(accepted.status).toBe("accepted");
    await waitForTerminalOnInbox(page, accepted.case_id);
    await expect(page.getByText(/Auto-refreshing queued and running work/i)).toHaveCount(0);
  });
});
