/** 自主循环实时计划清单卡（F4 · 可见脊柱）。
 *
 * orchestrator 每步把子任务累积成有序清单经 plan 事件推来,这里钉在对话流顶部,
 * 用状态图标(进行中/完成/重试/中止)让「拆→写→测→修→循环」可见,类 Devin/Qoder。 */
import { IconCheck, IconClock, IconHourglass, IconX } from '../icons';
import { useApp } from '../store';
import type { PlanStepStatus } from '../types';

const STATUS: Record<PlanStepStatus, string> = {
  running: '进行中',
  done: '完成',
  retry: '重试',
  aborted: '中止',
};

function StepIcon({ status }: { status: PlanStepStatus }) {
  if (status === 'done') return <IconCheck size={13} />;
  if (status === 'aborted') return <IconX size={13} />;
  if (status === 'retry') return <IconClock size={13} />;
  return <IconHourglass size={13} />;
}

export function PlanCard() {
  const { plan } = useApp();
  if (!plan || plan.steps.length === 0) return null;
  const doneCount = plan.steps.filter((s) => s.status === 'done').length;
  return (
    <div className="plan-card" data-testid="plan-card">
      <div className="plan-head">
        <span className="plan-title">计划</span>
        <span className="plan-count">
          {doneCount}/{plan.steps.length}
        </span>
        {plan.complete && <span className="plan-complete">已完成</span>}
      </div>
      <ol className="plan-steps">
        {plan.steps.map((s) => (
          <li key={s.index} className={`plan-step ${s.status}`}>
            <span className="plan-ico">
              <StepIcon status={s.status} />
            </span>
            <span className="plan-text">{s.text}</span>
            <span className="plan-badge">{STATUS[s.status]}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
