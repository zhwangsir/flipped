import { useState, useEffect, useRef, type ReactNode } from 'react';
import { useApp } from '../store';
import type { ChangedFile, FileNode, BrowserElement, GitDiffFile, GitDiffLine, ReviewFinding, CommitMessageResult } from '../types';
import { renderMarkdown } from '../lib/markdown';
import { splitDiffHunks } from '../lib/diffHunks';
import { isTauri, createBrowserWebview, updateBrowserWebview, closeBrowserWebview } from '../lib/native';
import { PtyTerminal } from './PtyTerminal';
import { ProjectMapPanel } from './ProjectMapPanel';
import { RulesPanel } from './RulesPanel';
import { IconFile, IconFolder, IconTerminal, IconBrowser, IconReview, IconChat, IconX, IconChevronDown, IconEye, IconCheck, IconMap, IconRefresh, IconSparkle, IconBot, IconWand, IconClock } from '../icons';
import { BotChannelPanel } from './BotChannelPanel';
import { WorkerRulesPanel } from './WorkerRulesPanel';
import { listModelAliases } from '../api';

/** M186.3 — 「仅变更」过滤:保留命中文件节点与祖先目录(目录无命中后代则剔除)。 */
export function filterTreeByPaths(tree: FileNode[], changedPaths: Set<string>): FileNode[] {
  const out: FileNode[] = [];
  for (const node of tree) {
    if (node.type === 'dir') {
      const children = filterTreeByPaths(node.children ?? [], changedPaths);
      if (children.length > 0) out.push({ ...node, children });
    } else if (changedPaths.has(node.path)) {
      out.push(node);
    }
  }
  return out;
}

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
        <button className="ft-row ft-dir" style={{ paddingLeft: pad }} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
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
    detectedServerUrl,
  } = useApp();
  const [url, setUrl] = useState(browserRender?.url || browserView?.url || '');
  const [selected, setSelected] = useState<BrowserElement | null>(null);
  // 实时 iframe(可交互, 首要场景=预览自己的 dev server) vs 截图(元素追踪 / 外部站点)
  const [view, setView] = useState<'live' | 'shot'>('live');
  const [liveUrl, setLiveUrl] = useState('');
  const hostRef = useRef<HTMLDivElement | null>(null);

  const norm = (u: string) => (/^https?:\/\//.test(u) ? u : 'http://' + u.replace(/^\/+/, ''));

  // Tauri desktop: replace the live iframe with a real Chromium child webview overlaid on the host div.
  useEffect(() => {
    if (!isTauri() || view !== 'live' || !liveUrl) return;
    const host = hostRef.current;
    if (!host) return;
    const rect = host.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;
    createBrowserWebview('browser-preview', norm(liveUrl), rect.left, rect.top, rect.width, rect.height);

    const update = () => {
      const r = host.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        updateBrowserWebview('browser-preview', r.left, r.top, r.width, r.height);
      }
    };
    const observer = new ResizeObserver(update);
    observer.observe(host);

    return () => {
      observer.disconnect();
      closeBrowserWebview('browser-preview').catch(() => {});
    };
  }, [liveUrl, view]);
  const goLive = () => {
    const u = url.trim();
    if (u) {
      setView('live');
      setLiveUrl(norm(u));
    }
  };
  const goShot = () => {
    const u = url.trim();
    if (u && !browserLoading) {
      setView('shot');
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
          onKeyDown={(e) => e.key === 'Enter' && goLive()}
          placeholder="http://localhost:5173"
          aria-label="预览地址"
        />
        <button className="rbrowser-go" onClick={goLive} disabled={!url.trim()} title="实时可交互预览(适合本地 dev server)">
          实时
        </button>
        <button className="rbrowser-go ghost" onClick={goShot} disabled={browserLoading || !url.trim()} title="截图+可点选元素追踪给 agent(适合外部站点)">
          {browserLoading ? '渲染…' : '截图'}
        </button>
      </div>
      {detectedServerUrl && detectedServerUrl !== liveUrl && (
        <button
          className="rbrowser-detected"
          data-testid="detected-server"
          onClick={() => {
            setUrl(detectedServerUrl);
            setView('live');
            setLiveUrl(detectedServerUrl);
          }}
          title="agent 终端里检测到本地服务,点击实时预览"
        >
          <IconEye size={12} /> 检测到本地服务 <span className="mono">{detectedServerUrl}</span> · 预览
        </button>
      )}
      {view === 'live' ? (
        liveUrl ? (
          isTauri() ? (
            <div ref={hostRef} className="rbrowser-live-host" style={{ flex: 1, minHeight: 0 }} />
          ) : (
            <iframe
              className="rbrowser-live"
              src={liveUrl}
              title="实时预览"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
            />
          )
        ) : (
          <div className="rbrowser-empty">
            <IconBrowser size={22} />
            <div>输入本地 dev server 地址,实时可交互预览</div>
            <div className="rbrowser-empty-sub">如 http://localhost:5173 · 外部站点可用「截图」追踪元素</div>
          </div>
        )
      ) : (
        <>
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
        </>
      )}
    </div>
  );
}

/** M179.2 — AI 评审单条 finding:severity 徽标 + message(:行号) + 建议次级行(只读展示)。 */
const REVIEW_SEVERITY_LABEL: Record<ReviewFinding['severity'], string> = { high: '高', medium: '中', low: '低' };

function ReviewFindingRow({ finding, showPath = false }: { finding: ReviewFinding; showPath?: boolean }) {
  const { openFile } = useApp();
  const body = (
    <>
      <div className="review-finding-main">
        <span className={`review-badge ${finding.severity}`}>
          {REVIEW_SEVERITY_LABEL[finding.severity] ?? finding.severity}
        </span>
        {showPath && <span className="review-path">{finding.path}</span>}
        <span className="review-msg">
          {finding.message}
          {finding.line != null && <span className="review-line">:{finding.line}</span>}
        </span>
      </div>
      {finding.suggestion && <div className="review-suggestion">建议:{finding.suggestion}</div>}
    </>
  );
  // M186.2 — 有行号的 finding 整行可点:跳到文件并高亮目标行;无行号保持只读 div
  if (finding.line != null) {
    return (
      <button
        type="button"
        className="review-finding review-jump"
        title={`跳转到 ${finding.path}:${finding.line}`}
        onClick={() => openFile(finding.path, finding.line!)}
      >
        {body}
      </button>
    );
  }
  return <div className="review-finding">{body}</div>;
}

/** M194.5 — AI commit message 可编辑块:textarea 初值=生成文本,复制按钮复制编辑后文本;
 * 由调用处 key={result.message} 保证重新生成时重置初值。 */
function CommitMessageBlock({ result }: { result: CommitMessageResult }) {
  const [text, setText] = useState(result.message);
  return (
    <div className="commit-msg">
      <IconWand size={12} />
      <textarea
        className="commit-msg-edit"
        title="提交信息(可编辑)"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
      />
      <span className="commit-msg-meta">
        {result.model} · {result.files_count} 个文件
      </span>
      <button
        className="review-clear"
        onClick={() => navigator.clipboard?.writeText(text)}
        title="复制提交信息"
      >
        复制
      </button>
    </div>
  );
}

/** diff 单行渲染(add/del/ctx/hunk 符号 + 文本)。M193.2 抽出供 prelude 与 hunk 块复用。 */
function DiffLineRow({ l }: { l: GitDiffLine }) {
  return (
    <div className={'rdiff-row ' + l.type}>
      <span className="rdiff-sign">
        {l.type === 'add' ? '+' : l.type === 'del' ? '-' : l.type === 'hunk' ? '' : ' '}
      </span>
      <span className="rdiff-tx">{l.text}</span>
    </div>
  );
}

/** 工作区真实 git diff 审查视图(阶段②c)。无会话变更时展示 `git diff HEAD` 的真 +/- diff。 */
function GitDiffView() {
  const { gitDiff, gitDiffLoading, loadGitDiff, revertGitDiffFile, revertGitDiffHunk, aiReview, runAiReview, clearAiReview, reviewHistory, reviewHistoryLoading, loadReviewHistory, openReview, commitMessage, generateCommit } = useApp();
  // M177.2 — 逐文件撤销:确认态/进行中/错误均组件本地管理,同一时刻只允许一个卡处于确认态
  const [confirmingPath, setConfirmingPath] = useState<string | null>(null);
  const [revertingPath, setRevertingPath] = useState<string | null>(null);
  const [revertError, setRevertError] = useState<{ path: string; message: string } | null>(null);
  // M193.2 — 逐 hunk 接受/拒绝:接受=纯前端审查进度标记(按内容指纹 key 记忆,无 git 副作用);
  // 拒绝=真实工作区操作(内联确认态 key=`${path}#${hunkIndex}`,同文件级单卡互斥哲学)
  const [acceptedHunks, setAcceptedHunks] = useState<Set<string>>(new Set());
  const [confirmingHunk, setConfirmingHunk] = useState<string | null>(null);
  const [revertingHunk, setRevertingHunk] = useState<string | null>(null);
  const [hunkError, setHunkError] = useState<{ key: string; message: string } | null>(null);
  // M186.1 — 评审历史下拉(展开时拉取一次列表)
  const [historyOpen, setHistoryOpen] = useState(false);
  // M194.4 — 评审模型选择('' = 默认 coder,不发 model 字段;'architect' 显式传参)
  const [reviewModel, setReviewModel] = useState('');
  // M195.3 — 评审模型下拉动态化(消化 L-M194-2):挂载时拉 GET /models/aliases,
  // 失败回落 M194.4 硬编码 ['architect'] 保持现状行为
  const [modelAliases, setModelAliases] = useState<string[]>(['architect']);
  useEffect(() => {
    let alive = true;
    listModelAliases()
      .then((d) => {
        if (!alive) return;
        const aliases = (d.aliases || []).map((a) => a.alias).filter(Boolean);
        if (aliases.length > 0) setModelAliases(aliases);
      })
      .catch(() => { /* 回落硬编码,保持现状 */ });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    loadGitDiff();
  }, [loadGitDiff]);

  const doRevert = async (f: GitDiffFile) => {
    setRevertingPath(f.path);
    setRevertError(null);
    try {
      await revertGitDiffFile(f.path);
      setConfirmingPath(null);
    } catch (e) {
      setRevertError({ path: f.path, message: e instanceof Error ? e.message : String(e) });
    } finally {
      setRevertingPath(null);
    }
  };

  // M193.2 — 接受/撤销接受:无副作用无确认,仅按内容指纹 key 切换组件内存标记
  const toggleAcceptHunk = (key: string) => {
    setAcceptedHunks((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // M193.2 — 拒绝 hunk:确认后调 store(内部刷新 diff);409 漂移等错误内联展示
  const doRevertHunk = async (f: GitDiffFile, hunkIndex: number, hunkKey: string) => {
    const id = `${f.path}#${hunkIndex}`;
    setRevertingHunk(id);
    setHunkError(null);
    try {
      await revertGitDiffHunk(f.path, hunkIndex);
      setConfirmingHunk(null);
      // 防御:该 hunk 已消失,顺带清掉可能残留的接受标记(内容变了 key 本也会自然失配)
      setAcceptedHunks((prev) => {
        if (!prev.has(hunkKey)) return prev;
        const next = new Set(prev);
        next.delete(hunkKey);
        return next;
      });
    } catch (e) {
      setHunkError({ key: id, message: e instanceof Error ? e.message : String(e) });
    } finally {
      setRevertingHunk(null);
    }
  };

  // M179.2 — findings 按 path 分组;不在当前 diff 的 path 归到底部「其他文件」
  const reviewResult = aiReview.result;
  const findingsByPath = new Map<string, ReviewFinding[]>();
  if (reviewResult) {
    for (const fd of reviewResult.findings) {
      const arr = findingsByPath.get(fd.path);
      if (arr) arr.push(fd);
      else findingsByPath.set(fd.path, [fd]);
    }
  }
  const otherFindings = [...findingsByPath.entries()].filter(
    ([p]) => !gitDiff.some((f) => f.path === p)
  );

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
        {/* M194.4 — 评审模型选择:默认 '' 不传 model(后端 coder),非默认显式传参;
            M195.3 — 选项动态化(挂载拉 /models/aliases,失败回落 architect) */}
        <select
          className="rdiff-model"
          title="评审模型"
          value={reviewModel}
          onChange={(e) => setReviewModel(e.target.value)}
        >
          <option value="">默认 · coder</option>
          {modelAliases.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        <button
          className="rdiff-refresh rdiff-review-btn"
          onClick={() => runAiReview(reviewModel || undefined)}
          disabled={aiReview.loading}
          title="AI 评审"
        >
          <IconSparkle size={12} /> {aiReview.loading ? '评审中…' : 'AI 评审'}
        </button>
        <button
          className="rdiff-refresh rdiff-review-btn"
          onClick={() => {
            const next = !historyOpen;
            setHistoryOpen(next);
            if (next) loadReviewHistory();
          }}
          title="评审历史"
        >
          <IconClock size={12} /> 历史
        </button>
        <button
          className="rdiff-refresh rdiff-review-btn"
          onClick={() => generateCommit()}
          disabled={commitMessage.loading}
          title="AI 生成提交信息"
        >
          <IconWand size={12} /> {commitMessage.loading ? '生成中…' : '提交信息'}
        </button>
      </div>
      {historyOpen && (
        <div className="review-history">
          {reviewHistoryLoading ? (
            <div className="review-history-empty">载入历史…</div>
          ) : reviewHistory.length === 0 ? (
            <div className="review-history-empty">暂无历史评审</div>
          ) : (
            reviewHistory.map((r) => (
              <button
                key={r.id}
                type="button"
                className="review-history-row"
                title={`回放 ${r.ts} 的评审`}
                onClick={() => {
                  openReview(r.id);
                  setHistoryOpen(false);
                }}
              >
                <span className="review-history-ts mono">{r.ts.replace('T', ' ').slice(0, 16)}</span>
                <span className="review-history-meta">
                  {r.model} · {r.findings_count} 条建议 · {r.files_reviewed} 文件
                </span>
              </button>
            ))
          )}
        </div>
      )}
      {aiReview.error && <div className="review-error">AI 评审失败:{aiReview.error}</div>}
      {reviewResult && (
        <div className="review-summary">
          <IconSparkle size={12} />
          {reviewResult.historical && <span className="review-hist-badge">历史</span>}
          <span>
            {reviewResult.findings.length} 条建议 · 评审了 {reviewResult.files_reviewed} 个文件 · {reviewResult.model}
          </span>
          {reviewResult.note && <span className="review-note">{reviewResult.note}</span>}
          <button className="review-clear" onClick={() => clearAiReview()} title="清除评审结果">
            清除
          </button>
        </div>
      )}
      {commitMessage.error && <div className="review-error commit-error">生成提交信息失败:{commitMessage.error}</div>}
      {commitMessage.result && (
        <CommitMessageBlock key={commitMessage.result.message} result={commitMessage.result} />
      )}
      {gitDiff.map((f) => {
        // M193.2 — 按 hunk 分组(空 lines 时结果为空,走现状空态分支)
        const blocks = splitDiffHunks(f.path, f.lines);
        return (
        <div className="rdiff-file" key={f.path}>
          <div className="rdiff-fhead mono">
            <IconFile size={12} />
            <span className="rdiff-path">{f.path}</span>
            {f.untracked && <span className="rdiff-badge new">新增</span>}
            {f.binary && <span className="rdiff-badge bin">二进制</span>}
            <span className="rdiff-stat">
              <span className="add">+{f.added}</span> <span className="del">−{f.removed}</span>
            </span>
            {confirmingPath === f.path ? (
              <span className="rdiff-confirm">
                <span className="rdiff-confirm-text">{f.untracked ? '删除该新文件？' : '还原到 HEAD？'}</span>
                <button
                  className="rdiff-confirm-danger"
                  disabled={revertingPath === f.path}
                  onClick={() => doRevert(f)}
                >
                  确认
                </button>
                <button
                  className="rdiff-revert"
                  disabled={revertingPath === f.path}
                  onClick={() => {
                    setConfirmingPath(null);
                    setRevertError(null);
                  }}
                >
                  取消
                </button>
              </span>
            ) : (
              <button
                className="rdiff-revert"
                title="撤销该文件变更"
                onClick={() => {
                  setConfirmingPath(f.path);
                  setRevertError(null);
                }}
              >
                <IconRefresh size={12} />
              </button>
            )}
          </div>
          {revertError && revertError.path === f.path && (
            <div className="rdiff-revert-error">{revertError.message}</div>
          )}
          <div className="rdiff-body">
            {(findingsByPath.get(f.path) ?? []).map((fd, i) => (
              <ReviewFindingRow key={i} finding={fd} />
            ))}
            {f.lines.length === 0 ? (
              <div className="rdiff-row empty">
                <span className="rdiff-sign" />
                <span className="rdiff-tx">
                  {f.untracked ? '新文件 · 撤销将删除该文件' : f.binary ? '二进制文件不显示 diff' : '无 diff 内容'}
                </span>
              </div>
            ) : (
              <>
                {blocks.prelude.map((l, i) => (
                  <DiffLineRow key={'p' + i} l={l} />
                ))}
                {blocks.hunks.map((h, hi) => {
                  const hunkId = `${f.path}#${hi}`;
                  const accepted = acceptedHunks.has(h.key);
                  return (
                    <div className={'rdiff-hunk' + (accepted ? ' accepted' : '')} key={h.key}>
                      <div className="rdiff-hunk-head mono">
                        <span className="rdiff-hunk-range">{h.header}</span>
                        {accepted ? (
                          <button
                            className="rdiff-hunk-btn accepted-toggle"
                            title="撤销接受"
                            onClick={() => toggleAcceptHunk(h.key)}
                          >
                            <IconCheck size={11} /> 已接受
                          </button>
                        ) : confirmingHunk === hunkId ? (
                          <span className="rdiff-confirm">
                            <span className="rdiff-confirm-text">撤销该 hunk 改动？</span>
                            <button
                              className="rdiff-confirm-danger"
                              disabled={revertingHunk === hunkId}
                              onClick={() => doRevertHunk(f, hi, h.key)}
                            >
                              确认
                            </button>
                            <button
                              className="rdiff-hunk-btn"
                              disabled={revertingHunk === hunkId}
                              onClick={() => {
                                setConfirmingHunk(null);
                                setHunkError(null);
                              }}
                            >
                              取消
                            </button>
                          </span>
                        ) : (
                          <span className="rdiff-hunk-actions">
                            <button
                              className="rdiff-hunk-btn accept"
                              title="接受该 hunk（保留改动）"
                              disabled={revertingHunk === hunkId}
                              onClick={() => toggleAcceptHunk(h.key)}
                            >
                              <IconCheck size={12} />
                            </button>
                            <button
                              className="rdiff-hunk-btn reject"
                              title="拒绝该 hunk（撤销改动回 HEAD）"
                              disabled={revertingHunk === hunkId}
                              onClick={() => {
                                setConfirmingHunk(hunkId);
                                setHunkError(null);
                              }}
                            >
                              <IconX size={12} />
                            </button>
                          </span>
                        )}
                      </div>
                      {h.lines.map((l, i) => (
                        <DiffLineRow key={i} l={l} />
                      ))}
                      {hunkError && hunkError.key === hunkId && (
                        <div className="rdiff-revert-error">{hunkError.message}</div>
                      )}
                    </div>
                  );
                })}
              </>
            )}
          </div>
        </div>
        );
      })}
      {otherFindings.length > 0 && (
        <div className="rdiff-file review-other">
          <div className="rdiff-fhead mono">
            <IconFile size={12} />
            <span className="rdiff-path">其他文件</span>
          </div>
          <div className="rdiff-body">
            {otherFindings.map(([path, list]) =>
              list.map((fd, i) => <ReviewFindingRow key={`${path}-${i}`} finding={fd} showPath />)
            )}
          </div>
        </div>
      )}
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
    changedFiles,
    contextTab: tab,
    setContextTab: setTab,
    showContext,
    prefillComposer,
    projectContext,
    projectFiles,
    openedFile,
    openFile,
    closeFile,
    gitDiff,
  } = useApp();
  const [commentLine, setCommentLine] = useState<number | null>(null);
  const [commentText, setCommentText] = useState('');
  // M186.3 — 文件树「仅变更」过滤开关(默认关)
  const [changedOnly, setChangedOnly] = useState(false);

  // M186.2 — findings 跳转目标行:打开文件后把目标行滚动到视口中央(高亮 class 在渲染处加)
  const jumpLine = openedFile?.line ?? null;
  const jumpPath = openedFile?.path ?? null;
  useEffect(() => {
    if (jumpLine == null) return;
    document.querySelector('.eln-wrap.line-target')?.scrollIntoView({ block: 'center' });
  }, [jumpLine, jumpPath]);

  // 面板隐藏时不渲染(改为右侧浮动启动器);文件/审查/浏览器等 surface 无需会话即可用
  if (!showContext) return null;

  // 「文件」tab 打开的文件 → 编辑器视图(来自文件树/@/会话变更)
  const editorSource = openedFile?.content ?? '';
  const editorLines = editorSource.split('\n');
  // M186.2 — 跳转目标行仅在有效范围内(1..行数)才高亮
  const editorTargetLine =
    jumpLine != null && jumpLine >= 1 && jumpLine <= editorLines.length ? jumpLine : null;
  const editorPath = openedFile?.path ?? '';
  const editorLang = openedFile ? langOf(editorPath) : 'text';
  const crumbSegs = editorPath.split('/').filter(Boolean);
  const projectName = projectContext?.project || '项目';
  const fileLabel = crumbSegs[crumbSegs.length - 1] || editorPath;

  const submitComment = (ln: number) => {
    const c = commentText.trim();
    if (!c) return;
    prefillComposer(`关于 ${fileLabel}:${ln} — ${c}`);
    setCommentLine(null);
    setCommentText('');
  };

  const hasFiles = changedFiles.length > 0;

  // M186.3 — 「仅变更」开启时用 gitDiff 路径集过滤文件树(保留祖先目录)
  const visibleFiles = changedOnly
    ? filterTreeByPaths(projectFiles, new Set(gitDiff.map((f) => f.path)))
    : projectFiles;

  return (
    <section className="context">
      {/* 面板 tab 与右侧启动器保持一致:审查 / 终端 / 浏览器 / 文件 */}
      <div className="tabs">
        <button className={'tab' + (tab === 'diff' ? ' active' : '')} onClick={() => setTab('diff')}>
          <IconReview size={14} /> 审查
        </button>
        <button className={'tab' + (tab === 'term' ? ' active' : '')} onClick={() => setTab('term')}>
          <IconTerminal size={14} /> 终端
        </button>
        <button className={'tab' + (tab === 'browser' ? ' active' : '')} onClick={() => setTab('browser')}>
          <IconBrowser size={14} /> 浏览器
        </button>
        <button className={'tab' + (tab === 'files' ? ' active' : '')} onClick={() => setTab('files')}>
          <IconFolder size={14} /> 文件
        </button>
        <button className={'tab' + (tab === 'map' ? ' active' : '')} onClick={() => setTab('map')}>
          <IconMap size={14} /> 地图
        </button>
        <button className={'tab' + (tab === 'rules' ? ' active' : '')} onClick={() => setTab('rules')}>
          <IconFile size={14} /> 规则
        </button>
        <button className={'tab' + (tab === 'bot' ? ' active' : '')} onClick={() => setTab('bot')}>
          <IconBot size={14} /> Bot
        </button>
        <button className={'tab' + (tab === 'worker' ? ' active' : '')} onClick={() => setTab('worker')}>
          <IconWand size={14} /> Worker
        </button>
      </div>

      <div className="panel-body">
        {tab === 'files' && (
          openedFile ? (
            <>
              <div className="file-head crumb-head">
                <button className="crumb-back" onClick={() => closeFile()} title="返回文件树">
                  <IconChevronDown size={13} /> 文件
                </button>
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
              </div>
              {editorLang === 'markdown' ? (
                <div className="md-doc">{renderMarkdown(editorSource)}</div>
              ) : (
                <div className="editor">
                  {editorLines.map((l, i) => {
                    const ln = i + 1;
                    return (
                      <div className={'eln-wrap' + (ln === editorTargetLine ? ' line-target' : '')} key={i}>
                        <div className="eln">
                          <span className="gn">{ln}</span>
                          <span className="c">{highlight(l)}</span>
                          <button
                            className="eln-comment"
                            title={`对第 ${ln} 行评论`}
                            aria-label={`对第 ${ln} 行评论`}
                            onClick={() => { setCommentLine(ln); setCommentText(''); }}
                          >
                            <IconChat size={11} />
                          </button>
                        </div>
                        {commentLine === ln && (
                          <div className="line-comment" role="dialog" aria-label={`第 ${ln} 行评论`}>
                            <div className="line-comment-ref">{fileLabel}:{ln}</div>
                            <textarea
                              value={commentText}
                              autoFocus
                              placeholder="写下对这行的意见，回车发给 flipped…"
                              onChange={(e) => setCommentText(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitComment(ln); }
                                else if (e.key === 'Escape') { setCommentLine(null); }
                              }}
                            />
                            <div className="line-comment-actions">
                              <button onClick={() => setCommentLine(null)}><IconX size={12} /> 取消</button>
                              <button className="primary" disabled={!commentText.trim()} onClick={() => submitComment(ln)}>发送到输入区</button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          ) : (
            <div className="file-tree">
              <div className="file-head ft-head">
                <button
                  className={'ft-filter' + (changedOnly ? ' active' : '')}
                  onClick={() => setChangedOnly((v) => !v)}
                  title="只显示 git 变更涉及的文件"
                >
                  仅变更 <span className="ft-filter-count">{gitDiff.length}</span>
                </button>
              </div>
              {visibleFiles.length === 0 ? (
                <div className="side-empty">
                  {changedOnly
                    ? '无变更文件'
                    : projectContext?.project
                    ? '空项目 · 暂无文件'
                    : '未选择项目 · 在底部「选择项目」导入或新建'}
                </div>
              ) : (
                visibleFiles.map((n) => (
                  <FileTreeNode key={n.path} node={n} depth={0} activePath={null} onOpen={openFile} />
                ))
              )}
            </div>
          )
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

        {tab === 'term' && <PtyTerminal active={tab === 'term'} className="term-panel" />}

        {tab === 'browser' && <BrowserTab />}

        {tab === 'map' && <ProjectMapPanel />}

        {tab === 'rules' && <RulesPanel />}

        {tab === 'bot' && <BotChannelPanel />}

        {tab === 'worker' && <WorkerRulesPanel />}
      </div>
    </section>
  );
}
