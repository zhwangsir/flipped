/**
 * M151.4 · Assistant 视图:对话式代码助手主界面(Codex 风)。
 *
 * 三栏布局由 AppShell 提供(Sidebar | center | ContextPanel),本组件只负责中间栏:
 * - MessageStream:user 右对齐 indigo 8% 底;assistant 左对齐 + 2px coral 左边框;
 *   tool 用 ToolCard 折叠卡;approval 用 ApprovalInline 行内卡。
 * - Composer:底部固定 textarea,Enter 发送 / Shift+Enter 换行;slash 命令补全。
 *
 * 不做 token 级流式 —— 用步级 Event 流(后端 /assistant/history 折叠,2.5s 轮询)。
 */
import { useMemo } from 'react';
import { useApp } from '../store';
import type { AssistantTurn } from '../types';
import { Composer } from './Composer';
import { ToolCard } from './ToolCard';
import { IconShield, IconX, IconCheck } from '../icons';

/** 行内审批卡:Allow once 调 approveAssistant(sid);Reject 调 rejectAssistant(sid)。 */
function ApprovalInline({ turn, sessionId }: { turn: AssistantTurn; sessionId: string }) {
  const { approveAssistant, rejectAssistant, assistantBusy } = useApp();
  const info = turn.approval || {};
  return (
    <div className='assistant-approval' data-testid='assistant-approval' role='alert'>
      <div className='ap-head'>
        <IconShield size={14} />
        <span>人工审批请求</span>
        {info.risk && <span style={{ marginLeft: 6, opacity: 0.7 }}>{info.risk}</span>}
      </div>
      {info.action && <div className='ap-action'>{info.action}</div>}
      {info.reason && <div className='ap-action' style={{ opacity: 0.7 }}>{info.reason}</div>}
      <div className='ap-actions'>
        <button
          type='button'
          className='ap-btn allow'
          data-testid='assistant-approve-btn'
          disabled={assistantBusy}
          onClick={() => approveAssistant(sessionId)}
        >
          <IconCheck size={13} /> Allow once
        </button>
        <button
          type='button'
          className='ap-btn reject'
          data-testid='assistant-reject-btn'
          disabled={assistantBusy}
          onClick={() => rejectAssistant(sessionId)}
        >
          <IconX size={13} /> Reject
        </button>
      </div>
    </div>
  );
}

/** 单条对话 turn 渲染:user/assistant 气泡 + tool 折叠卡 + approval 行内卡。 */
function Turn({ turn, sessionId }: { turn: AssistantTurn; sessionId: string | null }) {
  if (turn.role === 'user') {
    return (
      <div className='assistant-msg user' data-testid='assistant-msg-user'>
        {turn.text != null && <div className='bubble'>{turn.text}</div>}
      </div>
    );
  }
  if (turn.role === 'assistant') {
    return (
      <div className='assistant-msg assistant' data-testid='assistant-msg-assistant'>
        {turn.text != null && <div className='bubble'>{turn.text}</div>}
      </div>
    );
  }
  if (turn.role === 'tool') {
    return (
      <>
        {turn.tools.map((t, i) => (
          <ToolCard key={i} tool={t} />
        ))}
      </>
    );
  }
  if (turn.role === 'approval') {
    if (!sessionId) return null;
    return <ApprovalInline turn={turn} sessionId={sessionId} />;
  }
  return null;
}

/** MessageStream:turns 列表 + 空态 hero。 */
function MessageStream({ turns, sessionId }: { turns: AssistantTurn[]; sessionId: string | null }) {
  if (turns.length === 0) {
    return (
      <div className='assistant-empty' data-testid='assistant-empty'>
        <div className='hero'>我们能帮你构建什么?</div>
        <div className='sub'>输入需求开始 · / 唤起斜杠命令 · Enter 发送</div>
      </div>
    );
  }
  return (
    <div className='assistant-stream' data-testid='assistant-stream'>
      {turns.map((t, i) => (
        <Turn key={i} turn={t} sessionId={sessionId} />
      ))}
    </div>
  );
}

export function Assistant() {
  const {
    assistantTurns,
    assistantBusy,
    assistantError,
    sendAssistantMessage,
    clearAssistantTurns,
    selectedSessionId,
    selectedMode,
    setMode,
    selectedModel,
    setModel,
  } = useApp();

  const turns = useMemo(() => assistantTurns, [assistantTurns]);

  const onSlash = (cmd: string) => {
    // /clear 清空当前对话视图(不删会话);其余命令的持久化行为 P1 待办
    if (cmd === '/clear') {
      clearAssistantTurns();
      return;
    }
    // /compact /mode /help /files:M151.4 仅占位,P1 接通真实行为
    // 不抛错,不假装成功 —— 静默忽略,由后续里程碑接线
  };

  return (
    <section className='view-assistant' data-testid='view-assistant'>
      <MessageStream turns={turns} sessionId={selectedSessionId} />
      {assistantError && (
        <div className='assistant-empty' style={{ padding: '6px 28px', color: 'var(--assistant-coral)' }}>
          {assistantError}
        </div>
      )}
      <Composer
        onSend={(text) => {
          // sendAssistantMessage 自带 try/catch + assistantError 反馈,这里不再捕获
          sendAssistantMessage(text, selectedMode).catch(() => {});
        }}
        onSlash={onSlash}
        busy={assistantBusy}
        mode={selectedMode}
        onModeChange={setMode}
        model={selectedModel}
        onModelChange={setModel}
      />
    </section>
  );
}
