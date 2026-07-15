import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 前端单测:jsdom 环境支持 React 组件渲染(.tsx),同时兼容原有纯逻辑 .test.ts。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    setupFiles: ['./src/test-setup.ts'],
  },
});
