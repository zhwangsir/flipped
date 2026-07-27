/**
 * 后端可用性探测 · 共享 fixture。
 *
 * 用于真正的"后端 API 集成测试"（如 factory-api.spec.ts 用 Playwright `request` context
 * 直连 :8011）。这类测试无法用 page.route 拦截（page.route 只拦 browser page 请求），
 * 因此采用环境门控：后端在时跑真集成，后端不在时显式 skip（带原因），而非伪装通过。
 *
 * 项目先例：console.spec.ts 的 E2E_MOCK_APPROVAL 门控（STATE.json D-record）。
 *
 * 用法：
 *   import { isBackendAvailable } from '../fixtures/backend-available';
 *   let backendAvailable = false;
 *   test.beforeAll(async () => { backendAvailable = await isBackendAvailable(); });
 *   test.beforeEach(async () => {
 *     test.skip(!backendAvailable, '需真实后端 :8011，当前不可达');
 *   });
 */
import { request as pwRequest } from '@playwright/test';

export async function isBackendAvailable(baseUrl = 'http://127.0.0.1:8011'): Promise<boolean> {
  try {
    const ctx = await pwRequest.newContext({ baseURL: baseUrl });
    const res = await ctx.get('/api/v1/factories', { timeout: 2000 });
    await ctx.dispose();
    return res.ok();
  } catch {
    return false;
  }
}
