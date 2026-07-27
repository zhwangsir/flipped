import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 前端单测:jsdom 环境支持 React 组件渲染(.tsx),同时兼容原有纯逻辑 .test.ts。
// M151 循环测试:接入 v8 coverage，质量门禁 thresholds.lines=40（基线 43%）。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    setupFiles: ['./src/test-setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'text-summary', 'json-summary', 'html'],
      reportsDirectory: './coverage',
      // Vitest 4 移除 coverage.all（默认只报告被加载的文件）。
      // 显式 include 确保未加载的源文件也纳入覆盖率分母（与 v2/v3 行为一致）。
      include: ['src/**/*.{ts,tsx}'],
      // 质量门禁 floor（当前基线 29.36% lines，留 1% 余量防回归）。
      // 目标值 50% lines（TEST_PLAN.md 追踪，循环测试逐轮抬升，非硬门禁）。
      thresholds: {
        lines: 28,
        statements: 28,
        branches: 35,
        functions: 40,
      },
      // 排除：类型定义、生成产物、测试桩、入口引导
      exclude: [
        'src/**/*.d.ts',
        'src/main.tsx',
        'src/test-setup.ts',
        'src/api-types.d.ts',
        'src/icons.tsx',
        'coverage/**',
        'dist/**',
        'node_modules/**',
      ],
    },
  },
});
