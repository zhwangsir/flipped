import { useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '../store';
import type { Role, StreamItem, ToolCall, ToolChild } from '../types';
import { isTauri, pickFolder } from '../lib/native';
import { PlanCard } from './PlanCard';
import { FailurePanel } from './FailurePanel'; // M95 — RCA / verifier 判决可观测
import {
  ToolIcon,
  IconSend,
  IconCheck,
  IconPlus,
  IconChevronDown,
  IconShield,
  IconX,
  IconHourglass,
  IconCircleAlert,
  IconCheckCircle,
  IconTerminal,
  IconBrowser,
  IconFile,
  IconFolder,
  IconSparkle,
  IconGit,
  IconSearch,
  IconChevronRight,
} from '../icons';

const ROLE: Record<Role, { label: string; cls: string; avatar: string }> = {
  user: { label: '你', cls: 'user', avatar: '你' },
  supervisor: { label: 'Supervisor · 调度', cls: 'supervisor', avatar: 'S' },
  worker: { label: 'Worker · 执行', cls: 'worker', avatar: 'W' },
  overseer: { label: 'Overseer · 监督', cls: 'overseer', avatar: 'O' },
  verify: { label: '强制验收', cls: 'verify', avatar: '✓' },
  system: { label: '系统', cls: 'system', avatar: '⚙' },
};

function StatusBanner({ status, progress }: { status: string | null; progress: number }) {
  if (!status || status === 'idle') return null;
  const isRunning = status === 'running';
  const isDone = status === 'done';
  const isReview = status === 'review';
  const isError = status === 'error';
  return (
    <div className={'status-banner ' + status} data-testid='status-banner' role='status' aria-live='polite'>
      <span className='sb-icon'>
        {isDone && <IconCheckCircle size={14} />}
        {isReview && <IconCircleAlert size={14} />}
        {isError && <IconCircleAlert size={14} />}
        {isRunning && <IconHourglass size={14} />}
      </span>
      <span className='sb-text'>
        {isRunning && (progress > 0 ? '运行中… ' + progress + '%' : '运行中…')}
        {isDone && '任务已完成'}
        {isReview && '待人工审批'}
        {isError && '执行出错'}
      </span>
      {isRunning && progress > 0 && (
        <div className='progress-track'>
          <span className='progress-fill' style={{ width: progress + '%' }} />
        </div>
      )}
    </div>
  );
}

function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className='error-banner' data-testid='error-banner' role='alert'>
      <IconCircleAlert size={14} />
      <span>{message}</span>
    </div>
  );
}

function ApprovalCard({ info, onApprove, onReject, busy }: {
  info: { id: string; action?: string; reason?: string; risk?: string };
  onApprove: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  return (
    <div className='approval-card' data-testid='approval-card' role='dialog' aria-modal='true' aria-label='任务审批'>
      <div className='approval-head'>
        <IconShield size={16} />
        <span className='approval-title'>人工审批请求</span>
        <span className='approval-risk'>{info.risk || 'medium'}</span>
      </div>
      <div className='approval-body'>
        <div className='approval-action'>{info.action || '未知动作'}</div>
        {info.reason && <div className='approval-reason'>{info.reason}</div>}
      </div>
      <div className='approval-actions'>
        <button className='approval-btn reject' onClick={onReject} disabled={busy} data-testid='reject-button'>
          <IconX size={13} /> 否决
        </button>
        <button className='approval-btn approve' onClick={onApprove} disabled={busy} data-testid='approve-button'>
          <IconCheck size={13} /> 放行
        </button>
      </div>
    </div>
  );
}

function Turn({ item }: { item: StreamItem }) {
  const r = ROLE[item.role];

  // 用户消息：右对齐浅灰气泡(对齐真机 Codex)
  if (item.role === 'user') {
    return (
      <div className='turn user'>
        {item.text && <div className='turn-text'>{item.text}</div>}
      </div>
    );
  }

  // Agent：扁平文档式,无头像。主执行体(worker)不加角色标签,像真机一样干净；
  // 元角色(supervisor/overseer/verify)保留细小标签以体现 flipped 的多 Agent 编排。
  const showRole = item.role !== 'worker';
  return (
    <div className={'turn ' + item.role}>
      {showRole && (
        <div className='role-line'>
          <span className={'role-name rc-' + item.role}>{r.label}</span>
          {item.model && <span className='role-model'>{item.model}</span>}
        </div>
      )}
      {item.text && <div className='turn-text'>{item.text}</div>}

      {item.tools && (
        <div className='tools'>
          {item.tools.map((t, i) => (
            <ToolRow key={i} tool={t} />
          ))}
        </div>
      )}

      {item.verdict && (
        <div className='verdict'>
          <div className='meters'>
            {(['efficiency', 'direction'] as const).map((k) => (
              <div className='meter' key={k}>
                <div className='meter-top'>
                  <span>{k === 'efficiency' ? '效率' : '方向'}</span>
                  <b>{item.verdict![k].toFixed(2)}</b>
                </div>
                <div className='meter-track'>
                  <span className='meter-fill' style={{ width: item.verdict![k] * 100 + '%' }} />
                </div>
              </div>
            ))}
          </div>
          <div className='verdict-note'>{item.verdict.note}</div>
          <span className='verdict-action'>action = {item.verdict.action}</span>
        </div>
      )}

      {item.role === 'verify' && item.ok && (
        <div className='verify-banner'>
          <IconCheck size={16} /> {item.text}
        </div>
      )}
    </div>
  );
}

function ChildIcon({ type }: { type: ToolChild['type'] }) {
  if (type === 'terminal') return <IconTerminal size={12} />;
  if (type === 'browser') return <IconBrowser size={12} />;
  if (type === 'file_change') return <IconFile size={12} />;
  return <IconCheck size={12} />;
}

const STATUS_TEXT: Record<string, string> = { ok: '完成', running: '运行中', error: '失败' };

const ACTION_LABEL: Record<string, string> = {
  terminal: '终端命令',
  file_editor: '编辑文件',
  browser: '浏览器',
  search: '搜索',
};

/** Codex 式动作行主文本：终端显示 `$ 命令`、文件显示路径(等宽)，其余显示摘要或动作名。 */
function toolPrimary(tool: ToolCall): { text: string; mono: boolean } {
  const summary = tool.summary && tool.summary !== tool.tool ? tool.summary : '';
  if (tool.tool === 'terminal') return { text: '$ ' + (summary || '命令'), mono: true };
  if (tool.tool === 'file_editor') return { text: summary || '编辑文件', mono: true };
  return { text: summary || ACTION_LABEL[tool.tool] || tool.tool, mono: false };
}

function ToolRow({ tool }: { tool: ToolCall }) {
  const hasBody = (tool.children && tool.children.length > 0) || !!tool.detail;
  // Codex 式：输出默认折叠，失败自动展开
  const [open, setOpen] = useState(tool.status === 'error');
  const primary = toolPrimary(tool);
  return (
    <div className={'tool-card ' + tool.status}>
      <button
        type='button'
        className='tool-head'
        aria-expanded={hasBody ? open : undefined}
        onClick={() => hasBody && setOpen((o) => !o)}
        disabled={!hasBody}
      >
        <span className='tool-ic'>
          <ToolIcon name={tool.tool} />
        </span>
        <span className={'tool-label' + (primary.mono ? ' mono' : '')}>{primary.text}</span>
        <span className={'tool-status ' + tool.status}>
          {tool.status === 'running' && <span className='tool-spin' />}
          {tool.status === 'ok' && <IconCheck size={11} />}
          {STATUS_TEXT[tool.status] || tool.status}
        </span>
        {hasBody && (
          <span className={'tool-chev' + (open ? ' open' : '')}>
            <IconChevronDown size={13} />
          </span>
        )}
      </button>
      {open && hasBody && (
        <div className='tool-expand'>
          {tool.detail && <div className='tool-det'>{tool.detail}</div>}
          {tool.children?.map((c, i) => (
            <div className={'tool-child ' + c.type} key={i}>
              <span className='tool-child-ic'>
                <ChildIcon type={c.type} />
              </span>
              <pre className='tool-child-tx'>{c.text}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Conversation() {
  const {
    stream,
    sendTask,
    selectedSessionId,
    sessionStatus,
    progress,
    lastError,
    approvalPending,
    sendApproval,
    cancelTask,
    selectedModel,
    setModel,
    selectedMode,
    setMode,
    setContextTab,
    projectContext,
    projects,
    projectFiles,
    openProject,
    createProject,
    composerPrefill,
    prefillComposer,
  } = useApp();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [plusOpen, setPlusOpen] = useState(false);
  const [projPicker, setProjPicker] = useState(false);
  const [pickerMode, setPickerMode] = useState<null | 'import' | 'new'>(null);
  const [pickerInput, setPickerInput] = useState('');
  const [pickerErr, setPickerErr] = useState('');
  const [mention, setMention] = useState<string | null>(null); // @ 之后的查询串,null=未提及
  const [mentionSel, setMentionSel] = useState(0);
  const [sendErr, setSendErr] = useState(''); // 发送失败可见反馈（M146 P1：此前静默吞错）
  const [projQuery, setProjQuery] = useState(''); // 项目选择器搜索串（M146：此前搜索框无过滤逻辑）

  // 扁平化项目文件路径(供 @ 提及)
  const flatFiles = useMemo(() => {
    const out: string[] = [];
    const walk = (nodes: typeof projectFiles) => {
      for (const n of nodes) {
        if (n.type === 'file') out.push(n.path);
        else if (n.children) walk(n.children);
      }
    };
    walk(projectFiles);
    return out;
  }, [projectFiles]);

  const mentionMatches = useMemo(() => {
    if (mention === null) return [];
    const q = mention.toLowerCase();
    return flatFiles.filter((f) => f.toLowerCase().includes(q)).slice(0, 8);
  }, [mention, flatFiles]);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const plusWrapRef = useRef<HTMLDivElement>(null);
  const projPickerRef = useRef<HTMLDivElement>(null);

  // + 菜单：点外部关闭
  useEffect(() => {
    if (!plusOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!plusWrapRef.current?.contains(e.target as Node)) setPlusOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [plusOpen]);

  // 项目选择器：点外部关闭(并重置输入模式)
  useEffect(() => {
    if (!projPicker) return;
    const onDown = (e: MouseEvent) => {
      if (!projPickerRef.current?.contains(e.target as Node)) {
        setProjPicker(false);
        setPickerMode(null);
        setPickerInput('');
        setPickerErr('');
        setProjQuery('');
      }
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [projPicker]);

  // §3.4 — 行内评论把「关于 文件:行 …」预填进输入框并聚焦（评论回喂 agent）
  useEffect(() => {
    if (!composerPrefill) return;
    setText((t) => (t ? t + '\n' : '') + composerPrefill);
    prefillComposer('');
    requestAnimationFrame(() => taRef.current?.focus());
  }, [composerPrefill, prefillComposer]);

  const submit = async () => {
    if (!text.trim() || busy || approvalPending) return;
    setBusy(true);
    setSendErr('');
    try {
      await sendTask(text.trim());
      setText('');
    } catch (e) {
      // 发送失败必须可见——此前异常只走 finally，用户以为已发出（M146 P1）
      setSendErr(e instanceof Error ? e.message.replace(/^HTTP \d+: /, '') : '发送失败，请重试');
    } finally {
      setBusy(false);
    }
  };

  const closePicker = () => {
    setProjPicker(false);
    setPickerMode(null);
    setPickerInput('');
    setPickerErr('');
    setProjQuery('');
  };
  const submitPicker = async () => {
    const v = pickerInput.trim();
    if (!v) return;
    try {
      if (pickerMode === 'new') await createProject(v);
      else await openProject(v);
      closePicker();
    } catch (e) {
      setPickerErr(e instanceof Error ? e.message.replace(/^HTTP \d+: /, '') : '操作失败');
    }
  };
  // 「导入现有文件夹」:桌面壳弹原生选择框;浏览器回退到粘贴路径输入
  const importFolder = async () => {
    if (isTauri()) {
      const p = await pickFolder();
      if (!p) return; // 取消
      try {
        await openProject(p);
        closePicker();
      } catch (e) {
        setPickerMode('import');
        setPickerInput(p);
        setPickerErr(e instanceof Error ? e.message.replace(/^HTTP \d+: /, '') : '导入失败');
      }
    } else {
      setPickerMode('import');
      setPickerInput('');
    }
  };

  const handleApprove = async () => {
    setApprovalBusy(true);
    try {
      await Promise.resolve(sendApproval('approve'));
    } finally {
      setApprovalBusy(false);
    }
  };

  const handleReject = async () => {
    setApprovalBusy(true);
    try {
      await Promise.resolve(sendApproval('reject'));
    } finally {
      setApprovalBusy(false);
    }
  };

  const disabled = busy || approvalPending !== null;
  const isNewThread = !selectedSessionId && stream.length === 0 && !approvalPending;

  // 项目选择器搜索过滤（M146：此前输入不过滤列表，搜索框是死输入框）
  const projQueryLc = projQuery.trim().toLowerCase();
  const visibleProjects = projQueryLc
    ? projects.filter((p) => p.name.toLowerCase().includes(projQueryLc))
    : projects;

  // @ 提及:根据光标前的 @token 更新查询串
  const onComposerChange = (value: string, cursor: number) => {
    setText(value);
    const m = /(?:^|\s)@([^\s@]*)$/.exec(value.slice(0, cursor));
    setMention(m ? m[1] : null);
    setMentionSel(0);
  };
  const pickMention = (path: string) => {
    const ta = taRef.current;
    const cursor = ta ? ta.selectionStart : text.length;
    const before = text.slice(0, cursor).replace(/@([^\s@]*)$/, '@' + path + ' ');
    const next = before + text.slice(cursor);
    setText(next);
    setMention(null);
    requestAnimationFrame(() => {
      if (ta) {
        ta.focus();
        ta.setSelectionRange(before.length, before.length);
      }
    });
  };

  const composer = (
      <div className='composer'>
        <div className={'composer-box ' + (disabled ? 'disabled' : '')}>
          {mention !== null && mentionMatches.length > 0 && (
            <div className='mention-menu' role='listbox'>
              <div className='mention-label'>项目文件</div>
              {mentionMatches.map((f, i) => (
                <button
                  key={f}
                  className={'mention-item mono' + (i === mentionSel ? ' active' : '')}
                  role='option'
                  aria-selected={i === mentionSel}
                  onMouseMove={() => setMentionSel(i)}
                  onClick={() => pickMention(f)}
                >
                  <IconFile size={12} /> {f}
                </button>
              ))}
            </div>
          )}
          <textarea
            ref={taRef}
            data-testid='composer-input'
            rows={2}
            placeholder='描述你想构建的东西，或问任何问题…'
            aria-label='输入消息'
            value={text}
            disabled={disabled}
            onChange={(e) => onComposerChange(e.target.value, e.target.selectionStart)}
            onKeyDown={(e) => {
              if (mention !== null && mentionMatches.length > 0) {
                if (e.key === 'ArrowDown') { e.preventDefault(); setMentionSel((s) => Math.min(s + 1, mentionMatches.length - 1)); return; }
                if (e.key === 'ArrowUp') { e.preventDefault(); setMentionSel((s) => Math.max(s - 1, 0)); return; }
                if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickMention(mentionMatches[mentionSel]); return; }
                if (e.key === 'Escape') { e.preventDefault(); setMention(null); return; }
              }
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className='composer-bar'>
            <div className='cbar-plus-wrap' ref={plusWrapRef}>
              <button
                className={'cbar-plus' + (plusOpen ? ' active' : '')}
                disabled={disabled}
                onClick={() => setPlusOpen((o) => !o)}
                title='添加'
                aria-haspopup='menu'
                aria-expanded={plusOpen}
              >
                <IconPlus size={15} />
              </button>
              {plusOpen && (
                <div className='plus-menu' role='menu'>
                  <div className='plus-menu-label'>添加</div>
                  <button
                    className='plus-menu-item'
                    role='menuitem'
                    onClick={() => {
                      setText((t) => (t.endsWith('@') || t === '' ? t + '@' : t + ' @'));
                      setPlusOpen(false);
                      requestAnimationFrame(() => taRef.current?.focus());
                    }}
                  >
                    <IconFolder size={15} />
                    <span className='pm-name'>文件和文件夹</span>
                    <span className='pm-sub'>@ 引用</span>
                  </button>
                  <button
                    className='plus-menu-item'
                    role='menuitem'
                    onClick={() => {
                      setText((t) => (t ? t + '\n' : '') + '目标：');
                      setPlusOpen(false);
                      requestAnimationFrame(() => taRef.current?.focus());
                    }}
                  >
                    <IconSparkle size={15} />
                    <span className='pm-name'>目标</span>
                    <span className='pm-sub'>设定持续目标</span>
                  </button>
                  <button
                    className={'plus-menu-item' + (selectedMode === 'plan' ? ' active' : '')}
                    role='menuitem'
                    aria-pressed={selectedMode === 'plan'}
                    onClick={() => {
                      setMode('plan');
                      setPlusOpen(false);
                    }}
                  >
                    <IconCheckCircle size={15} />
                    <span className='pm-name'>计划模式</span>
                    <span className='pm-sub'>拆解为步骤</span>
                  </button>
                </div>
              )}
            </div>
            <button
              className='cbar-access'
              disabled={disabled}
              onClick={() => setContextTab('term')}
              title='沙盒访问级别（受控 Docker 沙盒）'
            >
              <IconShield size={13} /> 沙盒 <IconChevronDown size={11} />
            </button>
            <span className='spacer' />
            {sessionStatus === 'running' && (
              <button className='cbar-stop' onClick={() => cancelTask().catch(() => {})} disabled={busy} title='停止'>
                <IconX size={13} /> 停止
              </button>
            )}
            <select
              className='cbar-effort'
              value={selectedModel}
              onChange={(e) => setModel(e.target.value)}
              disabled={disabled}
              title='执行模型'
            >
              <option value='coder'>Kimi-K2.7 · coder</option>
              <option value='architect'>GLM-5.2 · architect</option>
            </select>
            <button
              className='send'
              data-testid='send-button'
              aria-label='发送'
              onClick={submit}
              disabled={disabled}
            >
              <IconSend size={15} />
            </button>
          </div>
        </div>
        {sendErr && (
          <div className='form-err' role='alert' data-testid='send-error'>{sendErr}</div>
        )}
        <div className='composer-context'>
          <div className='ctx-proj-wrap' ref={projPickerRef}>
            <button className='ctx-item ctx-proj' onClick={() => setProjPicker((o) => !o)}>
              <IconFile size={12} /> {projectContext?.project || '选择项目'}
              <IconChevronDown size={11} />
            </button>
            {projPicker && (
              <div className='proj-picker'>
                {pickerMode !== null ? (
                  <div className='proj-folder'>
                    <div className='proj-folder-h'>{pickerMode === 'new' ? '新建空白项目' : '导入现有文件夹'}</div>
                    <input
                      className='proj-folder-input mono'
                      autoFocus
                      value={pickerInput}
                      placeholder={pickerMode === 'new' ? '项目名，如 my-app' : '粘贴文件夹绝对路径，如 /Users/…/my-app'}
                      onChange={(e) => { setPickerInput(e.target.value); setPickerErr(''); }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') submitPicker();
                        else if (e.key === 'Escape') { setPickerMode(null); setPickerInput(''); setPickerErr(''); }
                      }}
                    />
                    {pickerMode === 'import' && (
                      <div className='proj-folder-hint'>外部文件夹会拷进 ~/projects，沙盒经 /projects 挂载才能访问</div>
                    )}
                    {pickerErr && <div className='proj-folder-err'>{pickerErr}</div>}
                    <div className='proj-folder-actions'>
                      <button onClick={() => { setPickerMode(null); setPickerInput(''); setPickerErr(''); }}>取消</button>
                      <button className='primary' disabled={!pickerInput.trim()} onClick={submitPicker}>
                        {pickerMode === 'new' ? '创建' : '导入'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className='proj-picker-search'>
                      <IconSearch size={13} />
                      <input
                        placeholder='搜索项目'
                        aria-label='搜索项目'
                        value={projQuery}
                        onChange={(e) => setProjQuery(e.target.value)}
                      />
                    </div>
                    {projects.length === 0 && (
                      <div className='proj-picker-empty'>~/projects 下暂无项目 · 新建或导入一个</div>
                    )}
                    {projects.length > 0 && visibleProjects.length === 0 && (
                      <div className='proj-picker-empty'>无匹配「{projQuery.trim()}」的项目</div>
                    )}
                    {visibleProjects.map((p) => (
                      <button
                        key={p.host}
                        className={'proj-picker-item' + (projectContext?.project === p.name ? ' selected' : '')}
                        onClick={() => { openProject(p.host).catch(() => {}); closePicker(); }}
                      >
                        <IconFile size={14} />
                        <span className='pp-name'>{p.name}</span>
                        {projectContext?.project === p.name && <IconCheck size={14} />}
                      </button>
                    ))}
                    <div className='proj-picker-item has-sub'>
                      <IconPlus size={14} />
                      <span className='pp-name'>New project</span>
                      <IconChevronRight size={13} />
                      <div className='proj-subpicker'>
                        <button className='proj-picker-item' onClick={() => { setPickerMode('new'); setPickerInput(''); }}>
                          <IconPlus size={14} />
                          <span className='pp-name'>新建空白项目</span>
                        </button>
                        <button className='proj-picker-item' onClick={importFolder}>
                          <IconFolder size={14} />
                          <span className='pp-name'>导入现有文件夹</span>
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
          <span className='ctx-sep'>·</span>
          <select
            className='ctx-mode'
            value={selectedMode}
            onChange={(e) => setMode(e.target.value)}
            title='模式：自主(拆→写→测→修→循环,全自动) / 智能体(沙盒单次执行) / 对话(直连模型) / 规划(拆步骤)'
          >
            <option value='auto'>自主</option>
            <option value='agent'>智能体</option>
            <option value='chat'>对话</option>
            <option value='plan'>规划</option>
          </select>
          <span className='ctx-sep'>·</span>
          <span className='ctx-item mono'>
            <IconGit size={12} /> {projectContext?.branch || 'main'}
          </span>
        </div>
      </div>
  );

  // Codex 招牌：新线程状态下，大问句 + composer 垂直居中成一组
  if (isNewThread) {
    return (
      <section className='center center-new'>
        <div className='new-thread'>
          <h1 className='empty-hero'>
            {projectContext?.project
              ? `我们应该在 ${projectContext.project} 中构建什么？`
              : '选择一个项目，开始构建'}
          </h1>
          {composer}
        </div>
      </section>
    );
  }

  return (
    <section className='center'>
      <div className='stream'>
        <StatusBanner status={sessionStatus} progress={progress} />
        <ErrorBanner message={lastError} />
        <FailurePanel />
        <PlanCard />
        {approvalPending && (
          <ApprovalCard
            info={approvalPending}
            onApprove={handleApprove}
            onReject={handleReject}
            busy={approvalBusy}
          />
        )}
        {selectedSessionId && stream.length === 0 && !approvalPending && (
          <div className='empty-state'>
            <h1 className='empty-hero'>准备就绪</h1>
            <div className='empty-sub'>发送消息开始对话 · ⌘K 唤起命令面板</div>
          </div>
        )}
        {stream.map((it) => (
          <Turn key={it.id} item={it} />
        ))}
      </div>
      {composer}
    </section>
  );
}
