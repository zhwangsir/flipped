import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright 跨浏览器兼容性配置（E2E 全维度测试）
 *
 * 项目浏览器矩阵（与 .github/workflows/ci.yml matrix 对齐）：
 *   - chromium：Desktop Chrome（Chromium 内核，CI 主力）
 *   - firefox ：Desktop Firefox（Gecko 内核，验证非 Chromium 行为）
 *   - webkit  ：Desktop Safari（WebKit 内核，验证 macOS/iOS 行为）
 *
 * 测试维度（覆盖用户要求的 5 维度）：
 *   - 功能验证    ：e2e/*.spec.ts + e2e/compatibility/{interaction,routing,layout}.spec.ts
 *   - 边界条件    ：e2e/boundary/{input,viewport,concurrent-ops}.spec.ts
 *   - 异常处理    ：e2e/error-handling/{api-failure,malformed-response,websocket}.spec.ts
 *   - 性能测试    ：e2e/performance/{interaction-perf,core-web-vitals,long-running}.spec.ts
 *   - 兼容性测试  ：e2e/compatibility/{responsive,interaction,routing,layout}.spec.ts + 三浏览器矩阵
 *
 * 报告输出（满足"生成完整测试报告"要求）：
 *   - HTML  ：reports/e2e-html/index.html（人工查阅，含截图/trace）
 *   - JSON  ：reports/e2e-results.json（机器可读，喂给 scripts/gen_e2e_report.py）
 *   - list  ：控制台实时输出
 *
 * webServer 复用已在运行的 dev server；未运行则自动启动 `npm run dev`。
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 1,
  workers: process.env.CI ? 1 : undefined,
  // 全局超时：单 case 60s（性能/长时运行 case 内部自定 timeout 覆盖）
  timeout: 60_000,
  expect: { timeout: 5_000 },
  // 输出目录：失败截图/trace/视频集中存放，便于报告引用
  outputDir: './reports/e2e-artifacts',
  // 报告：HTML + JSON + list 三管齐下，覆盖人工查阅与机器解析
  reporter: [
    ['html', { outputFolder: 'reports/e2e-html', open: 'never' }],
    ['json', { outputFile: 'reports/e2e-results.json' }],
    ['list'],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5273',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // 收集控制台错误：让 console-errors.spec.ts 能断言 pageconsole
    viewport: { width: 1280, height: 800 },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
  ],
  // 复用已在运行的 dev server；未运行则自动启动
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:5273',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
