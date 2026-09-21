/**
 * M151.4 · Assistant 视图:对话式代码助手主界面(Codex 风)。
 *
 * 三栏布局由 AppShell 提供(Sidebar | center | ContextPanel),本组件只负责中间栏:
 * - MessageStream:user 右对齐 indigo 8% 底;assistant 左对齐 + 2px coral 左边框;
 *   tool 用 ToolCard 折叠卡;approval 用 ApprovalInline 行内卡。
 * - Composer:底部固定 textarea,Enter 发送 / Shift+Enter 换行;slash 命令补全。
 *
 * 流式分两层(M166):
 * - 步级 Event 流:后端 /assistant/history 折叠,WS 事件驱动 300ms 防抖刷新(M165.3);
 * - token 级流式:chat/plan 直聊通路,WS token 事件累积进 store.assistantStream,
 *   turns 列表末尾渲染流式气泡(同 assistant turn 视觉 + stream-cursor 闪烁光标),
 *   done token / worker message / 会话切换时收敛(M166.3/M166.4)。
 *
 * M167.3 — assistant 气泡与流式气泡改由 MarkdownView 渲染 GFM 子集
 * (标题/代码块/列表/引用/表格/行内样式);user 气泡保持纯文本不解析。
 *
 * M169.2 — token 用量渲染:assistant turn 气泡下方逐条 usage 行(↑ prompt · ↓
 * completion),视图头部会话合计 chip;usage 事件(M165.3 防抖集合)驱动末端刷新。
 */
import { useEffect, useMemo, useState } from 'react';
import { useApp } from '../store';
import type { AssistantTurn } from '../types';
import { Composer } from './Composer';
import { ToolCard } from './ToolCard';
import { MarkdownView } from '../components/MarkdownView';
import { formatTokens } from '../lib/format';
import { IconShield, IconX, IconCheck, IconEdit, IconFile, IconTarget, IconSmartphone } from '../icons';
import emptyHeroArt from '../assets/empty-hero.jpg';
import { RemoteModal } from '../components/RemoteModal';
import { API_BASE } from '../api';

/** M175 — @ 文件引用状态中文标签(非 ok 状态展示在引用 chip 尾部)。 */
const STATUS_CN: Record<string, string> = {
  missing: '未找到',
  binary: '二进制',
  outside_root: '越界',
  skipped: '超上限',
};

/** M176 — goal exhausted 原因中文标签(B 队 reason 枚举:max_iter/no_progress/judge_errors)。 */
const GOAL_REASON_CN: Record<string, string> = {
  max_iter: '达到最大轮次',
  no_progress: '连续无进展',
  judge_errors: '判定连续失败',
};

/** M176 — goal marker:role='goal' turn 四相位居中标记行(iter 琥珀/achieved 绿/exhausted 红/stopped 灰)。 */
function GoalMarker({ goal }: { goal: NonNullable<AssistantTurn['goal']> }) {
  let cls = 'goal-marker';
  let label = '';
  if (goal.phase === 'iter') {
    cls += ' iter';
    label = `目标迭代 ${goal.iteration}/${goal.max_iterations}`;
  } else if (goal.phase === 'achieved') {
    cls += ' achieved';
    label = `目标达成 · 第 ${goal.iteration} 轮`;
  } else if (goal.phase === 'exhausted') {
    cls += ' exhausted';
    const reason = goal.reason ? GOAL_REASON_CN[goal.reason] ?? goal.reason : '';
    label = `目标未达成 · ${reason}`;
  } else if (goal.phase === 'stopped') {
    cls += ' stopped';
    label = '目标已停止';
  } else {
    return null;
  }
  return (
    <div className={cls} data-testid={`goal-marker-${goal.phase}`}>
      <IconTarget size={13} />
      <span>{label}</span>
      {goal.phase === 'iter' && goal.gap && <span className='goal-gap'>{goal.gap}</span>}
    </div>
  );
}

/** 行内审批卡:Allow once 调 approveAssistant(sid);Always 调 approveAssistant(sid,'always');Reject 调 rejectAssistant(sid)。 */
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
          className='ap-btn always'
          data-testid='assistant-approve-always-btn'
          disabled={assistantBusy}
          onClick={() => approveAssistant(sessionId, 'always')}
        >
          <IconShield size={13} /> Always
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
  const { assistantBusy, editAssistantMessage } = useApp();
  // M174 — user 气泡「编辑并重跑」行内编辑态(本地 state;busy 变化不强制退出编辑态)
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  if (turn.role === 'user') {
    // 仅当有 event_id(旧会话无 → 向后兼容不显示)+ 选中会话 + 非 busy 时才可编辑
    const canEdit = !!sessionId && !!turn.event_id && !assistantBusy;
    const startEdit = () => {
      setDraft(turn.text || '');
      setEditing(true);
    };
    const confirmEdit = () => {
      const text = draft.trim();
      setEditing(false);
      if (!sessionId || !turn.event_id || !text) return;
      // store action 失败会抛错,此处 .catch 兜底防未捕获 rejection
      editAssistantMessage(sessionId, turn.event_id, text).catch(() => {});
    };
    return (
      <div className='assistant-msg user' data-testid='assistant-msg-user'>
        {editing ? (
          <div className='umsg-edit'>
            <textarea
              data-testid='umsg-edit-input'
              value={draft}
              autoFocus
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  confirmEdit();
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  setEditing(false);
                }
              }}
            />
            <div className='umsg-edit-actions'>
              <button
                type='button'
                className='umsg-edit-confirm'
                data-testid='umsg-edit-confirm'
                onClick={confirmEdit}
              >
                重新执行
              </button>
              <button type='button' data-testid='umsg-edit-cancel' onClick={() => setEditing(false)}>
                取消
              </button>
            </div>
          </div>
        ) : (
          <>
            {canEdit && (
              <button
                type='button'
                className='umsg-edit-btn'
                data-testid='umsg-edit-btn'
                title='编辑并重跑'
                onClick={startEdit}
              >
                <IconEdit size={12} />
              </button>
            )}
            {turn.text != null && <div className='bubble'>{turn.text}</div>}
            {turn.refs && turn.refs.length > 0 && (
              <div className='umsg-refs' data-testid='umsg-refs'>
                {turn.refs.map((r) => (
                  <span
                    key={r.token}
                    className={'umsg-ref' + (r.status === 'ok' ? '' : ' bad')}
                    data-testid={`umsg-ref-${r.path}`}
                  >
                    <IconFile size={11} />
                    <span>{r.path}</span>
                    {r.status === 'ok' ? (
                      <span className='umsg-ref-meta'>
                        {r.bytes >= 1024 ? `${(r.bytes / 1024).toFixed(1)}KB` : `${r.bytes}B`}
                        {r.truncated ? '·截断' : ''}
                      </span>
                    ) : (
                      <span className='umsg-ref-meta'>{STATUS_CN[r.status] ?? r.status}</span>
                    )}
                  </span>
                ))}
              </div>
            )}
            {turn.attachments && turn.attachments.length > 0 && sessionId && (
              <div className='umsg-atts' data-testid='umsg-atts'>
                {turn.attachments.map((a, i) => {
                  // path 形如 "{session_id}/{filename}",取 basename 段拼原图 URL
                  const fname = a.path.split('/').pop() || a.path;
                  const url = `${API_BASE}/api/v1/assistant/attachments/${encodeURIComponent(sessionId)}/${encodeURIComponent(fname)}`;
                  return (
                    <a key={`${a.path}-${i}`} href={url} target='_blank' rel='noreferrer'>
                      <img src={url} alt={a.name} />
                    </a>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    );
  }
  if (turn.role === 'assistant') {
    // M169.2 — 气泡内容下方逐条 token 用量行(仅 assistant role 且 usage 非空)
    const u = turn.usage;
    return (
      <div className='assistant-msg assistant' data-testid='assistant-msg-assistant'>
        {turn.text != null && (
          <div className='bubble'>
            <MarkdownView text={turn.text} />
          </div>
        )}
        {u && (
          <div className='turn-usage' data-testid='turn-usage'>
            ↑ {formatTokens(u.prompt)} · ↓ {formatTokens(u.completion)}
          </div>
        )}
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
  // M176 — goal turn → 居中 marker 行(四相位)
  if (turn.role === 'goal') {
    if (!turn.goal) return null;
    return <GoalMarker goal={turn.goal} />;
  }
  return null;
}

/** MessageStream:turns 列表 + 空态 hero + M166.4 token 流式气泡(turns 末尾)。 */
function MessageStream({ turns, sessionId }: { turns: AssistantTurn[]; sessionId: string | null }) {
  const { assistantStream } = useApp();
  // 空 text(active 但无内容)不渲染气泡
  const showStream = assistantStream.active && assistantStream.text.length > 0;
  if (turns.length === 0 && !showStream) {
    return (
      <div className='assistant-empty' data-testid='assistant-empty'>
        <img className='hero-art' src={emptyHeroArt} alt='' aria-hidden='true' />
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
      {showStream && (
        <div className='assistant-msg assistant' data-testid='assistant-streaming'>
          <div className='bubble'>
            <MarkdownView text={assistantStream.text} streaming />
            <span className='stream-cursor' aria-hidden='true' />
          </div>
        </div>
      )}
    </div>
  );
}

export function Assistant() {
  const {
    assistantTurns,
    assistantError,
    sendAssistantMessage,
    clearAssistantTurns,
    appendAssistantLocalTurn,
    compactAssistant,
    undoAssistant,
    changedFiles,
    selectedSessionId,
    selectedMode,
    setMode,
    selectedModel,
    setModel,
    // M176 — Goal 模式:合成 busy(goal 运行中 Composer 显示停止态)+ /goal 发送 action
    composerBusy,
    sendAssistantGoal,
    // M190.1 — 编辑重跑截断 banner(撤销/关闭;409 提示已被新事件覆盖)
    lastTruncated,
    undoEditTruncate,
    dismissTruncated,
  } = useApp();

  const turns = useMemo(() => assistantTurns, [assistantTurns]);

  // M190.1 — banner 撤销失败反馈(409=已被新事件覆盖);lastTruncated 变化时重置
  const [truncUndoError, setTruncUndoError] = useState<string | null>(null);
  useEffect(() => setTruncUndoError(null), [lastTruncated]);

  // M181.2 — 移动远程控制弹窗开关(头部「远程」按钮)
  const [remoteOpen, setRemoteOpen] = useState(false);

  // M169.2 — 会话级 token 合计(仅累计带 usage 的 turn;全无可合计 → null 不渲染 chip)
  const sessionUsage = useMemo(() => {
    let p = 0,
      c = 0;
    for (const t of turns) {
      if (t.usage) {
        p += t.usage.prompt;
        c += t.usage.completion;
      }
    }
    return p + c > 0 ? { p, c } : null;
  }, [turns]);

  // M165.1a — slash 命令接线:/clear 清空 /help 帮助 /mode 循环切模式 /files 变更清单 /compact 压缩上下文
  const onSlash = (cmd: string) => {
    if (cmd === '/clear') {
      clearAssistantTurns();
      return;
    }
    if (cmd === '/help') {
      appendAssistantLocalTurn(
        [
          '可用斜杠命令:',
          '/clear · 清空当前对话视图',
          '/compact · 压缩当前会话上下文,释放窗口',
          '/mode · 循环切换模式 auto→agent→chat→plan',
          '/files · 查看本次会话的文件变更',
          '/undo · 撤销最近一轮改动',
          '/goal · 目标驱动自循环:/goal <可验证目标>',
          '/help · 显示本帮助',
          '输入框右下角的两个下拉可分别切换模式与模型。',
        ].join('\n')
      );
      return;
    }
    if (cmd === '/mode') {
      const order = ['auto', 'agent', 'chat', 'plan'];
      const next = order[(order.indexOf(selectedMode) + 1) % order.length];
      setMode(next);
      appendAssistantLocalTurn(`模式已切换为 ${next}`);
      return;
    }
    if (cmd === '/files') {
      appendAssistantLocalTurn(
        changedFiles.length > 0
          ? changedFiles.map((f) => f.path).join('\n')
          : '暂无文件变更记录'
      );
      return;
    }
    if (cmd === '/compact') {
      if (!selectedSessionId) {
        appendAssistantLocalTurn('请先开始对话再压缩上下文');
        return;
      }
      // store 内部已处理成功刷新与失败提示,此处 .catch 仅兜底防未捕获 rejection
      compactAssistant(selectedSessionId).catch(() => {});
      return;
    }
    // M168.2 — /undo:撤销最近一轮 agent 文件改动(对标 opencode /undo)。
    // store action 内部 busy 包裹 + 成功后刷新 history/diff;此处拼结果摘要 turn。
    if (cmd === '/undo') {
      if (!selectedSessionId) {
        appendAssistantLocalTurn('请先开始对话再撤销改动');
        return;
      }
      undoAssistant(selectedSessionId)
        .then((r) => {
          const parts: string[] = [];
          if (r.restored) parts.push('回滚 tracked 文件');
          if (r.deleted.length > 0) {
            parts.push(`删除 ${r.deleted.length} 个新增文件(${r.deleted.join('、')})`);
          }
          appendAssistantLocalTurn(
            parts.length > 0 ? `已撤销最近一轮改动:${parts.join(',')}` : '快照无差异,无文件变动'
          );
        })
        .catch((e) =>
          appendAssistantLocalTurn(`撤销失败:${e instanceof Error ? e.message : String(e)}`)
        );
    }
  };

  // D-0007 修复：<section> → <main>，让 Assistant 视图成为页面的 main landmark。
  // Conversation.tsx（factory 路由）继续用 <section>，二者互斥渲染，不冲突。
  return (
    <main className='view-assistant' data-testid='view-assistant'>
      {/* M181.2 — assistant-head 恒渲染:usage chip 条件渲染,右侧「远程」按钮常驻 */}
      <div className='assistant-head'>
        {sessionUsage && (
          <span className='session-usage mono' data-testid='session-usage'>
            ↑ {formatTokens(sessionUsage.p)} · ↓ {formatTokens(sessionUsage.c)}
          </span>
        )}
        <button
          className='remote-open'
          data-testid='remote-open'
          title='手机远程控制'
          onClick={() => setRemoteOpen(true)}
        >
          <IconSmartphone size={14} /> 远程
        </button>
      </div>
      {remoteOpen && (
        <RemoteModal sessionId={selectedSessionId} onClose={() => setRemoteOpen(false)} />
      )}
      <MessageStream turns={turns} sessionId={selectedSessionId} />
      {/* M190.1 — 编辑重跑截断 banner:撤销恢复被截事件,可关闭;409 提示已被新事件覆盖 */}
      {lastTruncated && lastTruncated.sessionId === selectedSessionId && (
        <div className='trunc-banner' data-testid='trunc-banner'>
          <span className='trunc-banner-text'>
            已截断 {lastTruncated.count} 条事件
          </span>
          {truncUndoError && (
            <span className='trunc-banner-error' data-testid='trunc-banner-error'>
              {truncUndoError}
            </span>
          )}
          <button
            className='trunc-banner-undo'
            data-testid='trunc-banner-undo'
            onClick={() => {
              undoEditTruncate(lastTruncated.sessionId).catch((e) => {
                const msg = e instanceof Error ? e.message : String(e);
                setTruncUndoError(
                  msg.includes('new events appended') ? '撤销失败:截断后已追加新事件,无法恢复' : `撤销失败:${msg}`
                );
              });
            }}
          >
            撤销
          </button>
          <button
            className='trunc-banner-close'
            data-testid='trunc-banner-close'
            aria-label='关闭'
            onClick={dismissTruncated}
          >
            <IconX size={12} />
          </button>
        </div>
      )}
      {assistantError && (
        <div className='assistant-empty' style={{ padding: '6px 28px', color: 'var(--assistant-coral)' }}>
          {assistantError}
        </div>
      )}
      <Composer
        onSend={(text, images) => {
          // M192 — 原始 promise 交回 Composer:成功清空附件 chips,失败(rejected)保留供重试;
          // rejection 由 Composer .catch 消化(错误反馈仍走 store assistantError),无未捕获 rejection
          return sendAssistantMessage(text, selectedMode, images);
        }}
        onSlash={onSlash}
        onGoal={(objective) => {
          // M176 — /goal <目标>:sendAssistantGoal 自带 try/catch + assistantError 反馈,这里不再捕获
          sendAssistantGoal(objective).catch(() => {});
        }}
        busy={composerBusy}
        mode={selectedMode}
        onModeChange={setMode}
        model={selectedModel}
        onModelChange={setModel}
      />
    </main>
  );
}
