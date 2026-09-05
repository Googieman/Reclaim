import { expect, test, type Page } from "@playwright/test";

const inboxPage = {
  schema_version: "case-inbox-v1.0.0",
  tenant_id: "demo-tenant",
  correlation_id: "browser-test-correlation",
  items: [
    {
      tenant_id: "demo-tenant",
      case_id: "case-001",
      incident_id: "incident-001",
      merchant_name: "Northstar merchant",
      source: "merchant_portal",
      incident_type: "account_takeover",
      occurred_at: "2026-09-03T09:00:00Z",
      state: "analyzed",
      updated_at: "2026-09-03T09:05:00Z",
      created_at: "2026-09-03T09:01:00Z",
      identifiers: { account: "account-001" },
      reported_amount_minor: 125000,
      reported_currency: "INR",
      external_reference: "order-001",
      orchestration: {
        run_id: "run-001",
        workflow_version: "n8n-v1.0.0",
        external_execution_id: "execution-001",
        stage: "analyze",
        status: "awaiting_human",
        queued_at: "2026-09-03T09:02:00Z",
        started_at: "2026-09-03T09:03:00Z",
        completed_at: null,
        updated_at: "2026-09-03T09:05:00Z",
        failure_code: null,
      },
    },
    {
      tenant_id: "demo-tenant",
      case_id: "case-002",
      incident_id: "incident-002",
      merchant_name: "Northstar merchant",
      source: "razorpay_test_mode",
      incident_type: "unauthorized_payment",
      occurred_at: "2026-09-03T10:00:00Z",
      state: "collecting_evidence",
      updated_at: "2026-09-03T10:05:00Z",
      created_at: "2026-09-03T10:01:00Z",
      identifiers: { payment: "payment-002" },
      reported_amount_minor: null,
      reported_currency: null,
      external_reference: null,
      orchestration: {
        run_id: "run-002",
        workflow_version: "n8n-v1.0.0",
        external_execution_id: "execution-002",
        stage: "normalize_intake",
        status: "running",
        queued_at: "2026-09-03T10:02:00Z",
        started_at: "2026-09-03T10:03:00Z",
        completed_at: null,
        updated_at: "2026-09-03T10:05:00Z",
        failure_code: null,
      },
    },
  ],
  next_cursor: null,
  has_more: false,
  limit: 25,
};

const modePayload = {
  requested_mode: "live",
  effective_mode: "live",
  final_mode: "live",
  provider_available: true,
  connector_available: true,
  provider_qualified: true,
  connector_qualified: true,
  live_execution_occurred: false,
  live_actions_enabled: false,
  live_financial_actions_enabled: false,
  availability_reasons: [],
  fallback_reason: null,
  label: "fresh_agent",
  simulation_notice: "Fresh Agent analysis + Action Gateway Simulator/Test Mode",
  decision_version: "local-authoritative-demo-v1.0.0",
};

const emptyPage = {
  ...inboxPage,
  items: [],
  next_cursor: null,
  has_more: false,
};

const acceptedIntake = {
  schema_version: "1.0.0",
  tenant_id: "demo-tenant",
  correlation_id: "intake-correlation",
  status: "accepted",
  incident_id: "incident-new",
  case_id: "case-new",
  reason: null,
  audit_reference: "audit-new",
};

const pageWithNewCase = {
  ...inboxPage,
  items: [
    {
      ...inboxPage.items[0],
      case_id: "case-new",
      incident_id: "incident-new",
      updated_at: "2026-09-03T11:01:00Z",
      created_at: "2026-09-03T11:00:00Z",
      orchestration: null,
    },
  ],
};

async function openInbox(page: Page) {
  const requests: URL[] = [];
  await page.route("**/tenants/**/cases**", async (route) => {
    requests.push(new URL(route.request().url()));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(inboxPage),
    });
  });
  await page.goto("/cases");
  await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
  await expect(page.getByRole("link", { name: "case-001" })).toBeVisible();
  return requests;
}

test.describe("case inbox navigation and interactions", () => {
  test("uses real route-backed navigation and marks the current route active", async ({ page }) => {
    await openInbox(page);
    const navigation = page.getByRole("navigation", { name: "Application navigation" });

    await expect(navigation.getByRole("link", { name: "Incidents" })).toHaveAttribute("href", "/cases");
    await expect(navigation.getByRole("link", { name: "Services" })).toHaveAttribute("href", "/services");
    await expect(navigation.getByRole("link", { name: "Review queue" })).toHaveAttribute("href", "/reviews");
    await expect(navigation.getByRole("link", { name: "Run history" })).toHaveAttribute("href", "/runs");
    await expect(navigation.getByRole("link", { name: "Audit trace" })).toHaveAttribute("href", "/audit");

    await navigation.getByRole("link", { name: "Services" }).click();
    await expect(page).toHaveURL(/\/services$/);
    await expect(page.getByRole("link", { name: "Services" })).toHaveAttribute("aria-current", "page");
  });

  test("sends supported filters to the authoritative inbox API and sorts visible cases", async ({ page }) => {
    const requests = await openInbox(page);
    const identifierSearch = page.getByLabel("Identifier search");

    await identifierSearch.fill("case-002");
    await expect(identifierSearch).toHaveValue("case-002");
    await page.getByRole("button", { name: "Search" }).click();
    await expect.poll(() => requests.at(-1)?.searchParams.get("q")).toBe("case-002");

    await page.getByLabel("Case state").selectOption("collecting_evidence");
    await expect.poll(() => requests.at(-1)?.searchParams.get("state")).toBe("collecting_evidence");

    await page.getByRole("button", { name: /Sort by Updated/ }).click();
    await expect(page.locator("[data-case-row]").first()).toContainText("case-002");
    await expect(page.getByRole("columnheader", { name: /Sort by Updated/ })).toHaveAttribute("aria-sort", "descending");
  });

  test("supports case selection, detail links, and Escape-dismissable drawers", async ({ page }) => {
    await openInbox(page);

    await page.keyboard.press("Control+K");
    await expect(page.getByRole("textbox", { name: "Search incidents" })).toBeFocused();
    await expect(page.getByRole("link", { name: "case-001" })).toHaveAttribute("href", "/cases/case-001");
    await page.getByRole("checkbox", { name: "Select case case-001" }).check();
    await expect(page.getByText("1 case selected")).toBeVisible();

    await page.getByRole("button", { name: "Review selected cases" }).click();
    await expect(page.getByRole("dialog", { name: "Selected cases" })).toBeVisible();
    await expect(page.getByRole("dialog").getByRole("link", { name: "case-001" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Selected cases" })).toBeHidden();

    await page.getByRole("button", { name: "New incident" }).click();
    await expect(page.getByRole("dialog", { name: "Report an incident" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Report an incident" })).toBeHidden();
  });

  test("supports mobile navigation and stacked incident cards", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openInbox(page);

    await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
    await expect(page.locator("[data-case-card]").first()).toBeVisible();
    await expect(page.locator(".case-table-wrap")).toBeHidden();

    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(page.getByRole("navigation", { name: "Application navigation" })).toHaveAttribute("data-mobile-open", "true");
    await page.getByRole("button", { name: "Close navigation" }).click();
    await expect(page.getByRole("navigation", { name: "Application navigation" })).toHaveAttribute("data-mobile-open", "false");
  });

  test("uses a compact rail and keeps the desktop table at tablet width", async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 900 });
    await openInbox(page);

    await expect(page.locator(".nav-rail .brand-word")).toBeHidden();
    await expect(page.getByRole("link", { name: "Services" })).toBeVisible();
    await expect(page.locator(".case-table-wrap")).toBeVisible();
    await expect(page.locator("[data-case-card]").first()).toBeHidden();
  });

  test("uses the server-qualified mode label instead of a hardcoded live label", async ({ page }) => {
    await page.route("**/tenants/demo-tenant/demo/mode**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(modePayload) }));
    await page.route("**/tenants/demo-tenant/cases**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(inboxPage) }));

    await page.goto("/cases");

    await expect(page.getByText("FRESH AGENT", { exact: false })).toBeVisible();
    await expect(page.getByText("LIVE READ", { exact: false })).toHaveCount(0);
  });

  test("refreshes and highlights the authoritative case returned by intake", async ({ page }) => {
    const caseRequests: URL[] = [];
    let intakeAccepted = false;
    await page.route("**/tenants/demo-tenant/demo/mode**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(modePayload) }));
    await page.route("**/tenants/demo-tenant/cases**", async (route) => {
      const url = new URL(route.request().url());
      caseRequests.push(url);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(intakeAccepted ? pageWithNewCase : inboxPage),
      });
    });
    await page.route("**/tenants/demo-tenant/incidents", (route) => {
      intakeAccepted = true;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(acceptedIntake) });
    });

    await page.goto("/cases");
    await expect(page.getByRole("link", { name: "case-001" })).toBeVisible();
    await page.locator('button[aria-controls="intake-panel"]').click();
    const intakeDialog = page.getByRole("dialog", { name: "Report an incident" });
    await expect(intakeDialog).toBeVisible();
    await intakeDialog.locator('input[type="datetime-local"]').fill("2026-09-03T11:00");
    await intakeDialog.locator("textarea").fill("Synthetic incident submitted from the operator inbox.");
    await intakeDialog.getByRole("button", { name: "Accept incident" }).click();

    await expect(page.locator("[data-case-row].case-row--highlighted")).toContainText("case-new");
    await expect.poll(() => caseRequests.at(-1)?.searchParams.get("q")).toBeNull();
    await expect.poll(() => caseRequests.at(-1)?.searchParams.get("state")).toBeNull();
    await expect.poll(() => caseRequests.at(-1)?.searchParams.get("automation_status")).toBeNull();
    await expect(page.getByText("Incident accepted. Case case-new is highlighted.")).toBeVisible();
  });

  test("shows API unavailable separately from an empty inbox", async ({ page }) => {
    await page.route("**/tenants/demo-tenant/demo/mode**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(modePayload) }));
    await page.route("**/tenants/demo-tenant/cases**", (route) =>
      route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "backend unavailable" }) }));

    await page.goto("/cases");

    await expect(page.getByRole("heading", { name: "API unavailable" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "No matching cases" })).toHaveCount(0);
  });

  test("shows an empty inbox only for a successful empty API response", async ({ page }) => {
    await page.route("**/tenants/demo-tenant/demo/mode**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(modePayload) }));
    await page.route("**/tenants/demo-tenant/cases**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(emptyPage) }));

    await page.goto("/cases");

    await expect(page.getByRole("heading", { name: "No matching cases" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "API unavailable" })).toHaveCount(0);
  });
});
