import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.RECLAIM_T153_WEB_BASE_URL?.trim();

if (!baseURL) {
  throw new Error(
    "RECLAIM_T153_WEB_BASE_URL is required; run this suite only against the prepared T153 Compose UI.",
  );
}

export default defineConfig({
  testDir: "./src",
  testMatch: "**/*.live.browser.spec.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  reporter: "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 5"] },
    },
  ],
});
