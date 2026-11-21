import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:4174",
  },
  webServer: {
    command: "npm run dev -- -p 4174",
    cwd: __dirname,
    url: "http://127.0.0.1:4174",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_ADMIN_API_URL: "http://127.0.0.1:8123",
    },
  },
})
