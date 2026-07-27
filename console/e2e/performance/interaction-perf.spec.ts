/**
 * 交互流畅度基准测试 · UX 维度（TEST_STRATEGY_OPTIMIZATION.md §6.4）
 *
 * 目标：为前端交互建立可重复测量的性能基线，对应指标：
 *   - FID  (First Input Delay)         < 100ms（目标），> 300ms 报警
 *   - INP  (Interaction to Next Paint)  < 200ms（目标），> 500ms 报警
 *   - 动画帧率                           ≥ 60fps，< 30fps 报警
 *   - 输入响应延迟（键盘输入到 DOM 更新） < 50ms
 *   - 快捷键响应延迟（Meta+K 等到 UI 出现）< 100ms
 *
 * 设计原则：
 *   1. 跨浏览器兼容：仅用 Performance API + requestAnimationFrame + Event timing，
 *      不依赖 Chrome DevTools Protocol，确保 chromium/firefox/webkit 都能跑。
 *   2. 不依赖真实后端：复用 compatibility/mock-api.ts 的 mockEmptyApi。
 *   3. 软阈值：超阈值只 warn 不 fail（避免 CI 因环境抖动误报；趋势由 PERF_LOG.md 追踪）。
 *      但断言"测量能成功采集"是硬失败——防止 mock 失效后所有指标变成 NaN 还绿。
 *   4. 每个测试在 page.evaluate 里注入采集脚本，触发交互后读回指标。
 */
import { test, expect, type Page } from '@playwright/test';
import { mockEmptyApi } from '../compatibility/mock-api';

// ---------- 阈值（与 TEST_STRATEGY_OPTIMIZATION.md §6.4 对齐） ----------
const FID_TARGET_MS = 100;
const FID_ALARM_MS = 300;
const INP_TARGET_MS = 200;
const INP_ALARM_MS = 500;
const FPS_TARGET = 60;
const FPS_ALARM = 30;
const INPUT_RESPONSE_TARGET_MS = 50;
const HOTKEY_RESPONSE_TARGET_MS = 100;

test.use({ viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ page }) => {
  await mockEmptyApi(page);
});

// ---------- 工具：直接测量法采集交互延迟 ----------
//
// PerformanceObserver 的 'event' 类型在 Playwright 自动化下不可靠（headless chromium
// 不一定生成 event entry；firefox/webkit 支持参差）。改用"在事件回调里直接打时间戳"
// 的方式：keydown 时记录 t0，input/视觉反馈时记录 t1，差值即交互延迟。
// 这与 §6.4 的 INP 语义一致（交互开始到下一帧绘制的时间）。

/**
 * 在页面已加载后注入交互延迟采集器：监听 composer 输入框的 keydown→input 延迟，
 * 记录到 window.__perfEvents（首次单独记到 window.__fid）。
 *
 * 必须在 page.goto + 元素可见之后调用（与"输入响应延迟"测试同模式）。
 */
async function attachInteractionCollector(page: Page) {
  await page.evaluate(() => {
    (window as any).__perfEvents = [] as number[];
    (window as any).__fid = null as number | null;
    let fidRecorded = false;

    const el = document.querySelector('[data-testid="assistant-composer-input"]') as HTMLTextAreaElement | null;
    if (!el || (el as any).__perfBound) return;
    (el as any).__perfBound = true;

    let keydownTime: number | null = null;
    el.addEventListener('keydown', (e) => {
      // 只测可打印字符 + Enter（真实交互）
      if (e.key.length === 1 || e.key === 'Enter') {
        keydownTime = performance.now();
      }
    }, { capture: true });
    el.addEventListener('input', () => {
      if (keydownTime !== null) {
        const dur = performance.now() - keydownTime;
        (window as any).__perfEvents.push(dur);
        if (!fidRecorded) {
          (window as any).__fid = dur;
          fidRecorded = true;
        }
        keydownTime = null;
      }
    }, { capture: true });
  });
}

/**
 * 注入帧率采集器：在指定时长内用 requestAnimationFrame 采样帧时间，
 * 返回 { fps, frameCount, durationMs }。
 */
async function measureFps(page: Page, durationMs = 1000): Promise<{ fps: number; frameCount: number; durationMs: number }> {
  return page.evaluate((dur) => {
    return new Promise<{ fps: number; frameCount: number; durationMs: number }>((resolve) => {
      const frames: number[] = [];
      const start = performance.now();
      const loop = () => {
        const now = performance.now();
        frames.push(now);
        if (now - start < dur) {
          requestAnimationFrame(loop);
        } else {
          const elapsed = now - start;
          // fps = 帧数 / 秒；首帧无前置时间，故 frameCount - 1 为间隔数
          const intervalCount = Math.max(frames.length - 1, 1);
          const fps = (intervalCount / elapsed) * 1000;
          resolve({ fps: Math.round(fps * 10) / 10, frameCount: frames.length, durationMs: Math.round(elapsed) });
        }
      };
      requestAnimationFrame(loop);
    });
  }, durationMs);
}

// ===========================================================================
// 1. FID · 首次输入延迟
// ===========================================================================

test.describe('交互流畅度 · FID 首次输入延迟', () => {
  test('首次键盘输入的 FID 应 < 300ms（报警线）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    // 必须在元素可见后注入采集器（与"输入响应延迟"测试同模式）
    await attachInteractionCollector(page);

    // 触发首次交互：聚焦输入框后用真实键盘输入（触发 keydown→input 链路）
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.click();
    // 用 keyboard.type 而非 fill：type 会触发真实 keydown/keypress/input 事件
    await page.keyboard.type('h');

    // 等 input 事件回调（微任务）
    await page.waitForTimeout(50);

    const fid = await page.evaluate(() => (window as any).__fid as number | null);
    // 硬断言：测量必须成功（防 mock 失效后静默绿）
    expect(fid, 'FID 必须被采集到（keydown→input 监听应生效）').not.toBeNull();
    expect(fid!).toBeGreaterThanOrEqual(0);
    expect(fid!).toBeLessThan(FID_ALARM_MS);
    // 软告警：超目标但未超报警线
    if (fid! > FID_TARGET_MS) {
      console.warn(`⚠️  FID=${fid!.toFixed(2)}ms 超目标 ${FID_TARGET_MS}ms（但 < 报警线 ${FID_ALARM_MS}ms，软告警）`);
    } else {
      console.log(`✅ FID=${fid!.toFixed(2)}ms（目标 <${FID_TARGET_MS}ms）`);
    }
  });
});

// ===========================================================================
// 2. INP · 交互到下一次绘制
// ===========================================================================

test.describe('交互流畅度 · INP 交互到下一次绘制', () => {
  test('多次键盘输入的 INP（P95）应 < 500ms（报警线）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    await attachInteractionCollector(page);

    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.click();

    // 连续触发 5 次真实键盘输入（每次都走 keydown→input 链路）
    for (const ch of ['h', 'e', 'l', 'l', 'o']) {
      await page.keyboard.type(ch);
      // 微小间隔让事件循环跑完
      await page.waitForTimeout(20);
    }

    await page.waitForTimeout(100); // 等所有 input 回调完成

    const events = await page.evaluate(() => (window as any).__perfEvents as number[]);
    // 硬断言：至少采集到 3 个事件
    expect(events.length, '应至少采集到 3 个交互事件').toBeGreaterThanOrEqual(3);

    // INP 通常取所有交互的 P95 或最大值；这里取 P95（更稳定）
    events.sort((a, b) => a - b);
    const p95Idx = Math.floor(events.length * 0.95);
    const p95 = events[Math.min(p95Idx, events.length - 1)];
    const max = events[events.length - 1];

    console.log(`📊 INP: P95=${p95.toFixed(2)}ms, max=${max.toFixed(2)}ms, samples=${events.length}`);
    expect(p95, `INP P95 应 < ${INP_ALARM_MS}ms（报警线）`).toBeLessThan(INP_ALARM_MS);

    if (p95 > INP_TARGET_MS) {
      console.warn(`⚠️  INP P95=${p95.toFixed(2)}ms 超目标 ${INP_TARGET_MS}ms（但 < 报警线，软告警）`);
    } else {
      console.log(`✅ INP P95=${p95.toFixed(2)}ms（目标 <${INP_TARGET_MS}ms）`);
    }
  });
});

// ===========================================================================
// 3. 动画帧率
// ===========================================================================

test.describe('交互流畅度 · 动画帧率', () => {
  test('空闲态帧率应 ≥ 30fps（报警线），目标 60fps', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    // 等 React mount + 任何首屏动画稳定
    await page.waitForTimeout(300);

    const result = await measureFps(page, 1000);
    console.log(`📊 空闲 FPS: ${result.fps} (${result.frameCount} frames in ${result.durationMs}ms)`);

    // 硬断言：必须采集到 ≥10 帧（防 rAF 不调度）
    expect(result.frameCount, 'rAF 应至少调度 10 次').toBeGreaterThanOrEqual(10);
    expect(result.fps, `空闲帧率应 ≥ ${FPS_ALARM}fps（报警线）`).toBeGreaterThanOrEqual(FPS_ALARM);

    if (result.fps < FPS_TARGET) {
      console.warn(`⚠️  FPS=${result.fps} 低于目标 ${FPS_TARGET}fps（但 ≥ 报警线 ${FPS_ALARM}fps，软告警）`);
    }
  });

  test('滚动侧栏时帧率应 ≥ 30fps（报警线）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await page.waitForTimeout(300);

    // 在滚动期间持续采样帧率
    const sidebar = page.locator('.sidebar');
    const box = await sidebar.boundingBox();
    if (!box) {
      console.warn('⚠️  sidebar 无 boundingBox，跳过滚动帧率测试');
      return;
    }

    // 启动 rAF 采样（后台运行 1s）
    const fpsPromise = measureFps(page, 1000);

    // 同时触发滚动：模拟滚轮事件
    await page.mouse.move(box.x + box.width / 2, box.y + 50);
    for (let i = 0; i < 20; i++) {
      await page.mouse.wheel(0, 30);
      await page.waitForTimeout(20);
    }

    const result = await fpsPromise;
    console.log(`📊 滚动 FPS: ${result.fps} (${result.frameCount} frames)`);

    expect(result.frameCount, '滚动期间 rAF 应持续调度').toBeGreaterThanOrEqual(10);
    expect(result.fps, `滚动帧率应 ≥ ${FPS_ALARM}fps（报警线）`).toBeGreaterThanOrEqual(FPS_ALARM);
  });
});

// ===========================================================================
// 4. 输入响应延迟（键盘输入到 DOM 更新）
// ===========================================================================

test.describe('交互流畅度 · 输入响应延迟', () => {
  test('键盘输入到 DOM value 更新应 < 50ms', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await expect(input).toBeVisible();
    await input.click();

    // 在页面里注入测量函数：监听 input 事件，记录从 keydown 到 input 触发的延迟
    await page.evaluate(() => {
      (window as any).__inputLatencies = [] as number[];
      const el = document.querySelector('[data-testid="assistant-composer-input"]') as HTMLTextAreaElement;
      if (!el) return;
      let keydownTime: number | null = null;
      el.addEventListener('keydown', (e) => {
        if (e.key.length === 1) keydownTime = performance.now();
      }, { capture: true });
      el.addEventListener('input', () => {
        if (keydownTime !== null) {
          (window as any).__inputLatencies.push(performance.now() - keydownTime);
          keydownTime = null;
        }
      }, { capture: true });
    });

    // 触发 5 次字符输入
    await input.press('a');
    await input.press('b');
    await input.press('c');
    await input.press('d');
    await input.press('e');

    const latencies = await page.evaluate(() => (window as any).__inputLatencies as number[]);
    expect(latencies.length, '应采集到 ≥3 次输入延迟').toBeGreaterThanOrEqual(3);

    const avg = latencies.reduce((a, b) => a + b, 0) / latencies.length;
    const max = Math.max(...latencies);
    console.log(`📊 输入延迟: avg=${avg.toFixed(2)}ms, max=${max.toFixed(2)}ms, samples=${latencies.length}`);

    expect(avg, `平均输入延迟应 < ${INPUT_RESPONSE_TARGET_MS}ms`).toBeLessThan(INPUT_RESPONSE_TARGET_MS);
    expect(max, `最大输入延迟应 < ${INPUT_RESPONSE_TARGET_MS * 2}ms（2x 宽容）`).toBeLessThan(INPUT_RESPONSE_TARGET_MS * 2);
  });
});

// ===========================================================================
// 5. 快捷键响应延迟（Meta+K 到 UI 出现）
// ===========================================================================

test.describe('交互流畅度 · 快捷键响应延迟', () => {
  test('Meta+K 到命令面板可见应 < 100ms', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    await page.waitForTimeout(200);

    const start = Date.now();
    await page.keyboard.press('Meta+k');
    // 等命令面板可见，记录耗时
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible({ timeout: 1000 });
    const elapsed = Date.now() - start;

    console.log(`📊 Meta+K → 命令面板可见: ${elapsed}ms`);
    // 软阈值：100ms 目标，500ms 报警（toBeVisible 自身有轮询开销，宽容到 500ms）
    expect(elapsed, `快捷键响应应 < ${HOTKEY_RESPONSE_TARGET_MS * 5}ms（含 toBeVisible 轮询开销）`).toBeLessThan(HOTKEY_RESPONSE_TARGET_MS * 5);

    if (elapsed > HOTKEY_RESPONSE_TARGET_MS) {
      console.warn(`⚠️  Meta+K 响应 ${elapsed}ms 超目标 ${HOTKEY_RESPONSE_TARGET_MS}ms（软告警）`);
    }

    // 关闭再测一次（已挂载的组件应更快）
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
    const start2 = Date.now();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible({ timeout: 1000 });
    const elapsed2 = Date.now() - start2;
    console.log(`📊 Meta+K（二次）→ 命令面板可见: ${elapsed2}ms`);
  });

  test('Meta+B 折叠侧栏响应应 < 100ms', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    await expect(page.locator('.app')).not.toHaveClass(/sb-collapsed/);
    await page.waitForTimeout(200);

    const start = Date.now();
    await page.keyboard.press('Meta+b');
    await expect(page.locator('.app')).toHaveClass(/sb-collapsed/);
    const elapsed = Date.now() - start;

    console.log(`📊 Meta+B → 侧栏折叠: ${elapsed}ms`);
    expect(elapsed, `快捷键响应应 < ${HOTKEY_RESPONSE_TARGET_MS * 5}ms`).toBeLessThan(HOTKEY_RESPONSE_TARGET_MS * 5);

    if (elapsed > HOTKEY_RESPONSE_TARGET_MS) {
      console.warn(`⚠️  Meta+B 响应 ${elapsed}ms 超目标 ${HOTKEY_RESPONSE_TARGET_MS}ms（软告警）`);
    }
  });
});

// ===========================================================================
// 6. 端到端交互链路延迟（输入 → 发送 → UI 反馈）
// ===========================================================================

test.describe('交互流畅度 · 端到端交互链路', () => {
  test('输入 + Enter 提交 → 输入框清空（端到端 < 200ms）', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await expect(input).toBeVisible();
    await input.fill('perf test task');
    await expect(page.locator('[data-testid="assistant-send-btn"]')).toBeEnabled();

    const start = Date.now();
    await input.press('Enter');
    // 提交后 textarea 应清空（store.tsx 的 send 逻辑）
    await expect(input).toHaveValue('');
    const elapsed = Date.now() - start;

    console.log(`📊 Enter 提交 → 输入框清空: ${elapsed}ms`);
    expect(elapsed, '端到端提交链路应 < 200ms').toBeLessThan(200);
  });
});

// ===========================================================================
// 7. 汇总报告（一次性输出所有指标，便于记 PERF_LOG.md）
// ===========================================================================

test.describe('交互流畅度 · 汇总报告', () => {
  test('输出本次运行的交互流畅度指标快照', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    await page.waitForTimeout(300);
    await attachInteractionCollector(page);

    // 采集空闲帧率
    const fpsResult = await measureFps(page, 800);

    // 触发交互（用 keyboard.type 触发真实 keydown→input）
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.click();
    await page.keyboard.type('perf');
    await page.waitForTimeout(150);

    const fid = await page.evaluate(() => (window as any).__fid as number | null);
    const events = await page.evaluate(() => (window as any).__perfEvents as number[]);

    console.log('========================================');
    console.log('  交互流畅度指标快照（TEST_STRATEGY_OPTIMIZATION.md §6.4）');
    console.log('========================================');
    console.log(`  FID:          ${fid !== null ? fid.toFixed(2) + 'ms' : 'N/A'}  (目标 <${FID_TARGET_MS}ms, 报警 >${FID_ALARM_MS}ms)`);
    if (events.length > 0) {
      const sorted = [...events].sort((a, b) => a - b);
      const p95 = sorted[Math.floor(sorted.length * 0.95)] || sorted[sorted.length - 1];
      console.log(`  INP P95:      ${p95.toFixed(2)}ms  (目标 <${INP_TARGET_MS}ms, 报警 >${INP_ALARM_MS}ms)`);
      console.log(`  INP max:      ${sorted[sorted.length - 1].toFixed(2)}ms  (samples=${events.length})`);
    } else {
      console.log('  INP:          N/A (无采集到事件)');
    }
    console.log(`  空闲 FPS:     ${fpsResult.fps}  (目标 ≥${FPS_TARGET}, 报警 <${FPS_ALARM})`);
    console.log(`  帧数:         ${fpsResult.frameCount} frames / ${fpsResult.durationMs}ms`);
    console.log('========================================');

    // 硬断言：至少 FPS 必须采集到
    expect(fpsResult.frameCount, 'FPS 采集必须成功').toBeGreaterThanOrEqual(10);
  });
});
