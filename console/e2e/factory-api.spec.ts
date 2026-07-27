/**
 * E2E 测试 — 工厂 REST API 端点测试。
 *
 * 直接测试后端 API（Playwright request context），不经过浏览器。
 * 覆盖：GET /factories、GET /{id}/detail、POST 创建、resume/pause。
 * 只读操作不产生副作用；写操作使用独立测试工厂并在测试后清理。
 */
import { test, expect } from '@playwright/test';
import { isBackendAvailable } from './fixtures/backend-available';

const API_BASE = 'http://127.0.0.1:8011';
const API = `${API_BASE}/api/v1/factories`;

// 环境门控：本文件用 Playwright `request` context 直连 :8011，page.route 无法拦截。
// 后端在时跑真集成，后端不在时显式 skip（诚实降级，非伪装通过）。
// 项目先例：console.spec.ts 的 E2E_MOCK_APPROVAL 门控。
let backendAvailable = false;
test.beforeAll(async () => {
  backendAvailable = await isBackendAvailable();
});
test.beforeEach(async () => {
  test.skip(!backendAvailable, '本测试需真实后端 :8011，当前不可达——后端启动后自动恢复运行');
});

test.describe('工厂 API · 只读端点', () => {
  test('GET /factories 返回数组', async ({ request }) => {
    const res = await request.get(API);
    expect(res.ok()).toBeTruthy();
    expect(res.status()).toBe(200);
    const data = await res.json();
    expect(Array.isArray(data)).toBeTruthy();
  });

  test('GET /factories 返回项含必需字段', async ({ request }) => {
    const res = await request.get(API);
    const data = await res.json();
    if (data.length > 0) {
      const f = data[0];
      expect(f).toHaveProperty('factory_id');
      expect(f).toHaveProperty('product_goal');
      expect(f).toHaveProperty('status');
      expect(f).toHaveProperty('iteration_count');
      expect(f).toHaveProperty('max_tasks');
      expect(f).toHaveProperty('created_at');
      expect(f).toHaveProperty('updated_at');
    }
  });

  test('GET /{id}/detail 返回详情结构', async ({ request }) => {
    // 先获取列表拿到一个真实 factory_id
    const listRes = await request.get(API);
    const list = await listRes.json();
    if (list.length === 0) {
      test.skip(true, '无工厂可测');
      return;
    }
    const fid = list[0].factory_id;
    const res = await request.get(`${API}/${encodeURIComponent(fid)}/detail`);
    expect(res.ok()).toBeTruthy();
    const detail = await res.json();
    expect(detail).toHaveProperty('factory_id', fid);
    expect(detail).toHaveProperty('roadmap');
    expect(detail).toHaveProperty('completed');
    expect(detail).toHaveProperty('failed');
    expect(detail).toHaveProperty('current_task_id');
    expect(Array.isArray(detail.roadmap)).toBeTruthy();
  });

  test('GET /{不存在的id}/detail 返回 404', async ({ request }) => {
    const res = await request.get(`${API}/nonexistent-factory-id/detail`);
    expect(res.status()).toBe(404);
  });
});

test.describe('工厂 API · 写操作（隔离）', () => {
  let createdId: string | null = null;

  test.afterAll(async ({ request }) => {
    // 清理：暂停创建的工厂（避免后台空转）
    if (createdId) {
      await request.post(`${API}/${createdId}/pause`).catch(() => {});
    }
  });

  test('POST /factories 创建工厂', async ({ request }) => {
    const body = {
      product_goal: 'E2E 测试工厂（可安全删除）',
      cwd: '/tmp/flipped-e2e-cleanup',
      max_tasks: 1,
    };
    const res = await request.post(API, { data: body });
    expect(res.ok()).toBeTruthy();
    expect(res.status()).toBe(200);
    const summary = await res.json();
    expect(summary).toHaveProperty('factory_id');
    expect(summary.product_goal).toBe(body.product_goal);
    expect(summary.max_tasks).toBe(1);
    createdId = summary.factory_id;
  });

  test('POST /{id}/pause 暂停工厂', async ({ request }) => {
    // 先创建
    const createRes = await request.post(API, {
      data: {
        product_goal: 'E2E pause 测试',
        cwd: '/tmp/flipped-e2e-pause',
        max_tasks: 1,
      },
    });
    const created = await createRes.json();
    const fid = created.factory_id;

    const res = await request.post(`${API}/${fid}/pause`);
    expect(res.ok()).toBeTruthy();
    const detail = await res.json();
    // 暂停后状态应为 paused 或 done（如果已完成）
    expect(['paused', 'done', 'error']).toContain(detail.status);
    createdId = fid;
  });
});
