import { defineConfig } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  globalSetup: './tests/camera-setup.ts',
  timeout: 120_000,
  projects: [
    { name: 'workspace', testIgnore: /(camera|webkit).spec.ts/, use: { channel: 'chrome' } },
    {
      name: 'webkit',
      testMatch: /webkit.spec.ts/,
      use: { browserName: 'webkit' },
    },
    {
      name: 'camera',
      testMatch: /camera.spec.ts/,
      use: {
        channel: 'chrome',
        permissions: ['camera'],
        launchOptions: {
          args: [
            '--use-fake-device-for-media-stream',
            '--use-fake-ui-for-media-stream',
            `--use-file-for-fake-video-capture=${fileURLToPath(new URL('../data/e2e-camera.y4m', import.meta.url))}`,
          ],
        },
      },
    },
  ],
  use: {
    baseURL: 'http://127.0.0.1:8128',
    viewport: { width: 1512, height: 1040 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },
  webServer: {
    command: `OREL_DATA_DIR=../data/e2e/${randomUUID()} ../.venv/bin/python -m uvicorn orel.app:app --app-dir .. --host 127.0.0.1 --port 8128`,
    url: 'http://127.0.0.1:8128/api/health',
    reuseExistingServer: false,
  },
})
