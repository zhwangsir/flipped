import { useState, type ReactNode } from 'react';
import { useApp } from '../store';
import { useTheme } from '../hooks/useTheme';
import {
  IconGear,
  IconSun,
  IconMoon,
  IconBolt,
  IconPuzzle,
  IconBrowser,
  IconGit,
  IconCode,
  IconChat,
  IconArchive,
  IconShield,
  IconCheck,
} from '../icons';

type NavId = 'general' | 'appearance' | 'config' | 'shortcuts' | 'mcp' | 'browser' | 'git' | 'archived';

const NAV: { group: string; items: { id: NavId; label: string; icon: ReactNode }[] }[] = [
  {
    group: '个人',
    items: [
      { id: 'general', label: '常规', icon: <IconGear size={15} /> },
      { id: 'appearance', label: '外观', icon: <IconSun size={15} /> },
      { id: 'config', label: '配置', icon: <IconBolt size={15} /> },
      { id: 'shortcuts', label: '键盘快捷键', icon: <IconCode size={15} /> },
    ],
  },
  {
    group: '集成',
    items: [
      { id: 'mcp', label: 'MCP 服务器', icon: <IconPuzzle size={15} /> },
      { id: 'browser', label: '浏览器', icon: <IconBrowser size={15} /> },
    ],
  },
  {
    group: '编码',
    items: [{ id: 'git', label: 'Git', icon: <IconGit size={15} /> }],
  },
  {
    group: '已归档',
    items: [{ id: 'archived', label: '已归档对话', icon: <IconArchive size={15} /> }],
  },
];

function readPref(key: string, fallback: string): string {
  try {
    return localStorage.getItem('flipped-set-' + key) ?? fallback;
  } catch {
    return fallback;
  }
}
function writePref(key: string, val: string) {
  try {
    localStorage.setItem('flipped-set-' + key, val);
  } catch {
    /* 隐私模式忽略 */
  }
}

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button className={'set-toggle' + (on ? ' on' : '')} onClick={() => onChange(!on)} aria-pressed={on}>
      <span className="set-toggle-knob" />
    </button>
  );
}

const SHORTCUTS: [string, string][] = [
  ['命令面板', '⌘K'],
  ['折叠 / 展开侧栏', '⌘B'],
  ['终端抽屉', '⌘J'],
  ['新对话', '⌘N'],
  ['搜索文件', '⌘P'],
  ['打开浏览器标签页', '⌘T'],
  ['打开审查选项卡', '⌃⇧G'],
  ['设置', '⌘,'],
];

export function Settings() {
  const { settingsOpen, setSettingsOpen, selectedModel, setModel, mcpServers, toggleMcpServer } = useApp();
  const { theme, toggle } = useTheme();
  const [nav, setNav] = useState<NavId>('general');
  const [workMode, setWorkMode] = useState(() => readPref('workmode', 'coding'));
  const [fileOpenTarget, setFileOpenTarget] = useState(() => readPref('file-open-target', 'editor'));
  const [language, setLanguage] = useState(() => readPref('language', 'auto'));
  const [perm, setPerm] = useState(() => ({
    def: readPref('perm-def', '1') === '1',
    auto: readPref('perm-auto', '1') === '1',
    full: readPref('perm-full', '1') === '1',
  }));
  const setPermKey = (k: 'def' | 'auto' | 'full', v: boolean) => {
    setPerm((p) => ({ ...p, [k]: v }));
    writePref('perm-' + k, v ? '1' : '0');
  };

  if (!settingsOpen) return null;

  return (
    <div className="settings-overlay" data-testid="settings">
      <aside className="settings-nav">
        <button className="settings-back" onClick={() => setSettingsOpen(false)}>
          ← 返回应用
        </button>
        {NAV.map((g) => (
          <div className="settings-navgroup" key={g.group}>
            <div className="settings-navlabel">{g.group}</div>
            {g.items.map((it) => (
              <button
                key={it.id}
                className={'settings-navitem' + (nav === it.id ? ' active' : '')}
                onClick={() => setNav(it.id)}
              >
                {it.icon} <span>{it.label}</span>
              </button>
            ))}
          </div>
        ))}
      </aside>

      <div className="settings-body">
        {nav === 'general' && (
          <>
            <h2 className="settings-title">常规</h2>
            <section className="settings-sec">
              <div className="settings-sec-h">工作模式</div>
              <div className="settings-sec-sub">选择 flipped 显示多少技术细节</div>
              <div className="set-cards">
                {[
                  ['coding', '适用于编程', '更具技术性的回复和控制', <IconCode size={16} />],
                  ['daily', '适用于日常工作', '同样强大，技术细节更少', <IconChat size={16} />],
                ].map(([id, t, d, ic]) => (
                  <button
                    key={id as string}
                    className={'set-card' + (workMode === id ? ' active' : '')}
                    onClick={() => { setWorkMode(id as string); writePref('workmode', id as string); }}
                  >
                    <span className="set-card-ic">{ic as ReactNode}</span>
                    <span className="set-card-text">
                      <b>{t as string}</b>
                      <span>{d as string}</span>
                    </span>
                    <span className={'set-radio' + (workMode === id ? ' on' : '')} />
                  </button>
                ))}
              </div>
            </section>

            <section className="settings-sec">
              <div className="settings-sec-h">权限</div>
              <div className="set-rows">
                {[
                  ['def', '默认权限', '默认情况下，flipped 可读取并编辑其工作区中的文件。必要时可请求额外访问权限。', perm.def],
                  ['auto', '自动审核', 'flipped 会自动审核额外访问权限请求。自动审核可能会出错。', perm.auto],
                  ['full', '完全访问权限', '无需批准即可编辑电脑上任何文件并运行联网命令。显著增加数据丢失/泄露风险。', perm.full],
                ].map(([k, t, d, v]) => (
                  <div className="set-row" key={k as string}>
                    <div className="set-row-text">
                      <b>{t as string}</b>
                      <span>{d as string}</span>
                    </div>
                    <Toggle on={v as boolean} onChange={(nv) => setPermKey(k as 'def' | 'auto' | 'full', nv)} />
                  </div>
                ))}
              </div>
            </section>

            <section className="settings-sec">
              <div className="settings-sec-h">常规</div>
              <div className="set-rows">
                <div className="set-row">
                  <div className="set-row-text"><b>默认文件打开目标</b><span>默认打开文件和文件夹的位置</span></div>
                  <select
                    className="set-select set-select-native"
                    value={fileOpenTarget}
                    onChange={(e) => {
                      setFileOpenTarget(e.target.value);
                      writePref('file-open-target', e.target.value);
                    }}
                  >
                    <option value="editor">编辑器</option>
                    <option value="preview">预览</option>
                    <option value="split">分屏</option>
                  </select>
                </div>
                <div className="set-row">
                  <div className="set-row-text"><b>语言</b><span>应用 UI 语言</span></div>
                  <select
                    className="set-select set-select-native"
                    value={language}
                    onChange={(e) => {
                      setLanguage(e.target.value);
                      writePref('language', e.target.value);
                    }}
                  >
                    <option value="auto">自动检测</option>
                    <option value="zh-CN">简体中文</option>
                    <option value="en">English</option>
                  </select>
                </div>
              </div>
            </section>
          </>
        )}

        {nav === 'appearance' && (
          <>
            <h2 className="settings-title">外观</h2>
            <section className="settings-sec">
              <div className="settings-sec-h">主题</div>
              <div className="set-cards">
                {[
                  ['light', '浅色', <IconSun size={16} />],
                  ['dark', '深色', <IconMoon size={16} />],
                ].map(([id, t, ic]) => (
                  <button
                    key={id as string}
                    className={'set-card' + (theme === id ? ' active' : '')}
                    onClick={() => { if (theme !== id) toggle(); }}
                  >
                    <span className="set-card-ic">{ic as ReactNode}</span>
                    <span className="set-card-text"><b>{t as string}</b></span>
                    <span className={'set-radio' + (theme === id ? ' on' : '')} />
                  </button>
                ))}
              </div>
            </section>
          </>
        )}

        {nav === 'config' && (
          <>
            <h2 className="settings-title">配置</h2>
            <section className="settings-sec">
              <div className="settings-sec-h">默认执行模型</div>
              <div className="settings-sec-sub">本地 exo 集群双模型</div>
              <div className="set-rows">
                {[
                  ['coder', 'Kimi-K2.7 · coder', '执行者 / 码农(子 Agent)'],
                  ['architect', 'GLM-5.2 · architect', '编排者 / 架构师(主 Agent)'],
                ].map(([id, t, d]) => (
                  <button
                    key={id}
                    className={'set-row set-row-btn' + (selectedModel === id ? ' active' : '')}
                    onClick={() => setModel(id)}
                  >
                    <span className="set-row-ic"><IconBolt size={15} /></span>
                    <div className="set-row-text"><b>{t}</b><span>{d}</span></div>
                    {selectedModel === id && <IconCheck size={16} />}
                  </button>
                ))}
              </div>
            </section>
          </>
        )}

        {nav === 'mcp' && (
          <>
            <h2 className="settings-title">MCP 服务器</h2>
            <section className="settings-sec">
              <div className="settings-sec-sub">连接外部工具与数据源(stdio / SSE)。启用需沙盒就绪。</div>
              <div className="set-rows">
                {mcpServers.length === 0 && <div className="settings-sec-sub">暂无 MCP 服务器</div>}
                {mcpServers.map((s) => (
                  <div className="set-row" key={s.name}>
                    <span className="set-row-ic"><IconPuzzle size={15} /></span>
                    <div className="set-row-text">
                      <b>{s.name} <span className="set-badge">{s.transport}</span></b>
                      <span>{s.description} · {s.tool_count} 工具</span>
                    </div>
                    <Toggle on={s.enabled} onChange={(v) => toggleMcpServer(s.name, v)} />
                  </div>
                ))}
              </div>
            </section>
          </>
        )}

        {nav === 'shortcuts' && (
          <>
            <h2 className="settings-title">键盘快捷键</h2>
            <section className="settings-sec">
              <div className="set-rows">
                {SHORTCUTS.map(([label, key]) => (
                  <div className="set-row" key={label}>
                    <div className="set-row-text"><b>{label}</b></div>
                    <kbd className="set-kbd">{key}</kbd>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}

        {nav === 'browser' && (
          <>
            <h2 className="settings-title">浏览器</h2>
            <section className="settings-sec">
              <div className="settings-sec-sub">
                内置真 Chromium 渲染(右侧「浏览器」)。用于实时预览构建结果 + 选中页面元素追踪给 agent。
              </div>
              <div className="set-row">
                <span className="set-row-ic"><IconShield size={15} /></span>
                <div className="set-row-text"><b>渲染引擎</b><span>Playwright / Chromium(本地缓存)</span></div>
                <span className="set-badge ok"><IconCheck size={11} /> 已启用</span>
              </div>
            </section>
          </>
        )}

        {nav === 'git' && (
          <>
            <h2 className="settings-title">Git</h2>
            <section className="settings-sec">
              <div className="settings-sec-sub">工作区 git 变更在右侧「审查」以真实 +/- diff 呈现。</div>
              <div className="set-row">
                <span className="set-row-ic"><IconGit size={15} /></span>
                <div className="set-row-text"><b>差异视图</b><span>git diff HEAD · Codex 配色</span></div>
                <span className="set-badge ok"><IconCheck size={11} /> 已启用</span>
              </div>
            </section>
          </>
        )}

        {nav === 'archived' && (
          <>
            <h2 className="settings-title">已归档对话</h2>
            <section className="settings-sec">
              <div className="settings-sec-sub">暂无已归档对话</div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
