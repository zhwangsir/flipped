/**
 * FactoryPanel — 24h 自治 AI 代码工厂控制面板。
 *
 * 遵循 Codex 暗色设计系统（tokens.css）：
 * - 暗底 warm-neutral 画布，无品牌色，单色 active emphasis
 * - 功能色：green=verified, red=failed, orange=running, blue=info
 * - Bento Grid 风格卡片，16px gap，rounded-lg，hairline border
 * - 动效：stagger fade-in, hover lift translateY(-1px)
 */
import { useEffect, useState } from "react";
import { useApp } from "../store";
import { navigate } from "../router";
import { formatWhen } from "../types";
import type { FactoryDetail, FactoryTask, TaskResult, FactorySummary, FactoryRcaEntry } from "../types";
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
  IconShield,
  IconSparkle,
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
  // M146 P1：启动/暂停/恢复失败此前静默（unhandled rejection），用户以为操作成功
  const [createBusy, setCreateBusy] = useState(false);
  const [createErr, setCreateErr] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [actionErr, setActionErr] = useState("");

  // D-0012 修复：overlay 挂载时绑 document keydown Escape → 关闭面板。
  // 与 Settings.tsx D-0010 修复同模式（document 级监听，无需焦点落在面板内）。
  // 关闭动作与关闭按钮一致：navigate("assistant") 切回主路由 + setFactoryOpen(false)。
  useEffect(() => {
    if (!factoryOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        navigate("assistant");
        setFactoryOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [factoryOpen, setFactoryOpen]);

  if (!factoryOpen) return null;

  const errText = (e: unknown) =>
    e instanceof Error ? e.message.replace(/^HTTP \d+: /, "") : "操作失败，请重试";

  const submitCreate = async () => {
    if (!goal.trim() || !cwd.trim() || createBusy) return;
    setCreateBusy(true);
    setCreateErr("");
    try {
      await createFactory(goal.trim(), cwd.trim(), maxTasks);
      setShowCreate(false);
      setGoal("");
      setCwd("");
    } catch (e) {
      setCreateErr(errText(e));
    } finally {
      setCreateBusy(false);
    }
  };

  const runAction = async (fn: () => Promise<void>) => {
    if (actionBusy) return;
    setActionBusy(true);
    setActionErr("");
    try {
      await fn();
    } catch (e) {
      setActionErr(errText(e));
    } finally {
      setActionBusy(false);
    }
  };

  return (
    <div
      className="factory-overlay"
      data-testid="factory-panel"
      role="dialog"
      aria-modal="true"
      aria-label="工厂面板"
    >
      {/* D-0007 修复：<header> → <div>：避免与 TopBar 的 <header className="topbar">
          形成 landmark-unique 冲突（两个 banner landmark）。factory-head 仅作样式容器。 */}
      <div className="factory-head">
        <div className="factory-head-title">
          <IconFactory size={18} />
          <span>工厂</span>
        </div>
        <span className="spacer" />
        <button className="icon-btn ghost" title="刷新" onClick={() => refreshFactories()}>
          <IconRefresh size={15} />
        </button>
        <button className="icon-btn ghost" title="新建工厂" onClick={() => { setShowCreate((v) => !v); setCreateErr(""); }}>
          <IconPlus size={16} />
        </button>
        <button className="icon-btn ghost" onClick={() => { navigate("assistant"); setFactoryOpen(false); }} aria-label="关闭">
          <IconX size={16} />
        </button>
      </div>

      <div className="factory-body">
        {showCreate && (
          <CreateFactoryCard
            goal={goal}
            setGoal={setGoal}
            cwd={cwd}
            setCwd={setCwd}
            maxTasks={maxTasks}
            setMaxTasks={setMaxTasks}
            busy={createBusy}
            err={createErr}
            onSubmit={submitCreate}
            onCancel={() => setShowCreate(false)}
          />
        )}

        {/* 详情视图 */}
        {factoryDetail ? (
          <FactoryDetailCard
            detail={factoryDetail}
            onResume={() => runAction(() => resumeFactory(factoryDetail.factory_id))}
            onPause={() => runAction(() => pauseFactory(factoryDetail.factory_id))}
            onBack={() => selectFactory("")}
            actionBusy={actionBusy}
            actionErr={actionErr}
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
  goal, setGoal, cwd, setCwd, maxTasks, setMaxTasks, busy, err, onSubmit, onCancel,
}: {
  goal: string; setGoal: (v: string) => void;
  cwd: string; setCwd: (v: string) => void;
  maxTasks: number; setMaxTasks: (v: number) => void;
  busy: boolean; err: string;
  onSubmit: () => void; onCancel: () => void;
}) {
  return (
    <div className="factory-create" style={{ animationDelay: "0ms" }}>
      {/* D-0008 修复：h3 → h2，让新建表单标题成为面板内首级标题，
          满足 axe-core heading-order 规则（不跳级）。 */}
      <h2 className="factory-create-title">新建工厂</h2>
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
      {err && <div className="form-err" role="alert" data-testid="factory-create-error">{err}</div>}
      <div className="factory-create-actions">
        <button className="btn-primary" onClick={onSubmit} disabled={!goal.trim() || !cwd.trim() || busy}>
          <IconPlay size={14} /> {busy ? "启动中…" : "启动工厂"}
        </button>
        <button className="btn-ghost" onClick={onCancel} disabled={busy}>取消</button>
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
  detail, onResume, onPause, onBack, actionBusy = false, actionErr = "",
}: {
  detail: FactoryDetail;
  onResume: () => void; onPause: () => void; onBack: () => void;
  actionBusy?: boolean; actionErr?: string;
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
            <button className="btn-ghost sm" onClick={onPause} disabled={actionBusy}>
              <IconPause size={14} /> {actionBusy ? "处理中…" : "暂停"}
            </button>
          )}
          {(status === "paused" || status === "error") && (
            <button className="btn-primary sm" onClick={onResume} disabled={actionBusy}>
              <IconPlay size={14} /> {actionBusy ? "处理中…" : "恢复"}
            </button>
          )}
        </div>
      </div>
      {actionErr && <div className="form-err" role="alert" data-testid="factory-action-error">{actionErr}</div>}

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
            key={`${task.id}-${i}`}
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
              <ResultRow key={`done-${r.task.id}-${i}`} result={r} index={i} ok />
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
              <ResultRow key={`fail-${r.task.id}-${i}`} result={r} index={i} ok={false} />
            ))}
          </div>
        </>
      )}

      {/* M100 — 工厂级 RCA 历史聚合折叠区 */}
      <FactoryRcaHistorySection factoryId={detail.factory_id} />

      {/* M135-B — 工厂质量趋势折叠区 */}
      <FactoryQualityTrendSection factoryId={detail.factory_id} />
    </div>
  );
}

/**
 * M100 — 工厂级 RCA 历史聚合折叠区。
 * 默认折叠;展开时显示 cause_stats chips + 时间线列表。
 * 数据来源 store.factoryRcaHistory(selectFactory 时已预拉取),展开时再主动刷新一次。
 */
function FactoryRcaHistorySection({ factoryId }: { factoryId: string }) {
  const { factoryRcaHistory, loadFactoryRcaHistory } = useApp();
  const [expanded, setExpanded] = useState(false);

  const entries = factoryRcaHistory?.rca_history ?? [];
  const causeStats = factoryRcaHistory?.cause_stats ?? {};
  const total = entries.length;
  const causeKeys = Object.keys(causeStats).sort((a, b) => causeStats[b] - causeStats[a]);

  const onToggle = () => {
    const next = !expanded;
    setExpanded(next);
    // 展开时主动刷新一次,保证最新(fail-open)
    if (next) loadFactoryRcaHistory(factoryId);
  };

  return (
    <>
      <button
        className="fd-sec-h fd-rca-toggle"
        onClick={onToggle}
        aria-expanded={expanded}
        type="button"
      >
        <IconShield size={14} />
        <span>RCA 历史</span>
        <span className="fd-rca-badge">{total}</span>
        <span className="spacer" />
        <span className={"fd-rca-chev" + (expanded ? " open" : "")}>
          <IconChevronDown size={14} />
        </span>
      </button>
      {expanded && (
        <div className="fd-rca-body">
          {/* 空态占位 */}
          {total === 0 ? (
            <div className="fd-rca-empty">暂无 RCA 历史(verify 未触发失败或未命中 RCA)</div>
          ) : (
            <>
              {/* cause_stats chips */}
              {causeKeys.length > 0 && (
                <div className="fd-rca-chips">
                  {causeKeys.map((k) => (
                    <span key={k} className="counter-chip">
                      {k} · {causeStats[k]}
                    </span>
                  ))}
                </div>
              )}
              {/* 时间线列表(倒序,最新在上) */}
              <div className="fd-rca-timeline">
                {[...entries].reverse().map((e, i) => (
                  <FactoryRcaRow key={`${e.timestamp}-${i}`} entry={e} index={entries.length - i} />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}

/** M100 — 单条工厂级 RCA 历史项(可展开看 fix_suggestion / history_hint)。 */
function FactoryRcaRow({
  entry, index,
}: {
  entry: FactoryRcaEntry; index: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = !!(entry.fix_suggestion || entry.history_hint || entry.related_rules.length);
  const pct = Math.round((entry.confidence || 0) * 100);

  return (
    <div
      className={"fd-rca-item" + (expanded ? " expanded" : "")}
      style={{ animationDelay: `${index * 40}ms` }}
    >
      <button
        className="fd-rca-item-head"
        onClick={() => hasDetail && setExpanded((v) => !v)}
        type="button"
      >
        <span className={"fd-rca-cause " + entry.cause}>{entry.cause}</span>
        <span className="fd-rca-conf" title="置信度">{pct}%</span>
        {entry.task_index >= 0 && (
          <span className="fd-rca-task" title="失败任务索引">#{entry.task_index}</span>
        )}
        <span className="fd-rca-time">{formatWhen(entry.timestamp)}</span>
        {hasDetail && (
          <span className={"fd-rca-chev" + (expanded ? " open" : "")}>
            <IconChevronDown size={13} />
          </span>
        )}
      </button>
      {expanded && hasDetail && (
        <div className="fd-rca-item-body">
          {entry.fix_suggestion && (
            <p className="fd-rca-fix">
              <span className="fd-rca-label">建议</span>
              {entry.fix_suggestion}
            </p>
          )}
          {entry.history_hint && (
            <p className="fd-rca-hint">
              <span className="fd-rca-label">历史</span>
              {entry.history_hint}
            </p>
          )}
          {entry.related_rules.length > 0 && (
            <p className="fd-rca-rules">
              <span className="fd-rca-label">规则</span>
              {entry.related_rules.join(", ")}
            </p>
          )}
        </div>
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

/**
 * M135-B — 工厂质量趋势折叠区。
 * 默认折叠;展开时显示趋势方向 badge + 最新评级 + 历史分数迷你曲线(纯 CSS bar chart)。
 * 数据来源 store.factoryQualityTrend(selectFactory 时已预拉取),展开时再主动刷新一次。
 */
function FactoryQualityTrendSection({ factoryId }: { factoryId: string }) {
  const { factoryQualityTrend, loadFactoryQualityTrend } = useApp();
  const [expanded, setExpanded] = useState(false);

  const trend = factoryQualityTrend?.trend;
  const history = factoryQualityTrend?.history ?? [];
  const total = history.length;

  const onToggle = () => {
    const next = !expanded;
    setExpanded(next);
    // 展开时主动刷新一次,保证最新(fail-open)
    if (next) loadFactoryQualityTrend(factoryId);
  };

  // 趋势方向 → 中文 + 样式类
  const directionMeta: Record<string, { label: string; cls: string }> = {
    improving: { label: "持续提升", cls: "improving" },
    stable: { label: "保持稳定", cls: "stable" },
    degrading: { label: "有所下降", cls: "degrading" },
    insufficient_data: { label: "数据不足", cls: "muted" },
    unknown: { label: "未知", cls: "muted" },
  };
  const dirMeta = directionMeta[trend?.direction ?? "insufficient_data"] ?? directionMeta.insufficient_data;

  return (
    <>
      <button
        className="fd-sec-h fd-quality-toggle"
        onClick={onToggle}
        aria-expanded={expanded}
        type="button"
      >
        <IconSparkle size={14} />
        <span>质量趋势</span>
        <span className="fd-quality-badge">{total}</span>
        {trend?.latest_grade && (
          <span className={"fd-quality-grade grade-" + trend.latest_grade.toLowerCase()}>
            {trend.latest_grade}
          </span>
        )}
        <span className="spacer" />
        <span className={"fd-quality-chev" + (expanded ? " open" : "")}>
          <IconChevronDown size={14} />
        </span>
      </button>
      {expanded && (
        <div className="fd-quality-body">
          {/* 空态占位 */}
          {total === 0 ? (
            <div className="fd-quality-empty">暂无质量数据(task 完成后自动打分)</div>
          ) : (
            <>
              {/* 趋势概要 */}
              <div className="fd-quality-summary">
                <span className={"fd-quality-direction " + dirMeta.cls}>{dirMeta.label}</span>
                {trend?.delta !== undefined && trend.delta !== 0 && (
                  <span className="fd-quality-delta">
                    {trend.delta > 0 ? "+" : ""}{trend.delta.toFixed(1)} 分
                  </span>
                )}
                {trend?.latest_overall !== undefined && (
                  <span className="fd-quality-overall">最新 {trend.latest_overall.toFixed(0)} 分</span>
                )}
              </div>
              {/* 迷你曲线(纯 CSS bar chart,最近 20 条) */}
              <div className="fd-quality-chart" role="img" aria-label="质量分数趋势图">
                {history.slice(-20).map((entry, i) => {
                  const score = entry.score?.overall ?? 0;
                  const height = Math.max(4, Math.min(100, score));
                  const grade = entry.score?.grade ?? "C";
                  return (
                    <div
                      key={`${entry.task_id}-${i}`}
                      className={"fd-quality-bar grade-" + grade.toLowerCase()}
                      style={{ height: `${height}%` }}
                      title={`${entry.task_id}: ${score.toFixed(0)} 分 (${grade})`}
                    />
                  );
                })}
              </div>
              {/* 维度明细(最新一条) */}
              {history.length > 0 && (() => {
                const latest = history[history.length - 1]?.score;
                if (!latest) return null;
                const dims: Array<[string, number]> = [
                  ["功能", latest.functionality],
                  ["代码", latest.code_quality],
                  ["设计", latest.design],
                  ["可维护", latest.maintainability],
                  ["性能", latest.performance],
                ];
                return (
                  <div className="fd-quality-dims">
                    {dims.map(([label, val]) => (
                      <div key={label} className="fd-quality-dim">
                        <span className="fd-quality-dim-label">{label}</span>
                        <span className={"fd-quality-dim-val" + (val >= 85 ? " high" : val < 70 ? " low" : "")}>
                          {val.toFixed(0)}
                        </span>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </>
          )}
        </div>
      )}
    </>
  );
}
