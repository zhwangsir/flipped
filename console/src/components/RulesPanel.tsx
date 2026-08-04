import { useCallback, useEffect, useState } from 'react';
import { fetchProjectRules, saveProjectRules } from '../api';
import type { ProjectRulesInfo } from '../types';
import { renderMarkdown } from '../lib/markdown';
import { IconFile } from '../icons';

/**
 * M180 — 项目规则面板(对标 ZCode 规则系统)。
 * 查看态渲染多文件拼接 markdown + files 徽标;编辑态行内编辑 .flipped/rules.md。
 * 不经 store,直接调 api.ts 自取数(useState + useEffect),与 ProjectMapPanel 范式同构。
 * 全部只读渲染 + 显式保存,无任何隐式写。
 */
export function RulesPanel() {
  const [info, setInfo] = useState<ProjectRulesInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchProjectRules();
      setInfo(res);
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const startEdit = () => {
    setDraft(info?.rules_content ?? '');
    setError(null);
    setEditing(true);
  };

  const cancel = () => {
    setEditing(false);
    setError(null);
  };

  const save = async () => {
    if (saving) return; // busy 态防连点
    setSaving(true);
    setError(null);
    try {
      const res = await saveProjectRules(draft);
      setInfo(res);
      setEditing(false);
    } catch (e) {
      setError(errText(e)); // 保存失败不收起编辑态
    } finally {
      setSaving(false);
    }
  };

  if (loading && !info) {
    return <div className="side-empty">加载规则…</div>;
  }
  if (error && !info) {
    return (
      <div className="side-empty">
        <div>规则加载失败：{error}</div>
        <button className="rdiff-refresh rules-retry" onClick={() => load()}>
          重试
        </button>
      </div>
    );
  }
  if (!info || info.needs_project) {
    return <div className="side-empty">未选择项目 · 在底部「选择项目」导入或新建</div>;
  }

  const hasFiles = info.files.length > 0;

  return (
    <div className="rules">
      <div className="file-head">
        <IconFile size={13} /> 项目规则
        {info.files.map((f) => (
          <span key={f} className="chip rules-chip">
            {f}
          </span>
        ))}
        {!editing && hasFiles && (
          <button className="rdiff-refresh" onClick={startEdit} title="编辑 .flipped/rules.md">
            编辑
          </button>
        )}
      </div>
      {error && <div className="rules-err">{error}</div>}
      {editing ? (
        <>
          <div className="rules-edit-hint">编辑 .flipped/rules.md — 规则将注入每次对话，Agent 须遵守</div>
          <textarea
            className="rules-textarea"
            value={draft}
            spellCheck={false}
            placeholder={'# 项目规则\n\n例如：组件一律函数式；禁止提交 console.log；样式变量复用 app.css'}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="rules-actions">
            <button className="rdiff-refresh" onClick={save} disabled={saving}>
              {saving ? '保存中…' : '保存'}
            </button>
            <button className="rdiff-refresh" onClick={cancel} disabled={saving}>
              取消
            </button>
          </div>
        </>
      ) : hasFiles ? (
        <div className="md-doc">{renderMarkdown(info.markdown)}</div>
      ) : (
        <div className="rules-empty">
          <div>暂无规则</div>
          <div className="rules-empty-sub">
            在这里写下的项目规则（代码风格、禁区、项目惯例）将注入每次对话，Agent 全模式遵守。
          </div>
          <button className="rdiff-refresh" onClick={startEdit}>
            新建规则
          </button>
        </div>
      )}
    </div>
  );
}
