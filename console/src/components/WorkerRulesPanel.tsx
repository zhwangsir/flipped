import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchWorkerRules,
  createWorkerRule,
  updateWorkerRule,
  deleteWorkerRule,
  toggleWorkerRule,
  fetchWorkerRuleVersions,
  rollbackWorkerRules,
  autoGenerateWorkerRules,
  fetchWorkerRuleStats,
} from '../api';
import type { WorkerRule, WorkerRulesInfo, WorkerRuleVersion, WorkerRuleStatsData } from '../types';
import { IconWand } from '../icons';

// M194.7 — enabled 过滤三态:全部(不带 enabled 参数)/启用/停用
type EnabledFilter = 'all' | 'on' | 'off';
const FILTER_OPTIONS: { key: EnabledFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'on', label: '启用' },
  { key: 'off', label: '停用' },
];

export function WorkerRulesPanel() {
  const [info, setInfo] = useState<WorkerRulesInfo | null>(null);
  const [stats, setStats] = useState<WorkerRuleStatsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [newText, setNewText] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [versions, setVersions] = useState<WorkerRuleVersion[]>([]);
  const [rollbackTarget, setRollbackTarget] = useState<number | null>(null);
  const [autoNote, setAutoNote] = useState<{ text: string; ok: boolean } | null>(null);
  // M194.7 — 服务端排序/过滤:sort=priority + enabled 走查询参数;
  // 服务端失败/不支持 → 回落全量拉取 + 本地排序/过滤(ref 置 false 后不再带参)
  const [enabledFilter, setEnabledFilter] = useState<EnabledFilter>('all');
  const serverQueryRef = useRef(true);

  const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

  const fetchAll = useCallback(async () => {
    const params = serverQueryRef.current
      ? {
          sort: 'priority' as const,
          ...(enabledFilter !== 'all' ? { enabled: enabledFilter === 'on' } : {}),
        }
      : undefined;
    try {
      const [r, s] = await Promise.all([fetchWorkerRules(params), fetchWorkerRuleStats()]);
      setInfo(r);
      setStats(s);
      setError(null);
    } catch (e) {
      if (!serverQueryRef.current) {
        setError(errText(e));
        return;
      }
      // M194.7 — 回落:无参全量拉取(本地排序/过滤兜底,现状行为不回归)
      try {
        const [r2, s2] = await Promise.all([fetchWorkerRules(), fetchWorkerRuleStats()]);
        if (!r2 || !Array.isArray(r2.rules)) throw e;
        serverQueryRef.current = false;
        setInfo(r2);
        setStats(s2);
        setError(null);
      } catch {
        setError(errText(e));
      }
    }
  }, [enabledFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await fetchAll();
    } finally {
      setLoading(false);
    }
  }, [fetchAll]);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = async () => {
    await fetchAll();
  };

  const onToggle = async (rule: WorkerRule) => {
    const next = !rule.enabled;
    // 乐观更新
    setInfo((prev) =>
      prev ? { ...prev, rules: prev.rules.map((rr) => (rr.id === rule.id ? { ...rr, enabled: next } : rr)) } : prev
    );
    try {
      await toggleWorkerRule(rule.id, next);
    } catch {
      // 失败回滚
      setInfo((prev) =>
        prev ? { ...prev, rules: prev.rules.map((rr) => (rr.id === rule.id ? { ...rr, enabled: rule.enabled } : rr)) } : prev
      );
    }
  };

  const startEdit = (rule: WorkerRule) => {
    setEditingId(rule.id);
    setEditText(rule.text);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditText('');
  };

  const saveEdit = async (rule: WorkerRule) => {
    await updateWorkerRule(rule.id, { text: editText, scope: rule.scope, priority: rule.priority });
    setEditingId(null);
    setEditText('');
    await refresh();
  };

  const confirmDel = (id: string) => setConfirmDeleteId(id);
  const cancelDel = () => setConfirmDeleteId(null);
  const doDelete = async (id: string) => {
    await deleteWorkerRule(id);
    setConfirmDeleteId(null);
    await refresh();
  };

  const addRule = async () => {
    const t = newText.trim();
    if (!t) return;
    await createWorkerRule(t, 'worker', 50);
    setNewText('');
    await refresh();
  };

  const autoGen = async () => {
    setAutoNote(null);
    try {
      const r = await autoGenerateWorkerRules();
      if (r.added.length > 0) {
        setAutoNote({ text: `新增 ${r.added.length} 条规则`, ok: true });
      } else {
        setAutoNote({ text: '无新候选', ok: false });
      }
      await refresh();
    } catch (e) {
      setAutoNote({ text: errText(e), ok: false });
    }
  };

  const toggleVersions = async () => {
    const next = !versionsOpen;
    setVersionsOpen(next);
    if (next && versions.length === 0) {
      try {
        const v = await fetchWorkerRuleVersions();
        setVersions(v);
      } catch {
        /* ignore */
      }
    }
  };

  const askRollback = (v: number) => setRollbackTarget(v);
  const cancelRollback = () => setRollbackTarget(null);
  const doRollback = async (v: number) => {
    await rollbackWorkerRules(v);
    setRollbackTarget(null);
    await refresh();
  };

  if (loading && !info) {
    return (
      <div className="side-empty" data-testid="wrules-panel">
        加载中…
      </div>
    );
  }
  if (error && !info) {
    return (
      <div className="side-empty" data-testid="wrules-panel">
        <div>加载失败：{error}</div>
        <button className="rdiff-refresh" onClick={() => load()}>
          重试
        </button>
      </div>
    );
  }

  // M194.7 — 服务端通路:列表已被服务端排序/过滤,直接渲染;
  // 回落通路(serverQueryRef=false):本地 priority desc 排序 + enabled 过滤(现状行为)
  const allRules = info?.rules ?? [];
  const rules = serverQueryRef.current
    ? allRules
    : allRules
        .filter((r) => (enabledFilter === 'all' ? true : enabledFilter === 'on' ? r.enabled : !r.enabled))
        .slice()
        .sort((a, b) => b.priority - a.priority);

  // M185.2：成功率 = success/(success+failure)（同单位 verify 次）；
  // 旧公式 success/applied 分母分子不同单位（L-M183-3）。零 outcome → -1（效果未评）。
  const successRate = (id: string) => {
    const s = stats?.stats[id];
    if (!s) return -1;
    const outcomes = s.success + s.failure;
    if (outcomes === 0) return -1;
    return s.success / outcomes;
  };

  const statClass = (rate: number) => {
    if (rate < 0) return 'muted';
    if (rate >= 0.8) return 'ok';
    if (rate >= 0.5) return 'amber';
    return 'danger';
  };

  return (
    <div className="wrules" data-testid="wrules-panel">
      <div className="wrules-head">
        <span className="wrules-title">
          Worker 规则 {info?.version != null && <span className="wrules-ver">v{info.version}</span>}
        </span>
        <div className="wrules-filter" data-testid="wrules-filter">
          {FILTER_OPTIONS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={'wrules-filter-btn' + (enabledFilter === key ? ' active' : '')}
              onClick={() => setEnabledFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <button className="rdiff-refresh" data-testid="wrules-auto" onClick={autoGen}>
          <IconWand size={12} /> 自动生成
        </button>
        <button className="rdiff-refresh" onClick={toggleVersions}>
          版本史
        </button>
      </div>
      {autoNote && <div className={`wrules-note ${autoNote.ok ? 'ok' : 'muted'}`}>{autoNote.text}</div>}

      <div className="wrules-new">
        <textarea
          className="wrules-textarea"
          placeholder="新规则…"
          value={newText}
          onChange={(e) => setNewText(e.target.value)}
          rows={2}
        />
        <button className="rdiff-refresh" data-testid="wrules-add" disabled={!newText.trim()} onClick={addRule}>
          添加
        </button>
      </div>

      {versionsOpen && (
        <div className="wrules-versions" data-testid="wrules-versions">
          {versions.map((v) => (
            <div className="wrules-vrow" key={v.version}>
              <span className="mono">v{v.version}</span>
              <span>{v.action}</span>
              <span>{v.detail}</span>
              <span>{v.rule_count} 条</span>
              <button className="rdiff-refresh" data-testid={`rollback-${v.version}`} onClick={() => askRollback(v.version)}>
                回滚
              </button>
              {rollbackTarget === v.version && (
                <div className="wrules-confirm">
                  <span>回滚到 v{v.version}?</span>
                  <button className="rdiff-confirm-danger" data-testid={`confirm-rollback-${v.version}`} onClick={() => doRollback(v.version)}>
                    确认
                  </button>
                  <button className="rdiff-revert" data-testid={`cancel-rollback-${v.version}`} onClick={cancelRollback}>
                    取消
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="wrules-list">
        {rules.map((r) => {
          const rate = successRate(r.id);
          const sClass = statClass(rate);
          const s = stats?.stats[r.id];
          return (
            <div className="wrules-row" data-testid={`wrule-${r.id}`} key={r.id}>
              <div className="wrules-main">
                <input
                  type="checkbox"
                  data-testid={`toggle-${r.id}`}
                  checked={r.enabled}
                  onChange={() => onToggle(r)}
                />
                <span className={`wrules-source ${r.source === 'auto' ? 'purple' : 'blue'}`}>{r.source}</span>
                <span className="wrules-priority">{r.priority}</span>
                {editingId === r.id ? (
                  <div className="wrules-edit">
                    <textarea
                      className="wrules-textarea"
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      rows={2}
                    />
                    <button className="rdiff-refresh" data-testid={`save-edit-${r.id}`} onClick={() => saveEdit(r)}>
                      保存
                    </button>
                    <button className="rdiff-refresh" data-testid={`cancel-edit-${r.id}`} onClick={cancelEdit}>
                      取消
                    </button>
                  </div>
                ) : (
                  <span className="wrules-text">{r.text}</span>
                )}
              </div>
              <div className="wrules-actions">
                {editingId !== r.id && (
                  <button className="rdiff-refresh" data-testid={`edit-${r.id}`} onClick={() => startEdit(r)}>
                    编辑
                  </button>
                )}
                <button className="rdiff-refresh" data-testid={`del-${r.id}`} onClick={() => confirmDel(r.id)}>
                  删除
                </button>
              </div>
              {confirmDeleteId === r.id && (
                <div className="wrules-confirm">
                  <span>确认删除该规则?</span>
                  <button className="rdiff-confirm-danger" onClick={() => doDelete(r.id)}>
                    确认
                  </button>
                  <button className="rdiff-revert" onClick={cancelDel}>
                    取消
                  </button>
                </div>
              )}
              <div className={`wrules-stat ${sClass}`} data-testid={`stat-${r.id}`}>
                {s && s.applied > 0 ? (
                  <>
                    应用 {s.applied} · 成功 {s.success} · 失败 {s.failure}
                    {rate >= 0 && (
                      <div className={`wrules-bar ${sClass}`} style={{ width: `${Math.round(rate * 100)}%` }} />
                    )}
                  </>
                ) : (
                  <span>未应用</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {/* M185.2：语义注记（stats.semantics，缺省本地兜底）防误读成功率口径 */}
      <div className="wrules-semantics muted" data-testid="wrules-semantics">
        {stats?.semantics ||
          'applied=规则注入次数；success/failure=verify 通过/失败次数；success_rate=success/(success+failure)，规则效果=降低失败迭代数，非端到端任务成功率直接度量'}
      </div>
    </div>
  );
}
