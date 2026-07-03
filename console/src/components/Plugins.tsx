import { useState, type ReactNode } from 'react';
import { useApp } from '../store';
import {
  IconBrowser,
  IconTerminal,
  IconFolder,
  IconReview,
  IconSearch,
  IconPuzzle,
  IconBolt,
  IconFile,
  IconGit,
  IconChat,
  IconGear,
  IconX,
} from '../icons';

interface Cap {
  name: string;
  desc: string;
  icon: ReactNode;
  status: 'ready' | 'mcp' | 'soon';
  cat: 'featured' | 'productivity';
}

/** flipped 真实能力目录(接 Codex 插件页形态,不虚构不存在的工具)。 */
const CAPS: Cap[] = [
  { name: '浏览器', desc: '真 Chromium 渲染 + 选中页面元素追踪', icon: <IconBrowser size={22} />, status: 'ready', cat: 'featured' },
  { name: '终端', desc: '连接本机 pty 终端(⌘J 抽屉)', icon: <IconTerminal size={22} />, status: 'ready', cat: 'featured' },
  { name: '文件', desc: '项目文件树浏览 + 读取', icon: <IconFolder size={22} />, status: 'ready', cat: 'featured' },
  { name: '审查', desc: '工作区真实 git diff 审查', icon: <IconReview size={22} />, status: 'ready', cat: 'featured' },
  { name: '联网搜索', desc: 'SearXNG web_search(MCP)', icon: <IconSearch size={22} />, status: 'mcp', cat: 'productivity' },
  { name: 'RAG 知识库', desc: 'Chroma 向量检索本地文档(MCP)', icon: <IconPuzzle size={22} />, status: 'mcp', cat: 'productivity' },
  { name: 'Git', desc: '分支 / 提交 / diff(MCP)', icon: <IconGit size={22} />, status: 'mcp', cat: 'productivity' },
  { name: '电脑操控', desc: '控制 macOS 应用(cua-driver)', icon: <IconBolt size={22} />, status: 'soon', cat: 'productivity' },
  { name: 'Office 文档', desc: '生成 / 编辑 表格·演示·文档', icon: <IconFile size={22} />, status: 'soon', cat: 'productivity' },
];

export function Plugins() {
  const { pluginsOpen, setPluginsOpen, mcpServers, toggleMcpServer, prefillComposer } = useApp();
  const [tab, setTab] = useState<'plugins' | 'skills'>('plugins');
  const [q, setQ] = useState('');

  if (!pluginsOpen) return null;

  const query = q.trim().toLowerCase();
  const caps = query ? CAPS.filter((c) => c.name.toLowerCase().includes(query) || c.desc.toLowerCase().includes(query)) : CAPS;
  const featured = caps.filter((c) => c.cat === 'featured');
  const productivity = caps.filter((c) => c.cat === 'productivity');

  const tryInChat = (name: string) => {
    prefillComposer(`用「${name}」帮我 `);
    setPluginsOpen(false);
  };

  return (
    <div className="plugins-overlay" data-testid="plugins">
      <header className="plugins-head">
        <div className="plugins-tabs">
          <button className={'plugins-tab' + (tab === 'plugins' ? ' active' : '')} onClick={() => setTab('plugins')}>插件</button>
          <button className={'plugins-tab' + (tab === 'skills' ? ' active' : '')} onClick={() => setTab('skills')}>技能</button>
        </div>
        <span className="spacer" />
        <button className="icon-btn ghost" title="刷新"><IconSearch size={15} /></button>
        <button className="icon-btn ghost" title="设置"><IconGear size={15} /></button>
        <button className="icon-btn ghost" onClick={() => setPluginsOpen(false)} aria-label="关闭"><IconX size={16} /></button>
      </header>

      <div className="plugins-body">
        {tab === 'plugins' ? (
          <>
            <h1 className="plugins-title">插件</h1>
            <p className="plugins-sub">在你常用的工具中使用 flipped</p>
            <div className="plugins-search">
              <IconSearch size={15} />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索插件" aria-label="搜索插件" />
            </div>

            <div className="plugins-installed">
              <div className="plugins-sec-h">已安装</div>
              <div className="plugins-chips">
                {mcpServers.length === 0 && <span className="plugins-empty">暂无 MCP 服务器</span>}
                {mcpServers.map((s) => (
                  <button
                    key={s.name}
                    className={'plugins-chip' + (s.enabled ? ' on' : '')}
                    onClick={() => toggleMcpServer(s.name, !s.enabled)}
                    title={`${s.name} · ${s.tool_count} 工具 · 点击${s.enabled ? '停用' : '启用'}`}
                  >
                    <IconPuzzle size={18} />
                    <span>{s.name}</span>
                  </button>
                ))}
              </div>
            </div>

            {featured.length > 0 && (
              <section className="plugins-cat">
                <div className="plugins-cat-h">精选</div>
                <div className="plugins-grid">
                  {featured.map((c) => (
                    <PluginCard key={c.name} cap={c} onTry={tryInChat} />
                  ))}
                </div>
              </section>
            )}
            {productivity.length > 0 && (
              <section className="plugins-cat">
                <div className="plugins-cat-h">效率</div>
                <div className="plugins-grid">
                  {productivity.map((c) => (
                    <PluginCard key={c.name} cap={c} onTry={tryInChat} />
                  ))}
                </div>
              </section>
            )}
          </>
        ) : (
          <>
            <h1 className="plugins-title">技能</h1>
            <p className="plugins-sub">flipped 的多 Agent 编排角色(Supervisor / Worker / Overseer)</p>
            <div className="plugins-grid">
              {[
                ['Supervisor · GLM-5.2', '编排者 / 架构师,拆解需求与调度'],
                ['Worker · Kimi-K2.7', '执行者 / 码农,沙盒内改代码跑测'],
                ['Overseer · GLM-5.2', '监督者,评估效率与方向(强制验收)'],
              ].map(([t, d]) => (
                <div className="plugin-card" key={t}>
                  <span className="plugin-card-ic"><IconChat size={22} /></span>
                  <div className="plugin-card-text"><b>{t}</b><span>{d}</span></div>
                  <span className="plugin-status ready">内置</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function PluginCard({ cap, onTry }: { cap: Cap; onTry: (name: string) => void }) {
  return (
    <div className="plugin-card">
      <span className="plugin-card-ic">{cap.icon}</span>
      <div className="plugin-card-text">
        <b>{cap.name}</b>
        <span>{cap.desc}</span>
      </div>
      {cap.status === 'soon' ? (
        <span className="plugin-status soon">即将支持</span>
      ) : (
        <button className="plugin-try" onClick={() => onTry(cap.name)}>Try in chat</button>
      )}
    </div>
  );
}
