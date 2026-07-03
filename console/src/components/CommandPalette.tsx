import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useApp } from '../store';
import { useTheme } from '../hooks/useTheme';
import {
  IconSearch,
  IconChat,
  IconEdit,
  IconGear,
  IconSidebar,
  IconTerminal,
  IconBrowser,
  IconReview,
  IconLayout,
  IconSun,
  IconMoon,
  IconPuzzle,
  IconFile,
} from '../icons';

interface Row {
  id: string;
  section: string;
  label: string;
  icon: ReactNode;
  shortcut?: string;
  source?: string;
  run: () => void;
}

/** Codex 式命令面板：聊天(⌘1-9)+ 命令分组(推荐/面板/配置/切换项目),接真实动作。 */
export function CommandPalette() {
  const app = useApp();
  const { theme, toggle } = useTheme();
  const { paletteOpen, setPaletteOpen } = app;
  const [query, setQuery] = useState('');
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const activeRef = useRef<HTMLButtonElement>(null);
  const projectName = app.projectContext?.project || 'flipped';

  const rows = useMemo<Row[]>(() => {
    const close = () => setPaletteOpen(false);
    const list: Row[] = [];
    // 聊天
    app.sessions.forEach((s, i) => {
      list.push({
        id: 'chat-' + s.id,
        section: '聊天',
        label: s.title,
        icon: <IconChat size={15} />,
        shortcut: i < 9 ? '⌘' + (i + 1) : undefined,
        source: s.mode === 'chat' ? '对话' : projectName,
        run: () => { app.selectSession(s.id); close(); },
      });
    });
    // 推荐
    list.push({ id: 'new', section: '推荐', label: '新对话', icon: <IconEdit size={15} />, shortcut: '⌘N', run: () => { app.createSession('新对话'); close(); } });
    list.push({ id: 'searchfiles', section: '推荐', label: '搜索文件', icon: <IconSearch size={15} />, shortcut: '⌘P', run: () => { app.openContext('files'); close(); } });
    list.push({ id: 'settings', section: '推荐', label: '设置', icon: <IconGear size={15} />, shortcut: '⌘,', run: () => { app.setSettingsOpen(true); close(); } });
    // 面板
    list.push({ id: 'toggle-sb', section: '面板', label: '切换边栏', icon: <IconSidebar size={15} />, shortcut: '⌘B', run: () => { app.toggleSidebar(); close(); } });
    list.push({ id: 'toggle-term', section: '面板', label: '切换底部面板', icon: <IconTerminal size={15} />, shortcut: '⌘J', run: () => { app.toggleTerminal(); close(); } });
    list.push({ id: 'open-browser', section: '面板', label: '打开浏览器标签页', icon: <IconBrowser size={15} />, shortcut: '⌘T', run: () => { app.openContext('browser'); close(); } });
    list.push({ id: 'open-review', section: '面板', label: '打开审查选项卡', icon: <IconReview size={15} />, shortcut: '⌃⇧G', run: () => { app.openContext('diff'); close(); } });
    list.push({ id: 'open-files', section: '面板', label: '打开文件', icon: <IconFile size={15} />, run: () => { app.openContext('files'); close(); } });
    list.push({ id: 'toggle-ctx', section: '面板', label: '切换侧边面板', icon: <IconLayout size={15} />, shortcut: '⌥⌘B', run: () => { app.toggleContext(); close(); } });
    // 配置
    list.push({ id: 'theme', section: '配置', label: theme === 'dark' ? '切换到浅色主题' : '切换到深色主题', icon: theme === 'dark' ? <IconSun size={15} /> : <IconMoon size={15} />, run: () => { toggle(); close(); } });
    list.push({ id: 'mcp', section: '配置', label: 'MCP', icon: <IconPuzzle size={15} />, run: () => { app.openContext('mcp'); close(); } });
    list.push({ id: 'shortcuts', section: '配置', label: '键盘快捷方式', icon: <IconGear size={15} />, run: () => { app.setSettingsOpen(true); close(); } });
    // 切换项目
    list.push({ id: 'proj', section: '切换项目', label: projectName, icon: <IconFile size={15} />, run: () => close() });
    return list;
  }, [app, theme, toggle, setPaletteOpen, projectName]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? rows.filter((c) => c.label.toLowerCase().includes(q) || c.section.toLowerCase().includes(q)) : rows;
  }, [rows, query]);

  useEffect(() => {
    if (paletteOpen) {
      setQuery('');
      setSel(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [paletteOpen]);

  useEffect(() => { setSel(0); }, [query]);
  useEffect(() => { activeRef.current?.scrollIntoView({ block: 'nearest' }); }, [sel]);

  if (!paletteOpen) return null;

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setPaletteOpen(false);
    } else if ((e.metaKey || e.ctrlKey) && /^[1-9]$/.test(e.key)) {
      e.preventDefault();
      const s = app.sessions[Number(e.key) - 1];
      if (s) { app.selectSession(s.id); setPaletteOpen(false); }
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

  let lastSection = '';
  return (
    <div className="palette-overlay" onClick={() => setPaletteOpen(false)} data-testid="command-palette">
      <div className="palette" onClick={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <div className="palette-search">
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索聊天或运行命令"
            aria-label="命令面板"
          />
        </div>
        <div className="palette-list">
          {filtered.length === 0 && <div className="palette-empty">无匹配</div>}
          {filtered.map((c, i) => {
            const header = c.section !== lastSection ? c.section : null;
            lastSection = c.section;
            return (
              <div key={c.id}>
                {header && <div className="palette-section">{header}</div>}
                <button
                  ref={i === sel ? activeRef : undefined}
                  className={'palette-item' + (i === sel ? ' active' : '')}
                  onMouseMove={() => setSel(i)}
                  onClick={c.run}
                >
                  <span className="palette-ic">{c.icon}</span>
                  <span className="palette-label">{c.label}</span>
                  {c.source && <span className="palette-source">{c.source}</span>}
                  {c.shortcut && <kbd>{c.shortcut}</kbd>}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
