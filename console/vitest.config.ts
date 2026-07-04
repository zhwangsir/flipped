import { defineConfig } from 'vitest/config';

// 前端单测:纯逻辑用 node 环境(无需 jsdom),覆盖 src 下 *.test.ts。
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
