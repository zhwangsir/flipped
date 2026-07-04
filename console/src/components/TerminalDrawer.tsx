import { useApp } from '../store';
import { IconTerminal, IconX } from '../icons';
import { PtyTerminal } from './PtyTerminal';

/** Stage 5 — 真实 pty 终端抽屉（⌘J）。pty 逻辑复用 PtyTerminal(与面板「终端」tab 同源）。 */
export function TerminalDrawer() {
  const { terminalOpen, toggleTerminal } = useApp();
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
      <PtyTerminal active={terminalOpen} />
    </div>
  );
}
