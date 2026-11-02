const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/browser',
  timeout: 120_000,
  retries: 0,
  workers: 1,
  reporter: 'line',
  use: {
    baseURL: process.env.CAS_BROWSER_URL || 'http://127.0.0.1:8765',
    channel: 'chrome',
    headless: true,
  },
});
