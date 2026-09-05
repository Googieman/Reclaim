import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./src",
  testMatch: "**/*.browser.spec.ts",
  testIgnore: "**/*.live.browser.spec.ts",
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: "npm run dev -- --hostname 127.0.0.1 --port 3000",
    url: "http://localhost:3000/cases",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
