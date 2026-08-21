import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:7300",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    {
      name: "firefox-motion",
      testMatch: /motion-smoke\.spec\.ts/,
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit-motion",
      testMatch: /motion-smoke\.spec\.ts/,
      use: { ...devices["Desktop Safari"] },
    },
    {
      name: "firefox-theme",
      testMatch: /theme-smoke\.spec\.ts/,
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit-theme",
      testMatch: /theme-smoke\.spec\.ts/,
      use: { ...devices["Desktop Safari"] },
    },
    {
      grep: /@selection/,
      name: "firefox-selection",
      testMatch: /reader\.spec\.ts/,
      use: { ...devices["Desktop Firefox"] },
    },
    {
      grep: /@selection/,
      name: "webkit-selection",
      testMatch: /reader\.spec\.ts/,
      use: { ...devices["Desktop Safari"] },
    },
  ],
  webServer: {
    command: "pnpm start",
    url: "http://127.0.0.1:7300",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
