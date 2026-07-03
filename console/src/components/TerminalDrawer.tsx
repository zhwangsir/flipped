import { useEffect, useRef } from 'react';
import { Terminal, type ITheme } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { useApp } from '../store';
import { IconTerminal, IconX } from '../icons';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://127.0.0.1:8001';
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

/** Stage 5 — 真实 pty 终端抽屉（⌘J）。xterm.js ↔ 后端 WebSocket pty。 */
export function TerminalDrawer() {
  const { terminalOpen, toggleTerminal } = useApp();
  const holderRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // 首次打开时惰性创建 terminal + WS，之后保持存活（不销毁 → shell 状态不丢）
  useEffect(() => {
    if (!terminalOpen || termRef.current || !holderRef.current) return;
    const term = new Terminal({
      fontSize: 12.5,
      fontFamily: '"Geist Mono Variable", ui-monospace, "SF Mono", Menlo, monospace',
      lineHeight: 1.25,
      cursorBlink: true,
      scrollback: 3000,
      theme: pickTheme(),
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(holderRef.current);

    const ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      fit.fit();
      ws.send(JSON.stringify({ r: [term.cols, term.rows] }));
      term.focus();
    };
    ws.onmessage = (e) => term.write(e.data as string);
    ws.onclose = () => term.write('\r\n\x1b[90m[终端已断开]\x1b[0m\r\n');
    term.onData((d) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ d })));
    term.onResize(({ cols, rows }) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ r: [cols, rows] })));

    termRef.current = term;
    fitRef.current = fit;
    wsRef.current = ws;
  }, [terminalOpen]);

  // 打开时重新 fit + 聚焦
  useEffect(() => {
    if (terminalOpen && termRef.current && fitRef.current) {
      const id = requestAnimationFrame(() => {
        fitRef.current?.fit();
        termRef.current?.focus();
      });
      return () => cancelAnimationFrame(id);
    }
  }, [terminalOpen]);

  // 窗口尺寸变化时自适应
  useEffect(() => {
    const onResize = () => terminalOpen && fitRef.current?.fit();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [terminalOpen]);

  // 卸载时清理
  useEffect(
    () => () => {
      wsRef.current?.close();
      termRef.current?.dispose();
    },
    []
  );

  return (
    <div className={'term-drawer' + (terminalOpen ? ' open' : '')} aria-hidden={!terminalOpen}>
      <div className="term-drawer-head">
        <span className="term-drawer-title">
          <IconTerminal size={13} /> 终端 <span className="mono">pty · zsh</span>
        </span>
        <button className="term-drawer-close" onClick={toggleTerminal} aria-label="关闭终端 (⌘J)" title="关闭 (⌘J)">
          <IconX size={14} />
        </button>
      </div>
      <div className="term-holder" ref={holderRef} />
    </div>
  );
}
