import { afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { ProjectMapPanel } from './ProjectMapPanel';
import type { ProjectMapInfo } from '../types';

// 面板自取数:mock ../api 模块(不经 store)
vi.mock('../api', () => ({
  fetchProjectMap: vi.fn(),
  regenerateProjectMap: vi.fn(),
}));

import { fetchProjectMap, regenerateProjectMap } from '../api';

const mockedFetch = vi.mocked(fetchProjectMap);
const mockedRegen = vi.mocked(regenerateProjectMap);

const sampleMap: ProjectMapInfo = {
  markdown: '# 项目结构\n\n- src\n- docs\n',
  generated_at: '2026-08-04T10:00:00Z',
  stale: false,
  from_cache: true,
  stack: ['React', 'FastAPI'],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('ProjectMapPanel', () => {
  it('挂载时调 fetchProjectMap;loading 态显示「生成项目地图…」,完成后渲染 markdown(md-doc 含标题)', async () => {
    mockedFetch.mockResolvedValue({ map: sampleMap, needs_project: false });
    render(<ProjectMapPanel />);
    expect(mockedFetch).toHaveBeenCalledTimes(1);
    expect(screen.getByText('生成项目地图…')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('项目结构')).toBeInTheDocument());
    expect(screen.getByText('项目结构').tagName).toBe('H1');
    expect(document.querySelector('.md-doc')).toBeTruthy();
  });

  it('needs_project=true → 空态「未选择项目」', async () => {
    mockedFetch.mockResolvedValue({ map: null, needs_project: true });
    render(<ProjectMapPanel />);
    await waitFor(() => expect(screen.getByText(/未选择项目 · 在底部「选择项目」导入或新建/)).toBeInTheDocument());
  });

  it('map=null(needs_project=false)→ 同样空态', async () => {
    mockedFetch.mockResolvedValue({ map: null, needs_project: false });
    render(<ProjectMapPanel />);
    await waitFor(() => expect(screen.getByText(/未选择项目/)).toBeInTheDocument());
  });

  it('stale=true 显示过期徽标;stale=false 不显示', async () => {
    mockedFetch.mockResolvedValue({ map: { ...sampleMap, stale: true }, needs_project: false });
    const { unmount } = render(<ProjectMapPanel />);
    await waitFor(() => expect(screen.getByText('项目已变更，地图可能过期')).toBeInTheDocument());
    unmount();

    mockedFetch.mockResolvedValue({ map: sampleMap, needs_project: false });
    render(<ProjectMapPanel />);
    await waitFor(() => expect(screen.getByText('项目结构')).toBeInTheDocument());
    expect(screen.queryByText('项目已变更，地图可能过期')).toBeNull();
  });

  it('stack chips 渲染技术栈标签', async () => {
    mockedFetch.mockResolvedValue({ map: sampleMap, needs_project: false });
    render(<ProjectMapPanel />);
    await waitFor(() => expect(screen.getByText('React')).toBeInTheDocument());
    expect(screen.getByText('FastAPI')).toBeInTheDocument();
  });

  it('点「重新生成」调 regenerateProjectMap 并用结果刷新内容', async () => {
    mockedFetch.mockResolvedValue({ map: sampleMap, needs_project: false });
    mockedRegen.mockResolvedValue({
      map: { ...sampleMap, markdown: '# 新地图\n', from_cache: false },
      needs_project: false,
    });
    render(<ProjectMapPanel />);
    await waitFor(() => expect(screen.getByText('项目结构')).toBeInTheDocument());
    fireEvent.click(screen.getByText('重新生成'));
    await waitFor(() => expect(screen.getByText('新地图')).toBeInTheDocument());
    expect(mockedRegen).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('项目结构')).toBeNull();
  });

  it('fetch 异常 → 错误态「地图加载失败:<err>」+ 重试按钮可恢复', async () => {
    mockedFetch.mockRejectedValueOnce(new Error('HTTP 500: boom'));
    render(<ProjectMapPanel />);
    await waitFor(() => expect(screen.getByText(/地图加载失败：HTTP 500: boom/)).toBeInTheDocument());

    mockedFetch.mockResolvedValue({ map: sampleMap, needs_project: false });
    fireEvent.click(screen.getByText('重试'));
    await waitFor(() => expect(screen.getByText('项目结构')).toBeInTheDocument());
    expect(mockedFetch).toHaveBeenCalledTimes(2);
  });

  it('底部小字显示本地化生成时间 + 来源(缓存/新建)', async () => {
    mockedFetch.mockResolvedValue({ map: sampleMap, needs_project: false });
    render(<ProjectMapPanel />);
    await waitFor(() => expect(screen.getByText(/缓存/)).toBeInTheDocument());
    expect(screen.getByText(new RegExp(new Date(sampleMap.generated_at).toLocaleString(), 'u'))).toBeInTheDocument();
  });
});
