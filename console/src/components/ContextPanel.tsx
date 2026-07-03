import { useState, useEffect, type ReactNode } from 'react';
import { useApp } from '../store';
import type { ChangedFile, FileNode, BrowserElement } from '../types';
import { terminalLines, editorCode, problems } from '../mock';
import { renderMarkdown } from '../lib/markdown';
import { IconCode, IconFile, IconFolder, IconTerminal, IconBrowser, IconWarn, IconPuzzle, IconChat, IconX, IconChevronDown, IconEye, IconCheck } from '../icons';

/** 递归文件树节点(阶段② — 右侧「文件」)。 */
function FileTreeNode({ node, depth, activePath, onOpen }: {
  node: FileNode;
  depth: number;
  activePath: string | null;
  onOpen: (p: string) => void;
}) {
  const [open, setOpen] = useState(depth < 1);
  const pad = 8 + depth * 12;
  if (node.type === 'dir') {
    return (
      <>
        <button className="ft-row ft-dir" style={{ paddingLeft: pad }} onClick={() => setOpen((o) => !o)}>
          <span className={'ft-chev' + (open ? ' open' : '')}><IconChevronDown size={11} /></span>
          <IconFolder size={13} />
          <span className="ft-name">{node.name}</span>
        </button>
        {open && node.children?.map((c) => (
          <FileTreeNode key={c.path} node={c} depth={depth + 1} activePath={activePath} onOpen={onOpen} />
        ))}
      </>
    );
  }
  return (
    <button
      className={'ft-row ft-file' + (activePath === node.path ? ' active' : '')}
      style={{ paddingLeft: pad + 16 }}
      onClick={() => onOpen(node.path)}
      title={node.path}
    >
      <IconFile size={12} />
      <span className="ft-name">{node.name}</span>
    </button>
  );
}

/** 浏览器真内核预览 + 选中元素追踪(阶段②b)。截图用真 Chromium 渲染，元素框百分比叠加(响应式)。 */
function BrowserTab() {
  const {
    browserRender,
    browserLoading,
    browserError,
    renderBrowser,
    browserView,
    prefillComposer,
  } = useApp();
  const [url, setUrl] = useState(browserRender?.url || browserView?.url || '');
  const [selected, setSelected] = useState<BrowserElement | null>(null);

  const go = () => {
    const u = url.trim();
    if (u && !browserLoading) {
      setSelected(null);
      renderBrowser(u);
    }
  };
  const vw = browserRender?.viewport.width || 1280;
  const vh = browserRender?.viewport.height || 800;
  const track = (el: BrowserElement) =>
    prefillComposer(`追踪页面元素 <${el.tag}> 「${el.text || el.selector}」（选择器 ${el.selector}）`);

  return (
    <div className="rbrowser">
      <div className="rbrowser-bar">
        <span className="traffic"><i /><i /><i /></span>
        <input
          className="rbrowser-url mono"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && go()}
          placeholder="http://localhost:5173"
          aria-label="预览地址"
        />
        <button className="rbrowser-go" onClick={go} disabled={browserLoading || !url.trim()}>
          {browserLoading ? '渲染中…' : '预览'}
        </button>
      </div>
      {browserError && <div className="rbrowser-err">渲染失败：{browserError}</div>}
      {!browserRender && !browserLoading && !browserError && (
        <div className="rbrowser-empty">
          <IconBrowser size={22} />
          <div>输入 URL 用真 Chromium 渲染</div>
          <div className="rbrowser-empty-sub">渲染后点击页面元素即可「追踪」给 agent</div>
        </div>
      )}
      {browserRender && (
        <>
          <div className="rbrowser-title mono">
            <IconEye size={12} /> {browserRender.title || browserRender.url}
            <span className="rbrowser-count">{browserRender.elements.length} 元素</span>
          </div>
          <div className="rbrowser-stage">
            <img src={browserRender.screenshot} alt={browserRender.title} />
            {browserRender.elements.map((el, i) => (
              <button
                key={i}
                type="button"
                className={'rbrowser-box' + (selected === el ? ' sel' : '')}
                style={{
                  left: `${(el.box.x / vw) * 100}%`,
                  top: `${(el.box.y / vh) * 100}%`,
                  width: `${(el.box.w / vw) * 100}%`,
                  height: `${(el.box.h / vh) * 100}%`,
                }}
                onClick={() => setSelected(el)}
                title={`<${el.tag}> ${el.text}`}
              />
            ))}
          </div>
          {selected && (
            <div className="rbrowser-sel">
              <div className="rbrowser-sel-info">
                <span className="rbrowser-tag mono">&lt;{selected.tag}&gt;</span>
                <span className="rbrowser-selname mono">{selected.selector}</span>
                {selected.text && <div className="rbrowser-seltext">{selected.text}</div>}
              </div>
              <button className="rbrowser-track" onClick={() => track(selected)}>
                追踪此元素
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** 工作区真实 git diff 审查视图(阶段②c)。无会话变更时展示 `git diff HEAD` 的真 +/- diff。 */
function GitDiffView() {
  const { gitDiff, gitDiffLoading, loadGitDiff } = useApp();
  useEffect(() => {
    loadGitDiff();
  }, [loadGitDiff]);

  if (gitDiffLoading && gitDiff.length === 0) {
    return <div className="side-empty">读取 git 变更…</div>;
  }
  if (gitDiff.length === 0) {
    return (
      <div className="rdiff-clean">
        <IconCheck size={18} /> 工作区无未提交变更 · 干净的树
      </div>
    );
  }
  return (
    <div className="rdiff">
      <div className="file-head">
        <IconFile size={13} /> 工作区 git 变更{' '}
        <span className="add">{gitDiff.length} 个文件</span>
        <button className="rdiff-refresh" onClick={() => loadGitDiff()} title="刷新">
          刷新
        </button>
      </div>
      {gitDiff.map((f) => (
        <div className="rdiff-file" key={f.path}>
          <div className="rdiff-fhead mono">
            <IconFile size={12} />
            <span className="rdiff-path">{f.path}</span>
            <span className="rdiff-stat">
              <span className="add">+{f.added}</span> <span className="del">−{f.removed}</span>
            </span>
          </div>
          <div className="rdiff-body">
            {f.lines.map((l, i) => (
              <div className={'rdiff-row ' + l.type} key={i}>
                <span className="rdiff-sign">
                  {l.type === 'add' ? '+' : l.type === 'del' ? '-' : l.type === 'hunk' ? '' : ' '}
                </span>
                <span className="rdiff-tx">{l.text}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

const KEYWORDS = new Set(['from', 'import', 'def', 'return', 'if', 'not', 'in', 'raise', 'class', 'for', 'while', 'with', 'as']);
const LITS = new Set(['None', 'True', 'False']);

function highlight(line: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\s+)|("(?:[^"\\]|\\.)*")|(@[A-Za-z_][\w.]*)|([A-Za-z_]\w*)|(\d+(?:\.\d+)?)|(#.*)|([^\sA-Za-z_0-9"#]+)/g;
  let m: RegExpExecArray | null;
  let key = 0;
  let prev = '';
  while ((m = re.exec(line)) !== null) {
    if (m[1]) out.push(m[1]);
    else if (m[2]) { out.push(<span key={key++} className="s">{m[2]}</span>); prev = ''; }
    else if (m[3]) { out.push(<span key={key++} className="de">{m[3]}</span>); prev = ''; }
    else if (m[4]) {
      const w = m[4];
      const cls = KEYWORDS.has(w) ? 'k' : LITS.has(w) ? 'n' : prev === 'def' ? 'f' : '';
      out.push(cls ? <span key={key++} className={cls}>{w}</span> : w);
      prev = w;
    } else if (m[5]) { out.push(<span key={key++} className="n">{m[5]}</span>); prev = ''; }
    else if (m[6]) { out.push(<span key={key++} className="cm">{m[6]}</span>); prev = ''; }
    else { out.push(m[0]); prev = ''; }
    if (m.index === re.lastIndex) re.lastIndex++;
  }
  return out;
}

const CHANGE_LABEL: Record<string, string> = { create: '新增', add: '新增', mod: '修改', modified: '修改', del: '删除', delete: '删除' };

/** Codex 式变更文件块：可折叠，内容按 diff 行渲染(新建文件=全绿新增)。 */
function DiffFile({ file }: { file: ChangedFile }) {
  const [open, setOpen] = useState(true);
  const name = file.path.split('/').pop() || file.path;
  const hasContent = typeof file.content === 'string' && file.content.length > 0;
  const lines = hasContent ? file.content!.replace(/\n$/, '').split('\n') : [];
  return (
    <div className="diff-file">
      <button className="diff-file-head" onClick={() => setOpen((o) => !o)} disabled={!hasContent}>
        <span className={'diff-file-chev' + (open ? ' open' : '')}>
          <IconChevronDown size={12} />
        </span>
        <IconFile size={13} />
        <span className="diff-file-name mono">{name}</span>
        <span className="diff-file-path mono">{file.path}</span>
        <span className="diff-file-badge">{CHANGE_LABEL[file.change] || file.change}</span>
        {hasContent && <span className="diff-file-stat">+{lines.length}</span>}
      </button>
      {open && hasContent && (
        <div className="diff-body">
          {lines.map((l, i) => (
            <div className="diff-row add" key={i}>
              <span className="ln">{i + 1}</span>
              <span className="tx">
                <span className="sign">+ </span>
                {l}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const EXT_LANG: Record<string, string> = {
  py: 'python', ts: 'typescript', tsx: 'tsx', js: 'javascript', jsx: 'jsx',
  json: 'json', md: 'markdown', css: 'css', html: 'html', sh: 'bash',
  go: 'go', rs: 'rust', yml: 'yaml', yaml: 'yaml', toml: 'toml', txt: 'text',
};
function langOf(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() || '';
  return EXT_LANG[ext] || 'text';
}

export function ContextPanel() {
  const {
    terminalBlocks,
    changedFiles,
    mcpServers,
    toggleMcpServer,
    contextTab: tab,
    setContextTab: setTab,
    showContext,
    prefillComposer,
    projectContext,
    projectFiles,
    openedFile,
    openFile,
  } = useApp();
  const [activePath, setActivePath] = useState<string | null>(null);
  const [commentLine, setCommentLine] = useState<number | null>(null);
  const [commentText, setCommentText] = useState('');
  // 面板隐藏时不渲染(改为右侧浮动启动器);文件/审查/浏览器等 surface 无需会话即可用
  if (!showContext) return null;

  // M7.2 — 编辑器展示真实沙盒文件内容（来自 file_editor 动作携带的 file_text）
  // 只认字符串内容，避免历史事件的非字符串 content 导致 .split 崩溃
  const realFiles = changedFiles.filter((f) => typeof f.content === 'string' && f.content.length > 0);
  const changedActive =
    realFiles.find((f) => f.path === activePath) || realFiles[realFiles.length - 1] || null;
  // 打开文件树里的文件优先(阶段②);否则回退到本次会话变更的文件
  const activeFile: { path: string; content: string; language?: string } | null = openedFile
    ? { path: openedFile.path, content: openedFile.content }
    : changedActive
    ? { path: changedActive.path, content: changedActive.content as string, language: changedActive.language }
    : null;
  const editorSource = typeof activeFile?.content === 'string' ? activeFile.content : editorCode;
  const editorLines = editorSource.split('\n');
  const editorLang = activeFile ? activeFile.language || langOf(activeFile.path) : 'python';
  const editorPath = activeFile ? activeFile.path : 'app.py';
  const crumbSegs = editorPath.split('/').filter(Boolean);
  const projectName = projectContext?.project || 'flipped';
  const fileLabel = crumbSegs[crumbSegs.length - 1] || editorPath;

  const submitComment = (ln: number) => {
    const c = commentText.trim();
    if (!c) return;
    prefillComposer(`关于 ${fileLabel}:${ln} — ${c}`);
    setCommentLine(null);
    setCommentText('');
  };

  const hasTerm = terminalBlocks.length > 0;
  const hasFiles = changedFiles.length > 0;
  const diffCount = hasFiles ? changedFiles.length : 14;

  return (
    <section className="context">
      <div className="tabs">
        <button className={'tab' + (tab === 'editor' ? ' active' : '')} onClick={() => setTab('editor')}>
          <IconCode size={14} /> 编辑器
        </button>
        <button className={'tab' + (tab === 'files' ? ' active' : '')} onClick={() => setTab('files')}>
          <IconFolder size={14} /> 文件
        </button>
        <button className={'tab' + (tab === 'diff' ? ' active' : '')} onClick={() => setTab('diff')}>
          <IconFile size={14} /> 变更 <span className="count">{diffCount}</span>
        </button>
        <button className={'tab' + (tab === 'term' ? ' active' : '')} onClick={() => setTab('term')}>
          <IconTerminal size={14} /> 终端
        </button>
        <button className={'tab' + (tab === 'browser' ? ' active' : '')} onClick={() => setTab('browser')}>
          <IconBrowser size={14} /> 浏览器
        </button>
        <button className={'tab' + (tab === 'problems' ? ' active' : '')} onClick={() => setTab('problems')}>
          <IconWarn size={14} /> 问题 <span className="count warn">{problems.length}</span>
        </button>
        <button className={'tab' + (tab === 'mcp' ? ' active' : '')} onClick={() => setTab('mcp')}>
          <IconPuzzle size={14} /> MCP
        </button>
      </div>

      <div className="panel-body">
        {tab === 'editor' && (
          <>
            {realFiles.length > 1 && (
              <div className="file-tabs">
                {realFiles.map((f) => (
                  <button
                    key={f.path}
                    className={'file-tab' + (activeFile?.path === f.path ? ' active' : '')}
                    onClick={() => setActivePath(f.path)}
                    title={f.path}
                  >
                    {f.path.split('/').pop()}
                  </button>
                ))}
              </div>
            )}
            <div className="file-head crumb-head">
              <IconCode size={13} />
              <nav className="crumbs" aria-label="文件路径">
                <span className="crumb-seg root">{projectName}</span>
                {crumbSegs.map((seg, i) => (
                  <span className="crumb-part" key={i}>
                    <span className="crumb-div">›</span>
                    <span className={'crumb-seg' + (i === crumbSegs.length - 1 ? ' leaf' : '')}>{seg}</span>
                  </span>
                ))}
              </nav>
              <span className="add crumb-lang">{editorLang}</span>
              {!activeFile && <span className="chip">示例预览</span>}
            </div>
            {activeFile && editorLang === 'markdown' ? (
              <div className="md-doc">{renderMarkdown(editorSource)}</div>
            ) : (
            <div className="editor">
              {editorLines.map((l, i) => {
                const ln = i + 1;
                return (
                  <div className="eln-wrap" key={i}>
                    <div className="eln">
                      <span className="gn">{ln}</span>
                      <span className="c">{highlight(l)}</span>
                      {activeFile && (
                        <button
                          className="eln-comment"
                          title={`对第 ${ln} 行评论`}
                          aria-label={`对第 ${ln} 行评论`}
                          onClick={() => {
                            setCommentLine(ln);
                            setCommentText('');
                          }}
                        >
                          <IconChat size={11} />
                        </button>
                      )}
                    </div>
                    {commentLine === ln && (
                      <div className="line-comment">
                        <div className="line-comment-ref">
                          {fileLabel}:{ln}
                        </div>
                        <textarea
                          value={commentText}
                          autoFocus
                          placeholder="写下对这行的意见，回车发给 flipped…"
                          onChange={(e) => setCommentText(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                              e.preventDefault();
                              submitComment(ln);
                            } else if (e.key === 'Escape') {
                              setCommentLine(null);
                            }
                          }}
                        />
                        <div className="line-comment-actions">
                          <button onClick={() => setCommentLine(null)}>
                            <IconX size={12} /> 取消
                          </button>
                          <button
                            className="primary"
                            disabled={!commentText.trim()}
                            onClick={() => submitComment(ln)}
                          >
                            发送到输入区
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            )}
          </>
        )}

        {tab === 'files' && (
          <div className="file-tree">
            {projectFiles.length === 0 ? (
              <div className="side-empty">加载文件树…</div>
            ) : (
              projectFiles.map((n) => (
                <FileTreeNode
                  key={n.path}
                  node={n}
                  depth={0}
                  activePath={openedFile?.path ?? null}
                  onOpen={openFile}
                />
              ))
            )}
          </div>
        )}

        {tab === 'diff' && (
          hasFiles ? (
            <>
              <div className="file-head">
                <IconFile size={13} /> 本次会话变更{' '}
                <span className="add">{changedFiles.length} 个文件</span>
              </div>
              <div className="diff-files">
                {changedFiles.map((f) => (
                  <DiffFile key={f.path} file={f} />
                ))}
              </div>
            </>
          ) : (
            <GitDiffView />
          )
        )}

        {tab === 'term' && (
          <div className="term">
            {hasTerm
              ? terminalBlocks.map((b, i) => (
                  <div key={i}>
                    <div className="cmd">$ {b.command}</div>
                    {b.output.split('\n').map((o, j) => (
                      <div key={j} className={o.includes('passed') || o.includes('200') || b.exit === 0 ? 'ok' : ''}>{o}</div>
                    ))}
                  </div>
                ))
              : terminalLines.map((l, i) => (
                  <div key={i} className={l.startsWith('$') ? 'cmd' : l.includes('passed') || l.includes('200') ? 'ok' : ''}>{l}</div>
                ))}
          </div>
        )}

        {tab === 'browser' && <BrowserTab />}

        {tab === 'problems' && (
          <div className="list">
            {problems.map((p, i) => (
              <div className="row-card" key={i}>
                <span className="lead warn"><IconWarn size={15} /></span>
                <div className="grow">
                  <div className="t1">{p.msg}</div>
                  <div className="t2">{p.file}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === 'mcp' && (
          <div className="list">
            {mcpServers.length === 0 && (
              <div className="row-card">
                <span className="lead"><IconPuzzle size={15} /></span>
                <div className="grow">
                  <div className="t1">暂无 MCP 服务器</div>
                  <div className="t2">检查后端 /mcp/servers</div>
                </div>
              </div>
            )}
            {mcpServers.map((s) => (
              <button
                type="button"
                className="row-card mcp-row"
                key={s.name}
                onClick={() => toggleMcpServer(s.name, !s.enabled)}
                title={s.enabled ? '点击停用' : '点击启用'}
              >
                <span className="lead"><IconPuzzle size={15} /></span>
                <div className="grow">
                  <div className="t1">{s.name} <span className="mcp-transport">{s.transport}</span></div>
                  <div className="t2">
                    {s.description} · {s.tool_count} 工具
                    {s.tools.length > 0 && <span className="mcp-tools"> · {s.tools.join(', ')}</span>}
                  </div>
                </div>
                <span className={'toggle' + (s.enabled ? ' on' : '')} />
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
