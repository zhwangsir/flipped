import { useApp } from '../store';
import { IconGit, IconCube, IconCheck, IconWarn, IconBolt, IconShield, IconHourglass } from '../icons';

function fmtTok(n: number): string {
  return n >= 1000 ? (n / 1000).toFixed(1) + 'k tok' : n + ' tok';
}

export function StatusBar() {
  const { connection, error, sessionStatus, progress, errorCount, approvalPending, metrics } = useApp();

  const connLabel =
    connection === 'connected'
      ? 'WS 已连接'
      : connection === 'connecting'
      ? 'WS 连接中'
      : connection === 'error'
      ? 'WS 错误'
      : 'WS 空闲';

  const statusLabel = sessionStatus
    ? sessionStatus === 'running'
      ? '运行中 ' + progress + '%'
      : sessionStatus === 'done'
      ? '已完成'
      : sessionStatus === 'review'
      ? '待审批'
      : sessionStatus === 'error'
      ? '出错'
      : '空闲'
    : '未开始';

  return (
    <footer className='statusbar'>
      <span className='sb'>
        <IconGit size={13} /> <span className='mono'>main</span>
      </span>
      <span className={'sb ' + (sessionStatus === 'done' ? 'ok' : sessionStatus === 'running' ? 'accent' : '')}>
        {sessionStatus === 'done' ? <IconCheck size={13} /> : sessionStatus === 'running' ? <IconHourglass size={13} /> : <IconBolt size={13} />}
        {' '}{statusLabel}
      </span>
      {errorCount > 0 && (
        <span className='sb' style={{ color: 'var(--danger)' }}>
          <IconWarn size={13} /> {errorCount}
        </span>
      )}
      {approvalPending && (
        <span className='sb accent'>
          <IconShield size={13} /> 审批中
        </span>
      )}
      <span className='spacer' />
      {error && (
        <span className='sb' style={{ color: 'var(--danger)' }}>
          {error}
        </span>
      )}
      <span className='sb-live'>
        <span className={'dot ' + connection} /> {connLabel}
      </span>
      {metrics && metrics.llm.total_calls > 0 && (
        <span className='sb mono' title='LLM 调用 · tokens · 平均延迟'>
          {metrics.llm.total_calls} calls · {fmtTok(metrics.llm.total_tokens)} · {Math.round(metrics.llm.avg_latency_ms)}ms
        </span>
      )}
      <span className='sb accent'>
        <IconBolt size={13} /> Kimi-K2.7 · <span className='mono'>coder</span>
      </span>
      <span className='sb'>
        <IconCube size={13} /> 沙盒 <span className='mono'>py3.12</span>
      </span>
    </footer>
  );
}
