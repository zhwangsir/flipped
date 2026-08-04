import { useCallback, useEffect, useState } from 'react';
import { fetchProjectMap, regenerateProjectMap } from '../api';
import type { ProjectMapInfo } from '../types';
import { renderMarkdown } from '../lib/markdown';
import { IconMap } from '../icons';

/**
 * M173 — 项目地图面板(对标 ZCode Zread 可视化)。
 * 不经 store,直接调 api.ts 自取数(useState + useEffect),与 GitDiffView 范式同构。
 */
export function ProjectMapPanel() {
  const [map, setMap] = useState<ProjectMapInfo | null>(null);
  const [needsProject, setNeedsProject] = useState(false);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchProjectMap();
      setMap(res.map);
      setNeedsProject(res.needs_project);
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const regenerate = async () => {
    if (regenerating) return; // busy 态防连点
    setRegenerating(true);
    setError(null);
    try {
      const res = await regenerateProjectMap();
      setMap(res.map);
      setNeedsProject(res.needs_project);
    } catch (e) {
      setError(errText(e));
    } finally {
      setRegenerating(false);
    }
  };

  if (loading && !map) {
    return <div className="side-empty">生成项目地图…</div>;
  }
  if (error && !map) {
    return (
      <div className="side-empty">
        <div>地图加载失败：{error}</div>
        <button className="rdiff-refresh pmap-retry" onClick={() => load()}>
          重试
        </button>
      </div>
    );
  }
  if (needsProject || !map) {
    return <div className="side-empty">未选择项目 · 在底部「选择项目」导入或新建</div>;
  }

  return (
    <div className="pmap">
      <div className="file-head">
        <IconMap size={13} /> 项目地图
        {map.stack.map((s) => (
          <span key={s} className="chip pmap-chip">
            {s}
          </span>
        ))}
        {map.stale && <span className="pmap-stale">项目已变更，地图可能过期</span>}
        <button className="rdiff-refresh" onClick={regenerate} disabled={regenerating} title="强制重建项目地图">
          {regenerating ? '生成中…' : '重新生成'}
        </button>
      </div>
      {error && <div className="pmap-err">地图加载失败：{error}</div>}
      <div className="md-doc">{renderMarkdown(map.markdown)}</div>
      <div className="pmap-foot">
        生成于 {new Date(map.generated_at).toLocaleString()} · {map.from_cache ? '缓存' : '新建'}
      </div>
    </div>
  );
}
