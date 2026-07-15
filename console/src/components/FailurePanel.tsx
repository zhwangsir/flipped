/**
 * M95 — FailurePanel:RCA 与 verifier 判决可观测面板。
 *
 * 显示三类信息:
 * 1. 最近 RCA(根因 chip + 置信度 + 修复建议 + Gold Memory 历史提示)
 * 2. 连续失败计数(每个 cause 的累计次数,≥3 触发升级)
 * 3. 最近 GLM 验证判决(severity + issues + suggestions)
 *
 * 无数据时不渲染(返回 null),不占用布局空间。
 */
import { useState } from 'react';
import { useApp } from '../store';
import type { RcaInfo, VerifierVerdict } from '../types';
import { IconWarn, IconShield, IconBolt, IconCheck, IconChevronDown, IconX } from '../icons';

const CAUSE_LABEL: Record<string, string> = {
  reasoning_overflow: '推理溢出',
  syntax_error: '语法错误',
  missing_import: '缺失 import',
  verify_mismatch: '验收不匹配',
  design_violation: '设计违规',
  a11y_violation: '无障碍违规',
  timeout: '超时',
  max_iterations: '迭代上限',
  empty_output: '空输出',
  infra_failure: '基础设施故障',
  unknown: '未知',
};

function causeLabel(cause: string): string {
  return CAUSE_LABEL[cause] || cause;
}

function RcaCard({ info, index }: { info: RcaInfo; index: number }) {
  const [expanded, setExpanded] = useState(index === 0); // 最新一条默认展开
  const hasExtra = info.history_hint || info.related_rules.length > 0;
  return (
    <div className={'rca-item cause-' + info.cause}>
      <button
        type='button'
        className='rca-head'
        onClick={() => hasExtra && setExpanded((e) => !e)}
        disabled={!hasExtra}
      >
        <span className={'rca-cause cause-' + info.cause}>{causeLabel(info.cause)}</span>
        <span className='rca-conf'>{Math.round(info.confidence * 100)}%</span>
        {hasExtra && (
          <span className={'rca-chev' + (expanded ? ' open' : '')}>
            <IconChevronDown size={12} />
          </span>
        )}
      </button>
      {info.fix_suggestion && (
        <div className='rca-fix'>
          <IconBolt size={11} />
          <span>{info.fix_suggestion}</span>
        </div>
      )}
      {expanded && hasExtra && (
        <div className='rca-detail'>
          {info.detail && <div className='rca-detail-text'>{info.detail}</div>}
          {info.history_hint && (
            <div className='rca-history'>
              <IconShield size={11} />
              <span>{info.history_hint}</span>
            </div>
          )}
          {info.related_rules.length > 0 && (
            <div className='rca-rules'>
              {info.related_rules.map((r) => (
                <span key={r} className='rca-rule-chip'>{causeLabel(r)}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function VerdictCard({ verdict }: { verdict: VerifierVerdict }) {
  if (!verdict.checked) return null;
  const sev = verdict.severity;
  return (
    <div className={'verdict-card verdict-' + sev}>
      <div className='verdict-head'>
        <span className='verdict-sev'>
          {sev === 'blocker' && <IconX size={12} />}
          {sev === 'warning' && <IconWarn size={12} />}
          {sev === 'ok' && <IconCheck size={12} />}
          GLM 验证 · {sev === 'blocker' ? '阻断' : sev === 'warning' ? '警告' : '通过'}
        </span>
      </div>
      {verdict.issues.length > 0 && (
        <ul className='verdict-issues'>
          {verdict.issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      )}
      {verdict.suggestions.length > 0 && (
        <ul className='verdict-suggestions'>
          {verdict.suggestions.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FailurePanel() {
  const { rcaHistory, lastVerifierVerdict, failureCounter, clearRca } = useApp();

  const hasRca = rcaHistory.length > 0;
  const hasVerdict = lastVerifierVerdict && lastVerifierVerdict.checked;
  const counterEntries = Object.entries(failureCounter).filter(([, n]) => n > 0);
  const hasCounter = counterEntries.length > 0;

  if (!hasRca && !hasVerdict && !hasCounter) return null;

  return (
    <div className='failure-panel' data-testid='failure-panel'>
      <div className='failure-panel-head'>
        <IconWarn size={13} />
        <span className='fp-title'>失败根因分析</span>
        <button className='fp-clear' onClick={clearRca} title='清空'>
          <IconX size={11} />
        </button>
      </div>

      {hasCounter && (
        <div className='fp-counter'>
          <div className='fp-counter-label'>连续失败计数</div>
          <div className='fp-counter-chips'>
            {counterEntries.map(([cause, n]) => (
              <span
                key={cause}
                className={'counter-chip' + (n >= 3 ? ' escalated' : '')}
                title={n >= 3 ? '已触发策略升级(换模型/拆任务/降复杂度)' : ''}
              >
                {causeLabel(cause)} · {n}
              </span>
            ))}
          </div>
        </div>
      )}

      {hasVerdict && <VerdictCard verdict={lastVerifierVerdict!} />}

      {hasRca && (
        <div className='fp-rca-list'>
          {rcaHistory
            .slice()
            .reverse()
            .map((info, i) => (
              <RcaCard key={rcaHistory.length - 1 - i} info={info} index={i} />
            ))}
        </div>
      )}
    </div>
  );
}
