import { useEffect, useRef } from 'react';
// D-0014 修复：xterm 改为动态导入 —— @xterm/xterm + @xterm/addon-fit 是重依赖
// （合计 ~200KB+ JS），但仅在终端抽屉(⌘J)或右栏「终端」tab 激活时才需要。
// 改为 import type（编译时擦除，不进 entry chunk）+ useEffect 内 dynamic import
// （首次 active 时按需加载）。tests 不受影响：PtyTerminal 在测试里被整体 mock。
import type { Terminal, ITheme } from '@xterm/xterm';
import type { FitAddon } from '@xterm/addon-fit';
import { isTauri, createTerminal, writeTerminal, resizeTerminal, closeTerminal, listenTerminalData } from '../lib/native';

// 与 api.ts 一致:dev_up.sh 注入 VITE_API_BASE_URL=:8011;默认值取当前后端端口。
const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://127.0.0.1:8011';
const WS_URL = API_BASE.replace(/^http/, 'ws') + '/api/v1/terminal';

const DARK: ITheme = {
  background: '#1c1c1c',
  foreground: '#ededed',
  cursor: '#ededed',
  cursorAccent: '#1c1c1c',
  selectionBackground: '#3a3a3a',
  black: '#1c1c1c', red: '#f85149', green: '#3fb950', yellow: '#e0a545',
  blue: '#4a9eff', magenta: '#c586c0', cyan: '#4ec9b0', white: '#d4d4d4',
  brightBlack: '#6d6d6d', brightRed: '#ff7b72', brightGreen: '#56d364', brightYellow: '#f0c674',
  brightBlue: '#79b8ff', brightMagenta: '#d2a8ff', brightCyan: '#56d4bb', brightWhite: '#f5f5f5',
};
const LIGHT: ITheme = {
  background: '#ffffff',
  foreground: '#1a1a1a',
  cursor: '#1a1a1a',
  cursorAccent: '#ffffff',
  selectionBackground: '#d6d6d2',
  black: '#1a1a1a', red: '#c0392b', green: '#1a7f37', yellow: '#9a6700',
  blue: '#0a5bd0', magenta: '#8250df', cyan: '#127b7b', white: '#6f6f6f',
  brightBlack: '#a3a3a0', brightRed: '#cf222e', brightGreen: '#1a7f37', brightYellow: '#9a6700',
  brightBlue: '#0a5bd0', brightMagenta: '#8250df', brightCyan: '#127b7b', brightWhite: '#1a1a1a',
};

function pickTheme(): ITheme {
  return document.documentElement.getAttribute('data-theme') === 'light' ? LIGHT : DARK;
}

interface PtyTerminalProps {
  /** 是否处于可见/活动状态:惰性创建 pty + 可见时 fit/focus。 */
  active: boolean;
  className?: string;
}

/** 真实 pty 终端(xterm.js ↔ 后端 WebSocket pty 或 Tauri 原生 pty)。抽屉(⌘J)与右侧面板「终端」tab 共用。
 *
 * 首次 active 时惰性创建 terminal 并保持存活(shell 状态不丢);active 变化时 re-fit/focus。 */
export function PtyTerminal({ active, className }: PtyTerminalProps) {
  const holderRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const termIdRef = useRef<string | null>(null);
  const unlistenRef = useRef<(() => void) | null>(null);
  const readyRef = useRef(false);

  // 主题热切换：全局 data-theme 变化时同步 xterm 配色(此前仅创建时取一次，切主题后终端颜色不更新)
  useEffect(() => {
    const obs = new MutationObserver(() => {
      if (termRef.current) termRef.current.options.theme = pickTheme();
    });
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => obs.disconnect();
  }, []);

  // 创建终端。创建成功后保持实例，隐藏时仅停止渲染，不销毁 shell 会话。
  // D-0014: xterm 模块改为 dynamic import —— 首次 active 时才加载 @xterm/xterm +
  // @xterm/addon-fit（~200KB+ JS），不进 entry chunk，Assistant 首屏不加载终端代码。
  useEffect(() => {
    if (!active || termRef.current || !holderRef.current) return;

    let cancelled = false;
    // term 在 async setup 内赋值，cleanup 通过闭包引用（可能仍为 null）。
    let term: Terminal | null = null;
    const isTauriMode = isTauri();

    const setup = async () => {
      // D-0014: dynamic import —— @xterm/xterm + @xterm/addon-fit + xterm.css
      const [xt, fa] = await Promise.all([
        import('@xterm/xterm'),
        import('@xterm/addon-fit'),
      ]);
      await import('@xterm/xterm/css/xterm.css');
      if (cancelled || !holderRef.current) return;

      const t = new xt.Terminal({
        fontSize: 12.5,
        fontFamily: '"Geist Mono Variable", ui-monospace, "SF Mono", Menlo, monospace',
        lineHeight: 1.25,
        cursorBlink: true,
        scrollback: 3000,
        theme: pickTheme(),
      });
      const f = new fa.FitAddon();
      t.loadAddon(f);
      t.open(holderRef.current);
      term = t;

      t.onData((d) => {
        if (isTauriMode) {
          const id = termIdRef.current;
          if (id) writeTerminal(id, d);
        } else {
          const ws = wsRef.current;
          if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ d }));
        }
      });
      t.onResize(({ cols, rows }) => {
        if (isTauriMode) {
          const id = termIdRef.current;
          if (id) resizeTerminal(id, cols, rows);
        } else {
          const ws = wsRef.current;
          if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ r: [cols, rows] }));
        }
      });

      const setupTauri = async () => {
        f.fit();
        const id = await createTerminal(t.cols, t.rows);
        if (cancelled) {
          if (id) closeTerminal(id).catch(() => {});
          return;
        }
        termIdRef.current = id;
        const unlisten = await listenTerminalData((_, data) => t.write(data));
        if (cancelled) {
          unlisten();
          closeTerminal(id).catch(() => {});
          return;
        }
        unlistenRef.current = unlisten;
        termRef.current = t;
        fitRef.current = f;
        readyRef.current = true;
        t.focus();
      };

      const setupWeb = () => {
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;
        ws.onopen = () => {
          if (wsRef.current !== ws) return;
          f.fit();
          ws.send(JSON.stringify({ r: [t.cols, t.rows] }));
          termRef.current = t;
          fitRef.current = f;
          readyRef.current = true;
          t.focus();
        };
        ws.onmessage = (e) => t.write(e.data as string);
        ws.onclose = () => {
          t.write('\r\n\x1b[90m[终端已断开]\x1b[0m\r\n');
          readyRef.current = false;
        };
        ws.onerror = () => {
          readyRef.current = false;
        };
      };

      try {
        if (isTauriMode) {
          setupTauri();
        } else {
          setupWeb();
        }
      } catch (e) {
        t.dispose();
        throw e;
      }
    };
    void setup();

    return () => {
      cancelled = true;
      if (term && !readyRef.current) {
        // 会话尚未就绪就被隐藏/卸载，需要清理，否则下次 active 时 termRef 存在但会话已死。
        wsRef.current?.close();
        if (isTauriMode) {
          const id = termIdRef.current;
          if (id) closeTerminal(id).catch(() => {});
        }
        term.dispose();
        wsRef.current = null;
        termIdRef.current = null;
        fitRef.current = null;
        termRef.current = null;
      }
    };
  }, [active]);

  // 面板重新可见时 fit/focus。
  useEffect(() => {
    if (active && readyRef.current && fitRef.current && termRef.current) {
      const id = requestAnimationFrame(() => {
        fitRef.current?.fit();
        termRef.current?.focus();
      });
      return () => cancelAnimationFrame(id);
    }
  }, [active]);

  useEffect(() => {
    const onResize = () => active && fitRef.current?.fit();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [active]);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
      unlistenRef.current?.();
      if (termIdRef.current) {
        closeTerminal(termIdRef.current).catch(() => {});
      }
      termRef.current?.dispose();
      termRef.current = null;
      fitRef.current = null;
      wsRef.current = null;
      unlistenRef.current = null;
      termIdRef.current = null;
      readyRef.current = false;
    };
  }, []);

  return <div className={'term-holder' + (className ? ' ' + className : '')} ref={holderRef} />;
}
