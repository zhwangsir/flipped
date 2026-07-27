/**
 * flipped · 性能测试专用 Playwright 配置。
 *
 * 主 config 在 console/playwright.config.ts，testDir=./e2e，只跑功能 E2E。
 * 本 config 把 testDir 指向 tests/performance/，让 lighthouse.spec.ts 等性能
 * 用例与功能 E2E 隔离——性能测试不阻塞功能回归，可独立调度。
 *
 * 跑法：
 *   cd console && npx playwright test --config=../tests/performance/playwright.config.ts
 *
 * 仅 chromium：lighthouse 只在 chromium 内核下能跑（依赖 CDP）。
 * webServer 复用已在运行的 dev / preview server（不自动起，避免与 dev 工作流冲突）。
 */
// 用相对路径 import：tests/performance/ 不在 console/node_modules 的 resolve 路径里，
// 直接 `from '@playwright/test'` 会 MODULE_NOT_FOUND。
import { defineConfig, devices } from '../../console/node_modules/@playwright/test/index.mjs';

export default defineConfig({
  testDir: '.',
  fullyParallel: false, // 性能测试串行跑，避免互相干扰 metrics
  forbidOnly: !!process.env.CI,
  retries: 0, // 性能基线不重试，第一次失败即报
  workers: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: '../../reports/perf/playwright-report' }]],
  use: {
    baseURL: 'http://127.0.0.1:5273',
    trace: 'off',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // 不自动起 webServer：性能测试要求 dev/preview server 已在跑
  // （dev_up.sh 启 dev，perf_monitor.sh 启 preview）
});
