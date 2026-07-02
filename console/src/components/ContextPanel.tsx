import { useState, type ReactNode } from 'react';
import { useApp } from '../store';
import { diffLines, terminalLines, editorCode, mcpServers, problems } from '../mock';
import { IconCode, IconFile, IconTerminal, IconBrowser, IconWarn, IconPuzzle } from '../icons';

type Tab = 'editor' | 'diff' | 'term' | 'browser' | 'problems' | 'mcp';

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

const CHANGE_METHOD: Record<string, string> = { add: 'post', mod: 'get', modified: 'get', del: 'del', delete: 'del' };

export function ContextPanel() {
  const { terminalBlocks, browserView, changedFiles } = useApp();
  const [tab, setTab] = useState<Tab>('editor');
  const lines = editorCode.split('\n');

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
            <div className="file-head">
              <IconCode size={13} /> {hasFiles ? changedFiles[changedFiles.length - 1].path : 'app.py'} <span className="add">python</span>
            </div>
            <div className="editor">
              {lines.map((l, i) => (
                <div className="eln" key={i}>
                  <span className="gn">{i + 1}</span>
                  <span className="c">{highlight(l)}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {tab === 'diff' && (
          hasFiles ? (
            <>
              <div className="file-head">
                <IconFile size={13} /> 本次会话变更 <span className="add">{changedFiles.length} 个文件</span>
              </div>
              <div className="list">
                {changedFiles.map((f, i) => (
                  <div className="endpoint" key={i}>
                    <span className={'method ' + (CHANGE_METHOD[f.change] || 'get')}>{f.change}</span>
                    <span className="ep-path">{f.path}</span>
                    {f.language && <span className="chip" style={{ marginLeft: 'auto' }}>{f.language}</span>}
                  </div>
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
            {mcpServers.map((s, i) => (
              <div className="row-card" key={i}>
                <span className="lead"><IconPuzzle size={15} /></span>
                <div className="grow">
                  <div className="t1">{s.name}</div>
                  <div className="t2">{s.desc} · {s.tools} 工具</div>
                </div>
                <span className={'toggle' + (s.on ? ' on' : '')} />
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
