import { useEffect, useState } from "react";
import { useApp } from "../store";
import { formatFuture } from "../types";
import type { ScheduledTask } from "../types";
import { IconClock, IconPlus } from "../icons";

/** M178.2 — 「已安排」任务管理视图：行内新建表单 + 任务卡列表 + 30s 自动刷新。 */
export function ScheduledView() {
  const { tasks, loadTasks } = useApp();
  const [formOpen, setFormOpen] = useState(false);

  // 进视图拉一次，之后 30s 自动刷新（组件卸载清 interval）
  useEffect(() => {
    void loadTasks();
    const id = setInterval(() => void loadTasks(), 30000);
    return () => clearInterval(id);
  }, [loadTasks]);

  return (
    <div className="sched-view">
      <div className="sched-head">
        <button className="sched-new" onClick={() => setFormOpen((v) => !v)}>
          <IconPlus size={13} /> 新建任务
        </button>
      </div>
      {formOpen && <TaskForm onClose={() => setFormOpen(false)} />}
      {tasks.length === 0 ? (
        <div className="side-empty tall scheduled-empty">
          <span className="scheduled-empty-icon">
            <IconClock size={22} />
          </span>
          <span className="scheduled-empty-title">暂无已安排任务</span>
          <span className="scheduled-empty-hint">在此处规划的任务将自动出现在这里</span>
        </div>
      ) : (
        tasks.map((t) => <TaskCard key={t.id} task={t} />)
      )}
    </div>
  );
}

/** 行内新建表单：标题/prompt/kind/运行时间(或间隔分钟)/mode，提交中 disable，失败红字提示。 */
function TaskForm({ onClose }: { onClose: () => void }) {
  const { addTask } = useApp();
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [kind, setKind] = useState<"once" | "interval">("once");
  const [runAt, setRunAt] = useState("");
  const [every, setEvery] = useState("30");
  const [mode, setMode] = useState("chat");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!title.trim() || !prompt.trim()) {
      setError("标题与任务内容不能为空");
      return;
    }
    if (kind === "once" && !runAt) {
      setError("请选择运行时间");
      return;
    }
    const minutes = Number(every);
    if (kind === "interval" && (!Number.isInteger(minutes) || minutes < 1)) {
      setError("请输入不小于 1 的分钟数");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await addTask({
        title: title.trim(),
        prompt: prompt.trim(),
        mode,
        kind,
        run_at: kind === "once" ? new Date(runAt).toISOString() : null,
        every_minutes: kind === "interval" ? minutes : null,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="sched-form">
      <input
        className="sched-input"
        placeholder="任务标题"
        aria-label="任务标题"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <textarea
        className="sched-input"
        placeholder="任务内容（到点自动派发）"
        aria-label="任务内容"
        rows={3}
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
      />
      <select
        className="sched-input"
        aria-label="任务类型"
        value={kind}
        onChange={(e) => setKind(e.target.value as "once" | "interval")}
      >
        <option value="once">一次性</option>
        <option value="interval">每隔 N 分钟</option>
      </select>
      {kind === "once" ? (
        <input
          className="sched-input"
          type="datetime-local"
          aria-label="运行时间"
          value={runAt}
          onChange={(e) => setRunAt(e.target.value)}
        />
      ) : (
        <input
          className="sched-input"
          type="number"
          min={1}
          aria-label="间隔分钟"
          value={every}
          onChange={(e) => setEvery(e.target.value)}
        />
      )}
      <select
        className="sched-input"
        aria-label="运行模式"
        value={mode}
        onChange={(e) => setMode(e.target.value)}
      >
        <option value="chat">chat</option>
        <option value="agent">agent</option>
      </select>
      <div className="sched-form-acts">
        <button className="sched-act primary" disabled={submitting} onClick={() => void submit()}>
          {submitting ? "创建中…" : "创建"}
        </button>
        <button className="sched-act" disabled={submitting} onClick={onClose}>
          取消
        </button>
      </div>
      {error && (
        <div className="sched-form-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

/** 单张任务卡：标题(可点击跳上次会话)/徽标/下次运行/上次状态/启停/删除(二次确认)。 */
function TaskCard({ task }: { task: ScheduledTask }) {
  const { removeTask, toggleTaskEnabled, selectSession } = useApp();
  const [confirming, setConfirming] = useState(false);
  const next = !task.enabled ? "已停用" : task.next_run_at ? formatFuture(task.next_run_at) : "—";

  return (
    <div className="sched-card">
      <div className="sched-card-head">
        {task.last_session_id ? (
          <button
            className="sched-title link"
            title="打开上次会话"
            onClick={() => selectSession(task.last_session_id as string)}
          >
            {task.title}
          </button>
        ) : (
          <span className="sched-title">{task.title}</span>
        )}
      </div>
      <div className="sched-badges">
        <span className="sched-badge">
          {task.kind === "once" ? "一次性" : `每 ${task.every_minutes} 分钟`}
        </span>
        <span className="sched-badge">{task.mode}</span>
      </div>
      <div className="sched-meta">
        {task.last_status && (
          <span
            className={"dot " + (task.last_status === "done" ? "ok" : task.last_status)}
            title={`上次：${task.last_status}`}
          />
        )}
        <span>下次：{next}</span>
        <span>已运行 {task.run_count} 次</span>
      </div>
      <div className="sched-actions">
        <button
          className="sched-act"
          onClick={() => {
            // M146：失败静默（不假装切换成功），与 deleteSession 同模式
            toggleTaskEnabled(task.id, !task.enabled).catch(() => {});
          }}
        >
          {task.enabled ? "停用" : "启用"}
        </button>
        {confirming ? (
          <>
            <span className="sched-confirm">确认删除？</span>
            <button
              className="sched-act danger"
              onClick={() => {
                removeTask(task.id)
                  .catch(() => {})
                  .finally(() => setConfirming(false));
              }}
            >
              确认
            </button>
            <button className="sched-act" onClick={() => setConfirming(false)}>
              取消
            </button>
          </>
        ) : (
          <button className="sched-act danger" onClick={() => setConfirming(true)}>
            删除
          </button>
        )}
      </div>
    </div>
  );
}
