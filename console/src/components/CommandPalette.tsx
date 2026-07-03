import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useApp } from '../store';
import { useTheme } from '../hooks/useTheme';
import type { ContextTab } from '../types';
import {
  IconSearch,
  IconPlus,
  IconSparkle,
  IconChat,
  IconLayout,
  IconBolt,
  IconCode,
  IconFile,
  IconTerminal,
  IconBrowser,
  IconWarn,
  IconPuzzle,
  IconSidebar,
  IconSun,
  IconMoon,
} from '../icons';

interface Cmd {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon: ReactNode;
  run: () => void;
}

const TABS: [ContextTab, string, ReactNode][] = [
  ['editor', '编辑器', <IconCode size={15} />],
  ['diff', '变更', <IconFile size={15} />],
  ['term', '终端', <IconTerminal size={15} />],
  ['browser', '浏览器', <IconBrowser size={15} />],
  ['problems', '问题', <IconWarn size={15} />],
  ['mcp', 'MCP', <IconPuzzle size={15} />],
];

export function CommandPalette() {
  const app = useApp();
  const { theme, toggle } = useTheme();
  const { paletteOpen, setPaletteOpen } = app;
  const [query, setQuery] = useState('');
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const activeRef = useRef<HTMLButtonElement>(null);

  const commands = useMemo<Cmd[]>(() => {
    const close = () => setPaletteOpen(false);
    const list: Cmd[] = [
      { id: 'new', group: '操作', label: '新对话', icon: <IconPlus size={15} />, run: () => { app.createSession('新对话'); close(); } },
      { id: 'mode-agent', group: '模式', label: '切换到 智能体', icon: <IconSparkle size={15} />, run: () => { app.setMode('agent'); close(); } },
      { id: 'mode-chat', group: '模式', label: '切换到 对话', icon: <IconChat size={15} />, run: () => { app.setMode('chat'); close(); } },
      { id: 'mode-plan', group: '模式', label: '切换到 规划', icon: <IconLayout size={15} />, run: () => { app.setMode('plan'); close(); } },
      { id: 'model-coder', group: '模型', label: '执行模型 · Kimi-K2.7 (coder)', icon: <IconBolt size={15} />, run: () => { app.setModel('coder'); close(); } },
      { id: 'model-arch', group: '模型', label: '执行模型 · GLM-5.2 (architect)', icon: <IconBolt size={15} />, run: () => { app.setModel('architect'); close(); } },
      ...TABS.map(([tab, label, icon]): Cmd => ({
        id: 'tab-' + tab, group: '面板', label: '打开 ' + label, icon, run: () => { app.setContextTab(tab); close(); },
      })),
      { id: 'toggle-ctx', group: '视图', label: '显示 / 隐藏 右侧面板', icon: <IconLayout size={15} />, run: () => { app.toggleContext(); close(); } },
      { id: 'toggle-sb', group: '视图', label: '折叠 / 展开 侧栏', hint: '⌘B', icon: <IconSidebar size={15} />, run: () => { app.toggleSidebar(); close(); } },
      { id: 'theme', group: '视图', label: theme === 'dark' ? '切换到 亮色主题' : '切换到 暗色主题', icon: theme === 'dark' ? <IconSun size={15} /> : <IconMoon size={15} />, run: () => { toggle(); close(); } },
      ...app.sessions.slice(0, 8).map((s): Cmd => ({
        id: 'sess-' + s.id, group: '会话', label: '打开 ' + s.title, icon: <IconChat size={15} />, run: () => { app.selectSession(s.id); close(); },
      })),
    ];
    return list;
  }, [app, theme, toggle, setPaletteOpen]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? commands.filter((c) => c.label.toLowerCase().includes(q)) : commands;
  }, [commands, query]);

  useEffect(() => {
    if (paletteOpen) {
      setQuery('');
      setSel(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [paletteOpen]);

  useEffect(() => {
    setSel(0);
  }, [query]);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'nearest' });
  }, [sel]);

  if (!paletteOpen) return null;

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setPaletteOpen(false);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      filtered[sel]?.run();
    }
  };

  return (
    <div className="palette-overlay" onClick={() => setPaletteOpen(false)} data-testid="command-palette">
      <div className="palette" onClick={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <div className="palette-search">
          <IconSearch size={16} />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入命令或搜索会话…"
            aria-label="命令面板"
          />
          <kbd>Esc</kbd>
        </div>
        <div className="palette-list">
          {filtered.length === 0 && <div className="palette-empty">无匹配命令</div>}
          {filtered.map((c, i) => (
            <button
              key={c.id}
              ref={i === sel ? activeRef : undefined}
              className={'palette-item' + (i === sel ? ' active' : '')}
              onMouseMove={() => setSel(i)}
              onClick={c.run}
            >
              <span className="palette-ic">{c.icon}</span>
              <span className="palette-label">{c.label}</span>
              <span className="palette-group">{c.group}</span>
              {c.hint && <kbd>{c.hint}</kbd>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
