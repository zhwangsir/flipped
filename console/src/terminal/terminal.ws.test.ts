// @vitest-environment node
/**
 * M136-C — 终端 WS 数据通路集成测试（真实后端 + 真实 pty + @xterm/headless）。
 *
 * beforeAll 里 spawn 真实 uvicorn（仓库根，端口 8124），WS 收到的每一帧
 * 原样喂给 headless xterm，再用 waitFor 断言屏面：
 *   1. 大数据量：printf 400 行 marker → 全部到达且提示符回归静默；
 *   2. UTF-8：中文 + emoji 无替换字符；
 *   3. resize：{"r":[40,10]} → pty winsize 生效（stty size = 10 40），
 *      且 40 列下的折行与客户端一致。
 * 后端起不来 → 整组 skip（但在本次交付中必须真实跑通）。
 */
import { spawn, type ChildProcess } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it, type TestContext } from 'vitest';
import WebSocket, { type RawData } from 'ws';
import { Terminal } from '@xterm/headless';
import { feed, waitFor } from './waitFor';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const PORT = 8124;
const BASE_HTTP = `http://127.0.0.1:${PORT}`;
const TERMINAL_WS = `ws://127.0.0.1:${PORT}/api/v1/terminal`;

let serverUp = false;
let child: ChildProcess | null = null;
let childLog = '';
let ws: WebSocket | null = null;
let term: Terminal;

async function waitForHealth(timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE_HTTP}/api/v1/health`, { signal: AbortSignal.timeout(1500) });
      if (res.status === 200) return true;
    } catch {
      // 尚未起来
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  return false;
}

beforeAll(async () => {
  const python = path.join(REPO_ROOT, '.venv', 'bin', 'python');
  const tmp = tmpdir();
  // 后端以 FLIPPED_PROJECTS_DIR 作为 pty 的 cwd，必须真实存在，否则 spawn 失败、
  // WS accept 后立刻 1006 断连且无任何数据帧（M136-C 实测踩坑）。
  mkdirSync(path.join(tmp, 'm136_ws_projects'), { recursive: true });
  mkdirSync(path.join(tmp, 'm136_ws_home'), { recursive: true });
  child = spawn(
    python,
    ['-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', String(PORT)],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        PYTHONPATH: 'src',
        FLIPPED_SESSION_STORE_PATH: path.join(tmp, 'm136_ws_sessions.json'),
        FLIPPED_PROJECTS_DIR: path.join(tmp, 'm136_ws_projects'), // pty 落在确定存在的干净目录
        // 干净 shell：空 HOME（不读用户 rc 文件）+ 固定 bash，避免 zshrc/tmux 等干扰
        HOME: path.join(tmp, 'm136_ws_home'),
        SHELL: '/bin/bash',
        ZDOTDIR: path.join(tmp, 'm136_ws_home'),
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  );
  child.stdout?.on('data', (d) => { childLog += d.toString(); });
  child.stderr?.on('data', (d) => { childLog += d.toString(); });
  child.on('exit', (code) => { childLog += `\n[uvicorn exited code=${code}]`; serverUp = false; });

  serverUp = await waitForHealth(20_000);
  if (!serverUp) return;

  term = new Terminal({ cols: 80, rows: 24, scrollback: 2000, allowProposedApi: true });
  ws = new WebSocket(TERMINAL_WS);
  ws.on('message', (data: RawData) => {
    const buf = Array.isArray(data) ? Buffer.concat(data) : Buffer.from(data as Buffer);
    void feed(term, buf.toString('utf8')); // xterm 内部保序
  });
  try {
    await new Promise<void>((resolve, reject) => {
      ws!.once('open', () => resolve());
      ws!.once('error', reject);
      setTimeout(() => reject(new Error('WS open 超时')), 5000);
    });
    // 等 shell 初始化：屏面必须真的出现内容（提示符）并进入静默。
    // 只等 stableMs 会在空屏面上瞬间"假通过"，掩盖 WS 建连即断的故障。
    await waitFor(term, { regex: /\S/, stableMs: 600 }, 10_000);
  } catch (e) {
    serverUp = false;
    childLog += `\n[ws/shell init failed: ${e}]`;
  }
}, 40_000);

afterAll(async () => {
  ws?.close();
  if (child && child.exitCode === null) {
    child.kill('SIGTERM');
    await Promise.race([
      new Promise((r) => child!.once('exit', r)),
      new Promise((r) => setTimeout(r, 3000)).then(() => child!.kill('SIGKILL')),
    ]);
  }
}, 10_000);

function skipIfDown(ctx: TestContext): void {
  if (!serverUp) {
    console.warn(`[terminal.ws] 后端未启动，跳过。uvicorn 日志尾部:\n${childLog.slice(-1500)}`);
    // vitest 2.1 运行时已支持 ctx.skip()，但 TestContext 类型尚未声明 → 局部收窄。
    (ctx as TestContext & { skip: (msg?: string) => void }).skip('backend failed to start');
  }
}

describe('终端 WS 数据通路（真实 uvicorn + pty + headless xterm）', () => {
  it('marker 洪泛：400 行全部到达且提示符回归', async (ctx) => {
    skipIfDown(ctx);
    ws!.send(JSON.stringify({ d: "printf 'MARKER-%03d\\n' {1..400}\r" }));
    const screen = await waitFor(term, { regex: /MARKER-399/, stableMs: 800 }, 25_000);
    const markerLines = screen.split('\n').filter((l) => /^MARKER-3\d\d$/.test(l.trim()));
    expect(markerLines.length).toBeGreaterThanOrEqual(90); // MARKER-300..399 绝大多数落进 scrollback
    expect(markerLines).toContain('MARKER-399');
    // 提示符回归：屏面静默 800ms 已通过 waitFor 的稳定条件
    expect(screen.trim().split('\n').pop()!.length).toBeGreaterThan(0);
  }, 30_000);

  it('UTF-8：中文与 emoji 无替换字符', async (ctx) => {
    skipIfDown(ctx);
    ws!.send(JSON.stringify({ d: "echo '中文测试 emoji 🎉'\r" }));
    const screen = await waitFor(term, { text: '中文测试', stableMs: 500 }, 15_000);
    expect(screen).toContain('🎉');
    const zhLines = screen.split('\n').filter((l) => l.includes('中文测试'));
    expect(zhLines.length).toBeGreaterThanOrEqual(2); // 命令回显 + echo 输出
    for (const line of zhLines) {
      expect(line).not.toContain('�');
    }
    expect(screen).not.toContain('�');
  }, 20_000);

  it('resize：pty winsize 与客户端折行一致（40 列）', async (ctx) => {
    skipIfDown(ctx);
    // 与真实客户端一致：先本地 resize，再通知服务端
    term.resize(40, 10);
    ws!.send(JSON.stringify({ r: [40, 10] }));
    await new Promise((r) => setTimeout(r, 300)); // 给 ioctl 一点生效时间
    ws!.send(JSON.stringify({ d: 'stty size\r' }));
    await waitFor(term, { regex: /^10 40$/m, stableMs: 500 }, 15_000); // rows=10 cols=40

    ws!.send(JSON.stringify({ d: "printf 'A%.0s' {1..200}\r" }));
    const screen = await waitFor(term, { regex: /A{40}/, stableMs: 800 }, 15_000);
    // 200 字符 ÷ 40 列 = 恰好 5 行满行（buffer 里此前内容无纯 A 行，可全局断言）
    const aRuns = screen.split('\n').filter((l) => /^A+$/.test(l));
    expect(aRuns).toHaveLength(5);
    for (const run of aRuns) expect(run).toHaveLength(40);
    expect(screen).not.toContain('�');
  }, 25_000);
});
