import { useState, type ReactNode } from 'react';
import { useApp } from '../store';
import type { ChangedFile } from '../types';
import { diffLines, terminalLines, editorCode, problems } from '../mock';
import { IconCode, IconFile, IconTerminal, IconBrowser, IconWarn, IconPuzzle, IconChat, IconX, IconChevronDown } from '../icons';

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
    browserView,
    changedFiles,
    mcpServers,
    toggleMcpServer,
    contextTab: tab,
    setContextTab: setTab,
    showContext,
    selectedSessionId,
    prefillComposer,
  } = useApp();
  const [activePath, setActivePath] = useState<string | null>(null);
  const [commentLine, setCommentLine] = useState<number | null>(null);
  const [commentText, setCommentText] = useState('');
  // 无活动会话(新线程)或手动折叠 → 不渲染右侧面板，聚焦中央
  if (!showContext || !selectedSessionId) return null;

  // M7.2 — 编辑器展示真实沙盒文件内容（来自 file_editor 动作携带的 file_text）
  // 只认字符串内容，避免历史事件的非字符串 content 导致 .split 崩溃
  const realFiles = changedFiles.filter((f) => typeof f.content === 'string' && f.content.length > 0);
  const activeFile =
    realFiles.find((f) => f.path === activePath) || realFiles[realFiles.length - 1] || null;
  const editorSource = typeof activeFile?.content === 'string' ? activeFile.content : editorCode;
  const editorLines = editorSource.split('\n');
  const editorLang = activeFile ? activeFile.language || langOf(activeFile.path) : 'python';
  const fileLabel = activeFile ? activeFile.path.split('/').pop() || activeFile.path : 'app.py';

  const submitComment = (ln: number) => {
    const c = commentText.trim();
    if (!c) return;
    prefillComposer(`关于 ${fileLabel}:${ln} — ${c}`);
    setCommentLine(null);
    setCommentText('');
  };

  const hasTerm = terminalBlocks.length > 0;
  const hasBrowser = browserView !== null;
  const hasFiles = changedFiles.length > 0;
  const diffCount = hasFiles ? changedFiles.length : 14;

  return (
    <section className="context">
      <div className="tabs">
        <button className={'tab' + (tab === 'editor' ? ' active' : '')} onClick={() => setTab('editor')}>
          <IconCode size={14} /> 编辑器
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
            <div className="file-head">
              <IconCode size={13} /> {activeFile ? activeFile.path : 'app.py'}{' '}
              <span className="add">{editorLang}</span>
              {!activeFile && <span className="chip" style={{ marginLeft: 'auto' }}>示例预览</span>}
            </div>
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
          </>
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
            <>
              <div className="file-head">
                <IconFile size={13} /> app.py <span className="add">+14 −0</span>
              </div>
              <div className="diff">
                {diffLines.map((l, i) => (
                  <div className={'diff-row ' + l.type} key={i}>
                    <span className="ln">{i + 1}</span>
                    <span className="tx">{l.type === 'add' && <span className="sign">+ </span>}{l.text}</span>
                  </div>
                ))}
              </div>
            </>
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

        {tab === 'browser' && (
          <div className="browser">
            <div className="browser-chrome">
              <div className="browser-bar">
                <span className="traffic"><i /><i /><i /></span>
                <span className="url">{hasBrowser ? browserView!.url : 'http://127.0.0.1:8000/docs'}</span>
              </div>
              <div className="browser-view">
                {hasBrowser ? (
                  <>
                    <div className="swagger-title">{browserView!.title || browserView!.url}</div>
                    {browserView!.screenshot ? (
                      <img
                        src={browserView!.screenshot}
                        alt={browserView!.title || 'screenshot'}
                        style={{ width: '100%', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', marginTop: 8 }}
                      />
                    ) : (
                      <div className="swagger-sub">已打开页面 · 无截图</div>
                    )}
                  </>
                ) : (
                  <>
                    <div className="swagger-title">Todo API</div>
                    <div className="swagger-sub">0.1.0 · OAS3 · /openapi.json</div>
                    <div className="endpoint"><span className="method get">GET</span><span className="ep-path">/todos</span></div>
                    <div className="endpoint"><span className="method post">POST</span><span className="ep-path">/todos</span></div>
                    <div className="endpoint"><span className="method del">DELETE</span><span className="ep-path">/todos/{'{todo_id}'}</span></div>
                  </>
                )}
              </div>
            </div>
          </div>
        )}

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
