/**
 * FactoryPanel — 24h 自治 AI 代码工厂控制面板。
 *
 * 遵循 Codex 暗色设计系统（tokens.css）：
 * - 暗底 warm-neutral 画布，无品牌色，单色 active emphasis
 * - 功能色：green=verified, red=failed, orange=running, blue=info
 * - Bento Grid 风格卡片，16px gap，rounded-lg，hairline border
 * - 动效：stagger fade-in, hover lift translateY(-1px)
 */
import { useState } from "react";
import { useApp } from "../store";
import { formatWhen } from "../types";
import type { FactoryDetail, FactoryTask, TaskResult, FactorySummary } from "../types";
import {
  IconFactory,
  IconPlus,
  IconPlay,
  IconPause,
  IconRefresh,
  IconX,
  IconCheck,
  IconClock,
  IconCircleAlert,
  IconCheckCircle,
  IconBolt,
  IconHourglass,
  IconChevronLeft,
  IconChevronDown,
} from "../icons";

const STATUS_LABELS: Record<string, string> = {
  pending: "待启动",
  running: "运行中",
  paused: "已暂停",
  done: "已完成",
  error: "错误",
};

export function FactoryPanel() {
  const { factoryOpen, setFactoryOpen, factories, factoryDetail, selectFactory, createFactory, resumeFactory, pauseFactory, refreshFactories } = useApp();
  const [showCreate, setShowCreate] = useState(false);
  const [goal, setGoal] = useState("");
  const [cwd, setCwd] = useState("");
  const [maxTasks, setMaxTasks] = useState(5);

  if (!factoryOpen) return null;

  return (
    <div className="factory-overlay" data-testid="factory-panel">
      <header className="factory-head">
        <div className="factory-head-title">
          <IconFactory size={18} />
          <span>工厂</span>
        </div>
        <span className="spacer" />
        <button className="icon-btn ghost" title="刷新" onClick={() => refreshFactories()}>
          <IconRefresh size={15} />
        </button>
        <button className="icon-btn ghost" title="新建工厂" onClick={() => setShowCreate((v) => !v)}>
          <IconPlus size={16} />
        </button>
        <button className="icon-btn ghost" onClick={() => setFactoryOpen(false)} aria-label="关闭">
          <IconX size={16} />
        </button>
      </header>

      <div className="factory-body">
        {showCreate && (
          <CreateFactoryCard
            goal={goal}
            setGoal={setGoal}
            cwd={cwd}
            setCwd={setCwd}
            maxTasks={maxTasks}
            setMaxTasks={setMaxTasks}
            onSubmit={async () => {
              if (!goal.trim() || !cwd.trim()) return;
              await createFactory(goal.trim(), cwd.trim(), maxTasks);
              setShowCreate(false);
              setGoal("");
              setCwd("");
            }}
            onCancel={() => setShowCreate(false)}
          />
        )}

        {/* 详情视图 */}
        {factoryDetail ? (
          <FactoryDetailCard
            detail={factoryDetail}
            onResume={() => resumeFactory(factoryDetail.factory_id)}
            onPause={() => pauseFactory(factoryDetail.factory_id)}
            onBack={() => selectFactory("")}
          />
        ) : (
          <>
            {/* 工厂列表 */}
            <section className="factory-list-section">
              <div className="factory-sec-h">
                <span>活跃工厂</span>
                <span className="factory-count">{factories.length}</span>
              </div>
              {factories.length === 0 ? (
                <div className="factory-empty">
                  <IconFactory size={32} />
                  <p>暂无工厂</p>
                  <span>点击 + 创建一个 24h 自治代码工厂</span>
                </div>
              ) : (
                <div className="factory-list">
                  {factories.map((f, i) => (
                    <FactoryCard
                      key={f.factory_id}
                      summary={f}
                      index={i}
                      onClick={() => selectFactory(f.factory_id)}
                    />
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function CreateFactoryCard({
  goal, setGoal, cwd, setCwd, maxTasks, setMaxTasks, onSubmit, onCancel,
}: {
  goal: string; setGoal: (v: string) => void;
  cwd: string; setCwd: (v: string) => void;
  maxTasks: number; setMaxTasks: (v: number) => void;
  onSubmit: () => void; onCancel: () => void;
}) {
  return (
    <div className="factory-create" style={{ animationDelay: "0ms" }}>
      <h3 className="factory-create-title">新建工厂</h3>
      <label className="factory-field">
        <span>产品目标</span>
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="例：创建一个 Python 计算器库，含 add/sub/mul/div 和单元测试"
          rows={3}
          autoFocus
        />
      </label>
      <label className="factory-field">
        <span>工作目录</span>
        <input
          value={cwd}
          onChange={(e) => setCwd(e.target.value)}
          placeholder="/tmp/my-project"
        />
      </label>
      <label className="factory-field">
        <span>最大任务数</span>
        <input
          type="number"
          min={1}
          max={50}
          value={maxTasks}
          onChange={(e) => setMaxTasks(Number(e.target.value) || 5)}
        />
      </label>
      <div className="factory-create-actions">
        <button className="btn-primary" onClick={onSubmit} disabled={!goal.trim() || !cwd.trim()}>
          <IconPlay size={14} /> 启动工厂
        </button>
        <button className="btn-ghost" onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}

function FactoryCard({
  summary, index, onClick,
}: {
  summary: FactorySummary; index: number; onClick: () => void;
}) {
  const status = summary.status;
  const progress = summary.iteration_count;
  const total = summary.max_tasks;
  const pct = total > 0 ? Math.round((progress / total) * 100) : 0;

  return (
    <button
      className="factory-list-card"
      style={{ animationDelay: `${index * 60}ms` }}
      onClick={onClick}
    >
      <div className="flc-top">
        <span className={"flc-status-dot " + status} />
        <span className="flc-goal">{summary.product_goal.slice(0, 60) || "(未设定目标)"}</span>
      </div>
      <div className="flc-meta">
        <span className="flc-id">{summary.factory_id.slice(0, 12)}</span>
        <span className="flc-progress">
          {progress}/{total} 任务
        </span>
        <span className="flc-time">{formatWhen(summary.updated_at)}</span>
      </div>
      <div className="flc-bar">
        <div className="flc-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="flc-badge">{STATUS_LABELS[status] || status}</div>
    </button>
  );
}

function FactoryDetailCard({
  detail, onResume, onPause, onBack,
}: {
  detail: FactoryDetail;
  onResume: () => void; onPause: () => void; onBack: () => void;
}) {
  const { status } = detail;
  const done = detail.completed.length;
  const failed = detail.failed.length;
  const total = detail.roadmap.length;
  const running = detail.roadmap.filter((t) => t.status === "running").length;
  const pending = detail.roadmap.filter((t) => t.status === "pending").length;
  const pct = total > 0 ? Math.round(((done) / total) * 100) : 0;

  return (
    <div className="factory-detail">
      {/* 顶部信息 */}
      <div className="fd-header">
        <button className="btn-ghost sm" onClick={onBack}>
          <IconChevronLeft /> 返回
        </button>
        <div className="fd-header-info">
          <span className={"fd-status-badge " + status}>
            {status === "running" && <span className="pulse" />}
            {STATUS_LABELS[status] || status}
          </span>
          <span className="fd-id">{detail.factory_id.slice(0, 16)}</span>
        </div>
        <div className="fd-header-actions">
          {status === "running" && (
            <button className="btn-ghost sm" onClick={onPause}>
              <IconPause size={14} /> 暂停
            </button>
          )}
          {(status === "paused" || status === "error") && (
            <button className="btn-primary sm" onClick={onResume}>
              <IconPlay size={14} /> 恢复
            </button>
          )}
        </div>
      </div>

      {/* 产品目标 */}
      <div className="fd-goal">
        <IconBolt size={14} />
        <span>{detail.product_goal}</span>
      </div>

      {/* 指标 Bento Grid */}
      <div className="fd-bento">
        <MetricCard icon={<IconCheck size={16} />} label="已完成" value={done} tone="success" />
        <MetricCard icon={<IconX size={16} />} label="失败" value={failed} tone="danger" />
        <MetricCard icon={<IconClock size={16} />} label="执行中" value={running} tone="info" />
        <MetricCard icon={<IconHourglass size={16} />} label="待执行" value={pending} tone="muted" />
      </div>

      {/* 进度条 */}
      <div className="fd-progress">
        <div className="fd-progress-bar">
          <div className="fd-progress-fill" style={{ width: `${pct}%` }} />
        </div>
        <span className="fd-progress-text">
          {done}/{total} · {pct}%
        </span>
      </div>

      {/* 迭代信息 */}
      <div className="fd-iter">
        <span>迭代 {detail.iteration_count} / {detail.max_tasks}</span>
        <span>·</span>
        <span>{formatWhen(detail.updated_at)}</span>
        <span>·</span>
        <span className="fd-cwd">{detail.cwd}</span>
      </div>

      {/* Roadmap 任务列表 */}
      <div className="fd-sec-h">
        <IconFactory size={14} />
        <span>Roadmap</span>
      </div>
      <div className="fd-roadmap">
        {detail.roadmap.length === 0 && (
          <div className="fd-roadmap-empty">GLM planner 正在拆分任务…</div>
        )}
        {detail.roadmap.map((task, i) => (
          <TaskRow
            key={task.id}
            task={task}
            index={i}
            isCurrent={detail.current_task_id === task.id}
          />
        ))}
      </div>

      {/* 完成结果 */}
      {detail.completed.length > 0 && (
        <>
          <div className="fd-sec-h">
            <IconCheckCircle size={14} />
            <span>已完成任务</span>
          </div>
          <div className="fd-results">
            {detail.completed.map((r, i) => (
              <ResultRow key={r.task.id} result={r} index={i} ok />
            ))}
          </div>
        </>
      )}

      {/* 失败结果 */}
      {detail.failed.length > 0 && (
        <>
          <div className="fd-sec-h">
            <IconCircleAlert size={14} />
            <span>失败任务</span>
          </div>
          <div className="fd-results">
            {detail.failed.map((r, i) => (
              <ResultRow key={r.task.id} result={r} index={i} ok={false} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function MetricCard({
  icon, label, value, tone,
}: {
  icon: React.ReactNode; label: string; value: number; tone: "success" | "danger" | "info" | "muted";
}) {
  return (
    <div className={"fd-metric " + tone}>
      <span className="fd-metric-icon">{icon}</span>
      <span className="fd-metric-value">{value}</span>
      <span className="fd-metric-label">{label}</span>
    </div>
  );
}

function TaskRow({
  task, index, isCurrent,
}: {
  task: FactoryTask; index: number; isCurrent: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasFeedback = task.feedback && task.feedback.length > 0;
  const hasVerify = task.verify_cmd && task.verify_cmd.length > 0 && task.verify_cmd[0] !== "true";

  return (
    <div
      className={"fd-task" + (isCurrent ? " current" : "") + (expanded ? " expanded" : "")}
      style={{ animationDelay: `${index * 50}ms` }}
    >
      <button
        className="fd-task-head"
        onClick={() => (hasFeedback || hasVerify) && setExpanded((v) => !v)}
      >
        <span className={"fd-task-dot " + task.status} />
        <span className="fd-task-id">{task.id}</span>
        <span className="fd-task-desc">{task.description.slice(0, 80)}</span>
        {task.attempts > 1 && (
          <span className="fd-task-attempts" title="重试次数">
            <IconRefresh size={11} /> {task.attempts}
          </span>
        )}
        {(hasFeedback || hasVerify) && (
          <span className={"fd-task-chev" + (expanded ? " open" : "")}>
            <IconChevronDown />
          </span>
        )}
      </button>
      {expanded && (hasFeedback || hasVerify) && (
        <div className="fd-task-body">
          {hasVerify && (
            <div className="fd-task-verify">
              <span className="fd-task-label">验收命令</span>
              <code>{task.verify_cmd.join(" ")}</code>
            </div>
          )}
          {hasFeedback && (
            <div className="fd-task-feedback">
              <span className="fd-task-label">反馈</span>
              <p>{task.feedback}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResultRow({
  result, index, ok,
}: {
  result: TaskResult; index: number; ok: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      className={"fd-result " + (ok ? "ok" : "fail")}
      style={{ animationDelay: `${index * 50}ms` }}
    >
      <button className="fd-result-head" onClick={() => setExpanded((v) => !v)}>
        <span className={"fd-result-icon"}>
          {ok ? <IconCheck size={14} /> : <IconX size={14} />}
        </span>
        <span className="fd-result-id">{result.task.id}</span>
        <span className="fd-result-desc">{result.task.description.slice(0, 60)}</span>
        <span className="fd-result-iter">迭代 {result.iteration}</span>
        <span className="fd-result-stop">{result.stop_reason}</span>
        <span className={"fd-result-chev" + (expanded ? " open" : "")}>
          <IconChevronDown />
        </span>
      </button>
      {expanded && (
        <div className="fd-result-body">
          <p className="fd-result-summary">{result.summary}</p>
        </div>
      )}
    </div>
  );
}
