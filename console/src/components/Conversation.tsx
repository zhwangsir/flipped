import { useEffect, useRef, useState } from 'react';
import { useApp } from '../store';
import type { Role, StreamItem, ToolCall, ToolChild } from '../types';
import {
  ToolIcon,
  IconSend,
  IconCheck,
  IconSparkle,
  IconChat,
  IconLayout,
  IconAt,
  IconPuzzle,
  IconCube,
  IconChevronDown,
  IconShield,
  IconX,
  IconHourglass,
  IconCircleAlert,
  IconCheckCircle,
  IconTerminal,
  IconBrowser,
  IconFile,
  IconGit,
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
    <div className={'status-banner ' + status} data-testid='status-banner'>
      <span className='sb-icon'>
        {isDone && <IconCheckCircle size={14} />}
        {isReview && <IconCircleAlert size={14} />}
        {isError && <IconCircleAlert size={14} />}
        {isRunning && <IconHourglass size={14} />}
      </span>
      <span className='sb-text'>
        {isRunning && '运行中… ' + progress + '%'}
        {isDone && '任务已完成'}
        {isReview && '待人工审批'}
        {isError && '执行出错'}
      </span>
      {isRunning && (
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
    <div className='error-banner' data-testid='error-banner'>
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
    <div className='approval-card' data-testid='approval-card'>
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
  return (
    <div className={'turn ' + item.role}>
      <div className={'avatar ' + r.cls}>{r.avatar}</div>
      <div>
        {item.role !== 'user' && (
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
    </div>
  );
}

function ChildIcon({ type }: { type: ToolChild['type'] }) {
  if (type === 'terminal') return <IconTerminal size={12} />;
  if (type === 'browser') return <IconBrowser size={12} />;
  if (type === 'file_change') return <IconFile size={12} />;
  return <IconCheck size={12} />;
}

function ToolRow({ tool }: { tool: ToolCall }) {
  return (
    <div className='tool'>
      <span className='tool-ic'>
        <ToolIcon name={tool.tool} />
      </span>
      <div className='tool-body'>
        <div className='tool-sum'>{tool.summary}</div>
        {tool.detail && <div className='tool-det'>{tool.detail}</div>}
        {tool.children && tool.children.length > 0 && (
          <div className='tool-children'>
            {tool.children.map((c, i) => (
              <div className={'tool-child ' + c.type} key={i}>
                <span className='tool-child-ic'>
                  <ChildIcon type={c.type} />
                </span>
                <span className='tool-child-tx'>{c.text}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <span className={'tool-status ' + tool.status}>
        {tool.status === 'ok' && <IconCheck size={11} />}
        {tool.status === 'ok' ? '完成' : tool.status === 'running' ? '运行中' : tool.status}
      </span>
    </div>
  );
}

export function Conversation() {
  const {
    stream,
    sendTask,
    connection,
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
    composerPrefill,
    prefillComposer,
  } = useApp();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);

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
    try {
      await sendTask(text.trim());
      setText('');
    } finally {
      setBusy(false);
    }
  };

  const handleApprove = () => {
    setApprovalBusy(true);
    sendApproval('approve');
  };

  const handleReject = () => {
    setApprovalBusy(true);
    sendApproval('reject');
  };

  const disabled = busy || approvalPending !== null;

  return (
    <section className='center'>
      <div className='stream'>
        <StatusBanner status={sessionStatus} progress={progress} />
        <ErrorBanner message={lastError} />
        {approvalPending && (
          <ApprovalCard
            info={approvalPending}
            onApprove={handleApprove}
            onReject={handleReject}
            busy={approvalBusy}
          />
        )}
        {stream.length === 0 && !approvalPending && (
          <div className='empty-state'>
            {selectedSessionId ? (
              <>
                <h1 className='empty-hero'>准备就绪</h1>
                <div className='empty-sub'>等待事件流… · WebSocket {connection}</div>
              </>
            ) : (
              <>
                <h1 className='empty-hero'>我们应该在 flipped 中构建什么？</h1>
                <div className='empty-sub'>
                  本地模型驱动的 AI 开发工厂 · 在受控沙盒中自主编码、调用工具、修改文件
                </div>
                <div className='empty-hints'>
                  <span className='empty-hint'>
                    <IconSparkle size={12} /> 智能体 · 沙盒执行
                  </span>
                  <span className='empty-hint'>
                    <IconChat size={12} /> 对话 · 直连本地模型
                  </span>
                  <span className='empty-hint'>
                    <IconLayout size={12} /> 规划 · 拆解步骤
                  </span>
                </div>
              </>
            )}
          </div>
        )}
        {stream.map((it) => (
          <Turn key={it.id} item={it} />
        ))}
      </div>

      <div className='composer'>
        <div className='modes'>
          <button
            className={'mode agent' + (selectedMode === 'agent' ? ' active' : '')}
            onClick={() => setMode('agent')}
            title='智能体：在沙盒中自主执行、用工具、改文件'
          >
            <IconSparkle size={13} /> 智能体
          </button>
          <button
            className={'mode' + (selectedMode === 'chat' ? ' active' : '')}
            onClick={() => setMode('chat')}
            title='对话：直连本地模型问答，不执行、不改文件'
          >
            <IconChat size={13} /> 对话
          </button>
          <button
            className={'mode' + (selectedMode === 'plan' ? ' active' : '')}
            onClick={() => setMode('plan')}
            title='规划：让模型把目标拆成有序步骤，不执行'
          >
            <IconLayout size={13} /> 规划
          </button>
        </div>
        <div className={'composer-box ' + (disabled ? 'disabled' : '')}>
          <textarea
            ref={taRef}
            data-testid='composer-input'
            rows={2}
            placeholder={
              selectedMode === 'chat'
                ? '和本地模型对话，问任何问题…'
                : selectedMode === 'plan'
                ? '描述目标，让模型先出一份分步计划…'
                : '给 flipped 一个任务，或 @ 引用文件、粘贴报错让它自主修复…'
            }
            value={text}
            disabled={disabled}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className='composer-bar'>
            <button
              className='tool-btn'
              disabled={disabled}
              onClick={() => setText((t) => (t.endsWith('@') || t === '' ? t + '@' : t + ' @'))}
              title='引用上下文：插入 @'
            >
              <IconAt size={13} /> 上下文
            </button>
            <button
              className='tool-btn on'
              disabled={disabled}
              onClick={() => setContextTab('mcp')}
              title='查看 / 开关 MCP 工具'
            >
              <IconPuzzle size={13} /> 工具
            </button>
            <button
              className='tool-btn sandbox'
              disabled={disabled}
              onClick={() => setContextTab('term')}
              title='沙盒访问级别 · 查看终端'
            >
              <IconCube size={13} /> 沙盒 <IconChevronDown size={12} />
            </button>
            <select
              className='tool-btn model-select'
              value={selectedModel}
              onChange={(e) => setModel(e.target.value)}
              disabled={disabled}
              title='执行模型'
            >
              <option value='coder'>Kimi-K2.7 · coder</option>
              <option value='architect'>GLM-5.2 · architect</option>
            </select>
            {sessionStatus === 'running' && (
              <button className='tool-btn stop' onClick={() => cancelTask()}>
                <IconX size={13} /> 停止
              </button>
            )}
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
        {projectContext && (
          <div className='composer-context'>
            <span className='ctx-item'>
              <IconFile size={12} /> {projectContext.project}
            </span>
            <span className='ctx-sep'>·</span>
            <span className='ctx-item'>{projectContext.mode}</span>
            <span className='ctx-sep'>·</span>
            <span className='ctx-item mono'>
              <IconGit size={12} /> {projectContext.branch}
            </span>
          </div>
        )}
      </div>
    </section>
  );
}
