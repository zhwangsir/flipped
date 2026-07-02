import { useApp } from '../store';
import type { ContextTab, SidebarTab } from '../types';
import {
  IconChat,
  IconFolder,
  IconSearch,
  IconGit,
  IconCube,
  IconBrowser,
  IconPuzzle,
  IconGear,
} from '../icons';

/** 每个入口都执行真实导航：切换左侧栏视图或右侧上下文面板 Tab。 */
const items: {
  key: string;
  label: string;
  Icon: typeof IconChat;
  sidebar?: SidebarTab;
  context?: ContextTab;
}[] = [
  { key: 'agent', label: '智能体', Icon: IconChat, sidebar: 'chats' },
  { key: 'explorer', label: '资源管理器', Icon: IconFolder, sidebar: 'files' },
  { key: 'search', label: '搜索会话', Icon: IconSearch, sidebar: 'chats' },
  { key: 'git', label: '源代码管理', Icon: IconGit, sidebar: 'files', context: 'diff' },
  { key: 'sandbox', label: '沙盒终端', Icon: IconCube, context: 'term' },
  { key: 'browser', label: '浏览器', Icon: IconBrowser, context: 'browser' },
  { key: 'mcp', label: 'MCP 工具', Icon: IconPuzzle, context: 'mcp' },
];

export function ActivityBar() {
  const { activeView, setActiveView, setSidebarTab, setContextTab } = useApp();

  const go = (item: (typeof items)[number]) => {
    setActiveView(item.key);
    if (item.sidebar) setSidebarTab(item.sidebar);
    if (item.context) setContextTab(item.context);
  };

  return (
    <nav className="rail">
      <div className="rail-mark">f</div>
      {items.map((item) => (
        <button
          key={item.key}
          className={'rail-btn' + (activeView === item.key ? ' active' : '')}
          onClick={() => go(item)}
          aria-label={item.label}
          title={item.label}
        >
          <item.Icon size={19} />
        </button>
      ))}
      <div className="rail-spacer" />
      <button
        className={'rail-btn' + (activeView === 'settings' ? ' active' : '')}
        onClick={() => setActiveView('settings')}
        aria-label="设置"
        title="设置"
      >
        <IconGear size={19} />
      </button>
      <div className="rail-avatar">王</div>
    </nav>
  );
}
