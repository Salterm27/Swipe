// Browser tests for Swipe: rendering, event wiring, drag gestures and the
// async save queue — what the unit tests structurally can't reach.
// A real app server is booted against a throwaway data dir.
const { defineConfig } = require('@playwright/test');

const PORT = process.env.SWIPE_TEST_PORT || 8098;

module.exports = defineConfig({
  testDir: './tests/browser',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['github']] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    // CI runs `playwright install chromium`. Set PW_CHROMIUM to reuse a
    // browser already on the machine instead.
    launchOptions: process.env.PW_CHROMIUM
      ? { executablePath: process.env.PW_CHROMIUM }
      : {},
  },
  webServer: {
    command: `rm -rf ./.pw-tmp && ${process.env.PYTHON || 'python3'} app.py`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    env: { SWIPE_PORT: String(PORT), SWIPE_DATA: './.pw-tmp' },
  },
});
