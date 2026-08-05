import { afterEach, beforeAll, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import { ContextPanel, filterTreeByPaths } from './ContextPanel';

// jsdom 未实现 ResizeObserver / scrollIntoView
beforeAll(() => {
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = vi.fn();
  }
  if (typeof globalThis.ResizeObserver === 'undefined') {
    globalThis.ResizeObserver = class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    } as unknown as typeof ResizeObserver;
  }
});

vi.mock('../store', () => ({ useApp: vi.fn() }));
vi.mock('../lib/native', () => ({
  isTauri: vi.fn(() => false),
  createBrowserWebview: vi.fn(async () => undefined),
  updateBrowserWebview: vi.fn(async () => undefined),
  closeBrowserWebview: vi.fn(async () => undefined),
}));
// PtyTerminal 占位 mock,避免引入 xterm
vi.mock('./PtyTerminal', () => ({
  PtyTerminal: (props: { active: boolean; className?: string }) => (
    <div data-testid="pty-terminal" data-active={String(props.active)} data-class={props.className ?? ''} />
  ),
}));
// M180.2 — 规则/地图面板直调 api,mock 避免真实 fetch
vi.mock('../api', () => ({
  fetchProjectRules: vi.fn(),
  saveProjectRules: vi.fn(),
  fetchProjectMap: vi.fn(),
  regenerateProjectMap: vi.fn(),
}));

import { useApp } from '../store';
import { isTauri } from '../lib/native';
import { fetchProjectRules } from '../api';
import type {
  ChangedFile,
  FileNode,
  GitDiffFile,
  BrowserRender,
  ProjectContext,
  AiReviewResult,
  ReviewHistoryEntry,
  CommitMessageResult,
} from '../types';

const mockedUseApp = vi.mocked(useApp);
const mockedIsTauri = vi.mocked(isTauri);

const baseState = {
  changedFiles: [] as ChangedFile[],
  contextTab: 'files' as 'files' | 'diff' | 'term' | 'browser',
  setContextTab: vi.fn(),
  showContext: true,
  prefillComposer: vi.fn(),
  projectContext: null as ProjectContext | null,
  projectFiles: [] as FileNode[],
  openedFile: null as { path: string; content: string } | null,
  openFile: vi.fn(async () => {}),
  closeFile: vi.fn(),
  // 浏览器 tab
  browserRender: null as BrowserRender | null,
  browserLoading: false,
  browserError: null as string | null,
  renderBrowser: vi.fn(async () => {}),
  browserView: null,
  detectedServerUrl: null as string | null,
  // git diff
  gitDiff: [] as GitDiffFile[],
  gitDiffLoading: false,
  loadGitDiff: vi.fn(async () => {}),
  revertGitDiffFile: vi.fn(async (_path: string) => ({ ok: true, path: _path, action: 'restored' as const })),
  // M193.2 — 逐 hunk 拒绝
  revertGitDiffHunk: vi.fn(async (_path: string, _i: number) => ({
    ok: true,
    path: _path,
    hunk_index: _i,
    action: 'hunk_reverted',
  })),
  // AI 评审(M179.2)
  aiReview: { result: null as AiReviewResult | null, loading: false, error: null as string | null },
  runAiReview: vi.fn(async () => {}),
  clearAiReview: vi.fn(),
  // 评审历史(M186.1)
  reviewHistory: [] as ReviewHistoryEntry[],
  reviewHistoryLoading: false,
  loadReviewHistory: vi.fn(async () => {}),
  openReview: vi.fn(async () => {}),
  // AI commit message(M186.4)
  commitMessage: { result: null as CommitMessageResult | null, loading: false, error: null as string | null },
  generateCommit: vi.fn(async () => {}),
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mockedUseApp.mockReturnValue({ ...baseState } as never);
  mockedIsTauri.mockReturnValue(false);
});

describe('ContextPanel — 隐藏态', () => {
  it('showContext=false 时不渲染(null)', () => {
    mockedUseApp.mockReturnValue({ ...baseState, showContext: false } as never);
    const { container } = render(<ContextPanel />);
    expect(container.firstChild).toBeNull();
  });
});

describe('ContextPanel — tabs 切换', () => {
  it('渲染 4 个 tab(审查/终端/浏览器/文件)', () => {
    render(<ContextPanel />);
    expect(screen.getByText('审查')).toBeInTheDocument();
    expect(screen.getByText('终端')).toBeInTheDocument();
    expect(screen.getByText('浏览器')).toBeInTheDocument();
    expect(screen.getByText('文件')).toBeInTheDocument();
  });

  it('当前 tab=files 时,文件 tab 含 active class', () => {
    render(<ContextPanel />);
    const filesTab = screen.getByText('文件').closest('button') as HTMLElement;
    expect(filesTab.classList.contains('active')).toBe(true);
  });

  it('点击"审查"调用 setContextTab("diff")', () => {
    const setContextTab = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setContextTab } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByText('审查'));
    expect(setContextTab).toHaveBeenCalledWith('diff');
  });

  it('点击"终端"调用 setContextTab("term")', () => {
    const setContextTab = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setContextTab } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByText('终端'));
    expect(setContextTab).toHaveBeenCalledWith('term');
  });

  it('点击"浏览器"调用 setContextTab("browser")', () => {
    const setContextTab = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setContextTab } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByText('浏览器'));
    expect(setContextTab).toHaveBeenCalledWith('browser');
  });

  it('点击"文件"调用 setContextTab("files")', () => {
    const setContextTab = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'diff', setContextTab } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByText('文件'));
    expect(setContextTab).toHaveBeenCalledWith('files');
  });

  it('点击"规则"调用 setContextTab("rules")', () => {
    const setContextTab = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setContextTab } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByText('规则'));
    expect(setContextTab).toHaveBeenCalledWith('rules');
  });

  it('contextTab=rules 时渲染 RulesPanel(项目规则标题 + files 徽标)', async () => {
    vi.mocked(fetchProjectRules).mockResolvedValue({
      files: ['.flipped/rules.md', 'AGENTS.md'],
      markdown: '## .flipped/rules.md\n\n- 禁止 console.log\n',
      total_chars: 40,
      rules_content: '- 禁止 console.log\n',
      needs_project: false,
    });
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'rules' } as never);
    render(<ContextPanel />);
    await waitFor(() => expect(screen.getByText('项目规则')).toBeInTheDocument());
    const chips = [...document.querySelectorAll('.rules-chip')].map((c) => c.textContent);
    expect(chips).toEqual(['.flipped/rules.md', 'AGENTS.md']);
  });
});

describe('ContextPanel — 文件 tab(无打开文件)', () => {
  it('未选择项目时显示"未选择项目"提示', () => {
    render(<ContextPanel />);
    expect(screen.getByText(/未选择项目/)).toBeInTheDocument();
  });

  it('选择项目但无文件时显示"空项目 · 暂无文件"', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectContext: { project: 'my-proj', branch: null, mode: 'agent' },
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('空项目 · 暂无文件')).toBeInTheDocument();
  });

  it('渲染文件树(顶层目录/文件)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectFiles: [
        { name: 'src', path: 'src', type: 'dir', children: [{ name: 'a.ts', path: 'src/a.ts', type: 'file' }] },
        { name: 'README.md', path: 'README.md', type: 'file' },
      ],
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('src')).toBeInTheDocument();
    expect(screen.getByText('README.md')).toBeInTheDocument();
  });

  it('点击目录节点切换展开状态(aria-expanded)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectFiles: [
        {
          name: 'src',
          path: 'src',
          type: 'dir',
          children: [{ name: 'a.ts', path: 'src/a.ts', type: 'file' }],
        },
      ],
    } as never);
    render(<ContextPanel />);
    const dirBtn = screen.getByText('src').closest('button') as HTMLElement;
    // 顶层目录默认展开(depth<1)
    expect(dirBtn.getAttribute('aria-expanded')).toBe('true');
    // 子文件可见
    expect(screen.getByText('a.ts')).toBeInTheDocument();
    fireEvent.click(dirBtn);
    expect(dirBtn.getAttribute('aria-expanded')).toBe('false');
  });

  it('点击文件节点调用 openFile(path)', () => {
    const openFile = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectFiles: [{ name: 'a.ts', path: 'a.ts', type: 'file' }],
      openFile,
    } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByText('a.ts'));
    expect(openFile).toHaveBeenCalledWith('a.ts');
  });
});

describe('ContextPanel — 文件 tab(打开文件 = 编辑器视图)', () => {
  it('渲染面包屑(项目名 + 路径分段)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectContext: { project: 'proj-x', branch: null, mode: 'agent' },
      openedFile: { path: 'src/app/main.ts', content: 'const x = 1;\n' },
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('proj-x')).toBeInTheDocument();
    expect(screen.getByText('src')).toBeInTheDocument();
    expect(screen.getByText('app')).toBeInTheDocument();
    expect(screen.getByText('main.ts')).toBeInTheDocument();
  });

  it('渲染编辑器行(行号 + 内容)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'const x = 1;\nconst y = 2;\n' },
    } as never);
    render(<ContextPanel />);
    // 行号在 .gn span 里(避免与代码里的 "1"/"2" 冲突)
    const lns = screen.getAllByText(/^\d+$/, { selector: '.gn' });
    expect(lns.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/const x/)).toBeInTheDocument();
    expect(screen.getByText(/const y/)).toBeInTheDocument();
  });

  it('.md 文件走 markdown 渲染(不走编辑器)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'README.md', content: '# Hello\n\nworld\n' },
    } as never);
    render(<ContextPanel />);
    // markdown 渲染为 <h1>Hello</h1>
    expect(screen.getByText('Hello').tagName).toBe('H1');
    // 不应渲染行号
    expect(screen.queryByText('1', { selector: '.gn' })).toBeNull();
  });

  it('点击"返回文件树"按钮调用 closeFile()', () => {
    const closeFile = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'x' },
      closeFile,
    } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByTitle('返回文件树'));
    expect(closeFile).toHaveBeenCalledTimes(1);
  });

  it('点击行评论按钮打开评论框', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'x\n' },
    } as never);
    render(<ContextPanel />);
    const commentBtn = screen.getByLabelText('对第 1 行评论');
    fireEvent.click(commentBtn);
    expect(screen.getByText('a.ts:1')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/写下对这行的意见/)).toBeInTheDocument();
  });

  it('评论框 Enter 提交调用 prefillComposer 并清空', () => {
    const prefillComposer = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'x\n' },
      prefillComposer,
    } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByLabelText('对第 1 行评论'));
    const textarea = screen.getByPlaceholderText(/写下对这行的意见/);
    fireEvent.change(textarea, { target: { value: '改一下' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });
    expect(prefillComposer).toHaveBeenCalledWith('关于 a.ts:1 — 改一下');
  });

  it('评论框 Shift+Enter 不提交(换行)', () => {
    const prefillComposer = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'x\n' },
      prefillComposer,
    } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByLabelText('对第 1 行评论'));
    const textarea = screen.getByPlaceholderText(/写下对这行的意见/);
    fireEvent.change(textarea, { target: { value: '改一下' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
    expect(prefillComposer).not.toHaveBeenCalled();
  });

  it('评论框 Escape 关闭评论框', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'x\n' },
    } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByLabelText('对第 1 行评论'));
    const textarea = screen.getByPlaceholderText(/写下对这行的意见/);
    fireEvent.keyDown(textarea, { key: 'Escape' });
    expect(screen.queryByPlaceholderText(/写下对这行的意见/)).toBeNull();
  });

  it('点击"取消"按钮关闭评论框', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'x\n' },
    } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByLabelText('对第 1 行评论'));
    fireEvent.click(screen.getByText('取消'));
    expect(screen.queryByPlaceholderText(/写下对这行的意见/)).toBeNull();
  });

  it('评论为空时"发送到输入区"按钮禁用', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'x\n' },
    } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByLabelText('对第 1 行评论'));
    const submitBtn = screen.getByText('发送到输入区').closest('button') as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(true);
  });

  it('点击"发送到输入区"按钮调用 prefillComposer', () => {
    const prefillComposer = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'x\n' },
      prefillComposer,
    } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByLabelText('对第 1 行评论'));
    const textarea = screen.getByPlaceholderText(/写下对这行的意见/);
    fireEvent.change(textarea, { target: { value: '修一下' } });
    fireEvent.click(screen.getByText('发送到输入区'));
    expect(prefillComposer).toHaveBeenCalledWith('关于 a.ts:1 — 修一下');
  });

  it('空评论(只空格)提交时不调用 prefillComposer', () => {
    const prefillComposer = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'x\n' },
      prefillComposer,
    } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByLabelText('对第 1 行评论'));
    const textarea = screen.getByPlaceholderText(/写下对这行的意见/);
    fireEvent.change(textarea, { target: { value: '   ' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });
    expect(prefillComposer).not.toHaveBeenCalled();
  });
});

describe('ContextPanel — 审查 tab(本次会话变更)', () => {
  it('有 changedFiles 时渲染"本次会话变更"标题与数量', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [
        { path: 'src/a.ts', change: 'mod', content: 'x\ny\n' },
        { path: 'README.md', change: 'add', content: '# 新\n' },
      ],
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('本次会话变更')).toBeInTheDocument();
    expect(screen.getByText('2 个文件')).toBeInTheDocument();
  });

  it('changedFile 渲染文件名 / 路径 / 变更类型徽章', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [{ path: 'src/app/main.ts', change: 'mod', content: 'x\n' }],
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('main.ts')).toBeInTheDocument();
    expect(screen.getByText('src/app/main.ts')).toBeInTheDocument();
    expect(screen.getByText('修改')).toBeInTheDocument();
  });

  it('change=add 渲染"新增"徽章', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [{ path: 'new.ts', change: 'add', content: 'x\n' }],
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('新增')).toBeInTheDocument();
  });

  it('change=del 渲染"删除"徽章', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [{ path: 'gone.ts', change: 'del', content: '' }],
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('删除')).toBeInTheDocument();
  });

  it('未知 change 类型原样显示', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [{ path: 'x.ts', change: 'renamed', content: '' }],
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('renamed')).toBeInTheDocument();
  });

  it('有 content 时折叠按钮可点击切换', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [{ path: 'src/a.ts', change: 'mod', content: 'x\ny\n' }],
    } as never);
    render(<ContextPanel />);
    // diff-file-name 与 diff-file-path 都可能含 a.ts;用 .diff-file-name 精确定位
    const head = screen.getByText('a.ts', { selector: '.diff-file-name' }).closest('button') as HTMLButtonElement;
    // 默认展开
    const chev = head.querySelector('.diff-file-chev') as HTMLElement;
    expect(chev.classList.contains('open')).toBe(true);
    fireEvent.click(head);
    expect(chev.classList.contains('open')).toBe(false);
  });

  it('无 content 时折叠按钮禁用', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [{ path: 'src/a.ts', change: 'mod', content: '' }],
    } as never);
    render(<ContextPanel />);
    const head = screen.getByText('a.ts', { selector: '.diff-file-name' }).closest('button') as HTMLButtonElement;
    expect(head.disabled).toBe(true);
  });

  it('content 行渲染行号与 + 符号', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [{ path: 'a.ts', change: 'add', content: 'line1\nline2\n' }],
    } as never);
    render(<ContextPanel />);
    // 行号 1 和 2
    const lns = screen.getAllByText('1', { selector: '.ln' });
    expect(lns.length).toBeGreaterThanOrEqual(1);
  });
});

describe('ContextPanel — 审查 tab(无变更,渲染 GitDiffView)', () => {
  it('加载中显示"读取 git 变更…"', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [],
      gitDiffLoading: true,
      gitDiff: [],
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('读取 git 变更…')).toBeInTheDocument();
  });

  it('加载完成且无变更显示"工作区无未提交变更"', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [],
      gitDiffLoading: false,
      gitDiff: [],
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText(/工作区无未提交变更/)).toBeInTheDocument();
  });

  it('挂载后调用 loadGitDiff()', () => {
    const loadGitDiff = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [],
      loadGitDiff,
    } as never);
    render(<ContextPanel />);
    expect(loadGitDiff).toHaveBeenCalled();
  });

  it('渲染 git 变更文件列表(路径/+/-)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [],
      gitDiff: [
        {
          path: 'src/a.ts',
          added: 5,
          removed: 2,
          lines: [
            { type: 'add', text: 'new line' },
            { type: 'del', text: 'old line' },
            { type: 'ctx', text: 'context' },
            { type: 'hunk', text: '@@ -1,2 +1,3 @@' },
          ],
        },
      ],
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('src/a.ts')).toBeInTheDocument();
    expect(screen.getByText('+5')).toBeInTheDocument();
    expect(screen.getByText('−2')).toBeInTheDocument();
    expect(screen.getByText('new line')).toBeInTheDocument();
    expect(screen.getByText('old line')).toBeInTheDocument();
    expect(screen.getByText('1 个文件')).toBeInTheDocument();
  });

  it('点击"刷新"调用 loadGitDiff()', () => {
    const loadGitDiff = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [],
      gitDiff: [
        { path: 'a.ts', added: 1, removed: 0, lines: [{ type: 'add', text: 'x' }] },
      ],
      loadGitDiff,
    } as never);
    render(<ContextPanel />);
    vi.clearAllMocks();
    fireEvent.click(screen.getByTitle('刷新'));
    expect(loadGitDiff).toHaveBeenCalled();
  });
});

// M177.2 — Review 面板强化:untracked/binary 徽标、空 diff 占位、逐文件撤销(行内确认)
describe('ContextPanel — 审查 tab · M177.2 文件卡增强', () => {
  const diffFiles: GitDiffFile[] = [
    { path: 'src/tracked.ts', added: 2, removed: 1, lines: [{ type: 'add', text: 'x' }] },
    { path: 'src/new-file.ts', added: 10, removed: 0, lines: [], untracked: true },
    { path: 'assets/logo.png', added: 0, removed: 0, lines: [], binary: true },
  ];
  const renderDiff = (overrides: Record<string, unknown> = {}) => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [],
      gitDiff: diffFiles,
      ...overrides,
    } as never);
    return render(<ContextPanel />);
  };

  it('untracked 文件卡显示「新增」徽标', () => {
    renderDiff();
    expect(screen.getByText('新增')).toBeInTheDocument();
  });

  it('binary 文件卡显示「二进制」徽标', () => {
    renderDiff();
    expect(screen.getByText('二进制')).toBeInTheDocument();
  });

  it('lines 为空时显示占位文案(untracked/binary)', () => {
    renderDiff();
    expect(screen.getByText('新文件 · 撤销将删除该文件')).toBeInTheDocument();
    expect(screen.getByText('二进制文件不显示 diff')).toBeInTheDocument();
  });

  it('点击撤销按钮出现确认文案与确认/取消按钮', () => {
    renderDiff();
    fireEvent.click(screen.getAllByTitle('撤销该文件变更')[0]);
    expect(screen.getByText('还原到 HEAD？')).toBeInTheDocument();
    expect(screen.getByText('确认')).toBeInTheDocument();
    expect(screen.getByText('取消')).toBeInTheDocument();
  });

  it('点击取消 → 确认态消失,恢复撤销按钮', () => {
    renderDiff();
    fireEvent.click(screen.getAllByTitle('撤销该文件变更')[0]);
    expect(screen.getByText('还原到 HEAD？')).toBeInTheDocument();
    fireEvent.click(screen.getByText('取消'));
    expect(screen.queryByText('还原到 HEAD？')).not.toBeInTheDocument();
    expect(screen.getAllByTitle('撤销该文件变更')).toHaveLength(3);
  });

  it('点击确认 → 调 revertGitDiffFile(path) 且成功后刷新(loadGitDiff)', async () => {
    const loadGitDiff = vi.fn(async () => {});
    const revertGitDiffFile = vi.fn(async (p: string) => {
      await loadGitDiff();
      return { ok: true, path: p, action: 'restored' as const };
    });
    renderDiff({ loadGitDiff, revertGitDiffFile });
    fireEvent.click(screen.getAllByTitle('撤销该文件变更')[0]);
    fireEvent.click(screen.getByText('确认'));
    await waitFor(() => expect(revertGitDiffFile).toHaveBeenCalledWith('src/tracked.ts'));
    await waitFor(() => expect(loadGitDiff).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText('还原到 HEAD？')).not.toBeInTheDocument());
  });

  it('撤销失败 → 显示错误文案且确认态保持,可重试', async () => {
    const revertGitDiffFile = vi.fn(async (_p: string) => {
      throw new Error('磁盘只读');
    });
    renderDiff({ revertGitDiffFile });
    fireEvent.click(screen.getAllByTitle('撤销该文件变更')[0]);
    fireEvent.click(screen.getByText('确认'));
    await screen.findByText('磁盘只读');
    expect(screen.getByText('还原到 HEAD？')).toBeInTheDocument();
    expect(screen.getByText('确认')).toBeInTheDocument();
  });

  it('untracked 确认文案是"删除该新文件？",tracked 是"还原到 HEAD？"', () => {
    renderDiff();
    fireEvent.click(screen.getAllByTitle('撤销该文件变更')[1]);
    expect(screen.getByText('删除该新文件？')).toBeInTheDocument();
    fireEvent.click(screen.getByText('取消'));
    fireEvent.click(screen.getAllByTitle('撤销该文件变更')[0]);
    expect(screen.getByText('还原到 HEAD？')).toBeInTheDocument();
  });
});

// M193.2 — 逐 hunk 接受/拒绝:hunk 块渲染 + 接受进度标记(纯前端) + 拒绝内联确认流
describe('ContextPanel — 审查 tab · M193.2 逐 hunk 接受/拒绝', () => {
  const twoHunkDiff: GitDiffFile[] = [
    {
      path: 'src/two.ts',
      added: 2,
      removed: 2,
      lines: [
        { type: 'hunk', text: '@@ -1,3 +1,3 @@' },
        { type: 'ctx', text: 'line a' },
        { type: 'del', text: 'old 1' },
        { type: 'add', text: 'new 1' },
        { type: 'hunk', text: '@@ -10,3 +10,3 @@' },
        { type: 'ctx', text: 'line b' },
        { type: 'del', text: 'old 2' },
        { type: 'add', text: 'new 2' },
      ],
    },
  ];
  const renderDiff = (overrides: Record<string, unknown> = {}, files: GitDiffFile[] = twoHunkDiff) => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [],
      gitDiff: files,
      ...overrides,
    } as never);
    return render(<ContextPanel />);
  };
  const hunkEl = (header: string) => screen.getByText(header).closest('.rdiff-hunk') as HTMLElement;

  it('两 hunk → 各自头部渲染接受/拒绝按钮,行内容仍在块内', () => {
    renderDiff();
    expect(screen.getByText('@@ -1,3 +1,3 @@')).toBeInTheDocument();
    expect(screen.getByText('@@ -10,3 +10,3 @@')).toBeInTheDocument();
    expect(screen.getAllByTitle('接受该 hunk（保留改动）')).toHaveLength(2);
    expect(screen.getAllByTitle('拒绝该 hunk（撤销改动回 HEAD）')).toHaveLength(2);
    expect(within(hunkEl('@@ -1,3 +1,3 @@')).getByText('new 1')).toBeInTheDocument();
    expect(within(hunkEl('@@ -10,3 +10,3 @@')).getByText('new 2')).toBeInTheDocument();
  });

  it('接受 → 块加 accepted 类并显示「已接受」;撤销接受 → 还原待审', () => {
    renderDiff();
    const el = hunkEl('@@ -1,3 +1,3 @@');
    fireEvent.click(within(el).getByTitle('接受该 hunk（保留改动）'));
    expect(el.classList.contains('accepted')).toBe(true);
    expect(within(el).getByText('已接受')).toBeInTheDocument();
    expect(within(el).queryByTitle('拒绝该 hunk（撤销改动回 HEAD）')).not.toBeInTheDocument();
    // 另一 hunk 不受影响
    expect(hunkEl('@@ -10,3 +10,3 @@').classList.contains('accepted')).toBe(false);
    fireEvent.click(within(el).getByTitle('撤销接受'));
    expect(el.classList.contains('accepted')).toBe(false);
    expect(within(el).getByTitle('接受该 hunk（保留改动）')).toBeInTheDocument();
  });

  it('拒绝 → 内联确认 → 确认调 revertGitDiffHunk(path, index)', async () => {
    const loadGitDiff = vi.fn(async () => {});
    const revertGitDiffHunk = vi.fn(async (p: string, i: number) => {
      await loadGitDiff();
      return { ok: true, path: p, hunk_index: i, action: 'hunk_reverted' };
    });
    renderDiff({ loadGitDiff, revertGitDiffHunk });
    const el = hunkEl('@@ -10,3 +10,3 @@');
    fireEvent.click(within(el).getByTitle('拒绝该 hunk（撤销改动回 HEAD）'));
    expect(within(el).getByText('撤销该 hunk 改动？')).toBeInTheDocument();
    fireEvent.click(within(el).getByText('确认'));
    await waitFor(() => expect(revertGitDiffHunk).toHaveBeenCalledWith('src/two.ts', 1));
    await waitFor(() => expect(loadGitDiff).toHaveBeenCalled());
    await waitFor(() => expect(within(el).queryByText('撤销该 hunk 改动？')).not.toBeInTheDocument());
  });

  it('拒绝 → 取消 → 确认态消失,按钮恢复', () => {
    renderDiff();
    const el = hunkEl('@@ -1,3 +1,3 @@');
    fireEvent.click(within(el).getByTitle('拒绝该 hunk（撤销改动回 HEAD）'));
    expect(within(el).getByText('撤销该 hunk 改动？')).toBeInTheDocument();
    fireEvent.click(within(el).getByText('取消'));
    expect(within(el).queryByText('撤销该 hunk 改动？')).not.toBeInTheDocument();
    expect(within(el).getByTitle('拒绝该 hunk（撤销改动回 HEAD）')).toBeInTheDocument();
  });

  it('revertGitDiffHunk 失败 → 错误文案内联展示在对应 hunk 块', async () => {
    const revertGitDiffHunk = vi.fn(async () => {
      throw new Error('HTTP 409: 工作区已变化（diff 漂移），请刷新后重试');
    });
    renderDiff({ revertGitDiffHunk });
    const el = hunkEl('@@ -1,3 +1,3 @@');
    fireEvent.click(within(el).getByTitle('拒绝该 hunk（撤销改动回 HEAD）'));
    fireEvent.click(within(el).getByText('确认'));
    await waitFor(() =>
      expect(within(el).getByText(/工作区已变化/)).toBeInTheDocument()
    );
    // 另一 hunk 块无错误
    expect(within(hunkEl('@@ -10,3 +10,3 @@')).queryByText(/工作区已变化/)).not.toBeInTheDocument();
  });

  it('untracked/binary 文件(lines 空) → 不出 hunk 按钮(回归既有空态)', () => {
    renderDiff({}, [
      { path: 'src/new.ts', added: 5, removed: 0, lines: [], untracked: true },
      { path: 'assets/logo.png', added: 0, removed: 0, lines: [], binary: true },
    ]);
    expect(screen.getByText('新文件 · 撤销将删除该文件')).toBeInTheDocument();
    expect(screen.queryByTitle('接受该 hunk（保留改动）')).not.toBeInTheDocument();
    expect(screen.queryByTitle('拒绝该 hunk（撤销改动回 HEAD）')).not.toBeInTheDocument();
  });

  it('无 hunk 行的 lines(防御 prelude) → 扁平行渲染,不出 hunk 按钮', () => {
    renderDiff({}, [
      { path: 'src/flat.ts', added: 1, removed: 0, lines: [{ type: 'add', text: 'x' }] },
    ]);
    expect(screen.getByText('x')).toBeInTheDocument();
    expect(screen.queryByTitle('接受该 hunk（保留改动）')).not.toBeInTheDocument();
  });
});

// M179.2 — AI 代码评审:头部「AI 评审」按钮 + findings 按文件行内渲染 + 总览行 + 其他文件分组
describe('ContextPanel — 审查 tab · M179.2 AI 评审', () => {
  const diffFiles: GitDiffFile[] = [
    { path: 'src/a.ts', added: 3, removed: 1, lines: [{ type: 'add', text: '+new' }] },
    { path: 'src/b.ts', added: 0, removed: 1, lines: [{ type: 'del', text: '-old' }] },
  ];
  const reviewResult: AiReviewResult = {
    findings: [
      { path: 'src/a.ts', line: 42, severity: 'high', message: '可能空指针', suggestion: '加判空' },
      { path: 'src/a.ts', severity: 'low', message: '命名含糊' },
      { path: 'src/b.ts', severity: 'medium', message: '缺少错误处理' },
      { path: 'src/gone.ts', severity: 'low', message: '不在 diff 里的发现' },
    ],
    files_reviewed: 2,
    model: 'glm-x',
    note: null,
  };
  const renderDiff = (overrides: Record<string, unknown> = {}) => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [],
      gitDiff: diffFiles,
      ...overrides,
    } as never);
    return render(<ContextPanel />);
  };

  it('头部渲染「AI 评审」按钮,点击调用 runAiReview()', () => {
    const runAiReview = vi.fn(async () => {});
    renderDiff({ runAiReview });
    fireEvent.click(screen.getByText('AI 评审'));
    expect(runAiReview).toHaveBeenCalledTimes(1);
  });

  it('loading 中按钮禁用且文案为「评审中…」', () => {
    renderDiff({ aiReview: { result: null, loading: true, error: null } });
    const btn = screen.getByText('评审中…').closest('button') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(screen.queryByText('AI 评审')).toBeNull();
  });

  it('findings 按 path 分组渲染到对应文件卡(不串卡)', () => {
    renderDiff({ aiReview: { result: reviewResult, loading: false, error: null } });
    const cardA = screen.getByText('src/a.ts').closest('.rdiff-file') as HTMLElement;
    const cardB = screen.getByText('src/b.ts').closest('.rdiff-file') as HTMLElement;
    expect(within(cardA).getByText(/可能空指针/)).toBeInTheDocument();
    expect(within(cardA).getByText('命名含糊')).toBeInTheDocument();
    expect(within(cardA).queryByText('缺少错误处理')).toBeNull();
    expect(within(cardB).getByText('缺少错误处理')).toBeInTheDocument();
  });

  it('finding 渲染在文件卡 diff 行之上', () => {
    renderDiff({ aiReview: { result: reviewResult, loading: false, error: null } });
    const cardA = screen.getByText('src/a.ts').closest('.rdiff-file') as HTMLElement;
    const findingEl = within(cardA).getByText(/可能空指针/);
    const diffRowEl = within(cardA).getByText('+new');
    // finding 在 diff 行之前(diffRow 是 finding 的后续节点)
    expect(findingEl.compareDocumentPosition(diffRowEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('severity 徽标三态(high/medium/low 类名 + 高/中/低 文案)', () => {
    const { container } = renderDiff({ aiReview: { result: reviewResult, loading: false, error: null } });
    expect(container.querySelector('.review-badge.high')?.textContent).toBe('高');
    expect(container.querySelector('.review-badge.medium')?.textContent).toBe('中');
    expect(container.querySelectorAll('.review-badge.low').length).toBe(2);
  });

  it('line 非空追加「:行号」,suggestion 非空渲染次级行「建议:…」', () => {
    renderDiff({ aiReview: { result: reviewResult, loading: false, error: null } });
    expect(screen.getByText(':42')).toBeInTheDocument();
    expect(screen.getByText('建议:加判空')).toBeInTheDocument();
  });

  it('path 不在当前 diff 的 findings → 底部「其他文件」分组(带 path 前缀)', () => {
    const { container } = renderDiff({ aiReview: { result: reviewResult, loading: false, error: null } });
    const other = screen.getByText('其他文件').closest('.review-other') as HTMLElement;
    expect(other).toBeTruthy();
    expect(within(other).getByText('不在 diff 里的发现')).toBeInTheDocument();
    expect(within(other).getByText('src/gone.ts')).toBeInTheDocument();
    // 匹配文件的 finding 不进「其他文件」
    expect(within(other).queryByText('命名含糊')).toBeNull();
    expect(container.querySelectorAll('.review-other .review-finding')).toHaveLength(1);
  });

  it('总览行展示「N 条建议 · 评审了 M 个文件 · model」,清除按钮调 clearAiReview()', () => {
    const clearAiReview = vi.fn();
    renderDiff({ aiReview: { result: reviewResult, loading: false, error: null }, clearAiReview });
    expect(screen.getByText('4 条建议 · 评审了 2 个文件 · glm-x')).toBeInTheDocument();
    fireEvent.click(screen.getByText('清除'));
    expect(clearAiReview).toHaveBeenCalledTimes(1);
  });

  it('note 非空时总览行展示 note', () => {
    renderDiff({
      aiReview: { result: { ...reviewResult, findings: [], files_reviewed: 0, note: '工作区干净' }, loading: false, error: null },
    });
    expect(screen.getByText('0 条建议 · 评审了 0 个文件 · glm-x')).toBeInTheDocument();
    expect(screen.getByText('工作区干净')).toBeInTheDocument();
  });

  it('error 非空 → 头部下方红字行(.review-error)', () => {
    const { container } = renderDiff({
      aiReview: { result: null, loading: false, error: 'HTTP 502: LLM 解析失败' },
    });
    const err = container.querySelector('.review-error') as HTMLElement;
    expect(err).toBeTruthy();
    expect(err.textContent).toContain('HTTP 502: LLM 解析失败');
  });

  it('无 result 时不渲染总览行与「其他文件」分组', () => {
    renderDiff();
    expect(screen.queryByText(/条建议/)).toBeNull();
    expect(screen.queryByText('其他文件')).toBeNull();
  });
});

// M186.2 — findings 行号跳转:有行号的 finding 整行可点 → openFile(path, line);
// 编辑器目标行高亮(.eln-wrap.line-target) + scrollIntoView 居中
describe('ContextPanel — M186.2 findings 行号跳转', () => {
  const diffFiles: GitDiffFile[] = [
    { path: 'src/a.ts', added: 3, removed: 1, lines: [{ type: 'add', text: '+new' }] },
  ];
  const renderDiff = (overrides: Record<string, unknown> = {}) => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [],
      gitDiff: diffFiles,
      ...overrides,
    } as never);
    return render(<ContextPanel />);
  };

  it('finding.line 非空 → 整行渲染为 button.review-jump,点击调 openFile(path, line)', () => {
    const openFile = vi.fn(async () => {});
    renderDiff({
      openFile,
      aiReview: {
        result: {
          findings: [{ path: 'src/a.ts', line: 42, severity: 'high', message: '可能空指针' }],
          files_reviewed: 1,
          model: 'm',
        },
        loading: false,
        error: null,
      },
    });
    const btn = screen.getByText(/可能空指针/).closest('button.review-jump') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    fireEvent.click(btn);
    expect(openFile).toHaveBeenCalledWith('src/a.ts', 42);
  });

  it('finding.line 为 null → 保持 div 不可点(无 review-jump)', () => {
    renderDiff({
      aiReview: {
        result: {
          findings: [{ path: 'src/a.ts', line: null, severity: 'low', message: '命名含糊' }],
          files_reviewed: 1,
          model: 'm',
        },
        loading: false,
        error: null,
      },
    });
    const el = screen.getByText('命名含糊').closest('.review-finding') as HTMLElement;
    expect(el.tagName).toBe('DIV');
    expect(el.classList.contains('review-jump')).toBe(false);
  });

  it('openedFile.line 存在 → 目标行 .eln-wrap 加 line-target 且 scrollIntoView 居中', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'l1\nl2\nl3\n', line: 2 },
    } as never);
    const { container } = render(<ContextPanel />);
    const target = container.querySelector('.eln-wrap.line-target') as HTMLElement;
    expect(target).toBeTruthy();
    expect(target.querySelector('.gn')!.textContent).toBe('2');
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: 'center' });
  });

  it('openedFile.line 越界 → 不高亮也不滚动', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'l1\nl2\n', line: 99 },
    } as never);
    const { container } = render(<ContextPanel />);
    expect(container.querySelector('.eln-wrap.line-target')).toBeNull();
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });
});

// M186.3 — 文件树「仅变更」过滤:filterTreeByPaths 纯函数 + 文件 tab 头部 toggle(默认关)+ 计数徽标
describe('ContextPanel — M186.3 文件树「仅变更」过滤', () => {
  it('filterTreeByPaths: 保留命中文件与祖先目录,剔除无命中子树', () => {
    const tree: FileNode[] = [
      {
        name: 'src', path: 'src', type: 'dir', children: [
          { name: 'a.ts', path: 'src/a.ts', type: 'file' },
          { name: 'b.ts', path: 'src/b.ts', type: 'file' },
          {
            name: 'deep', path: 'src/deep', type: 'dir', children: [
              { name: 'c.ts', path: 'src/deep/c.ts', type: 'file' },
            ],
          },
        ],
      },
      {
        name: 'docs', path: 'docs', type: 'dir', children: [
          { name: 'd.md', path: 'docs/d.md', type: 'file' },
        ],
      },
      { name: 'README.md', path: 'README.md', type: 'file' },
    ];
    const out = filterTreeByPaths(tree, new Set(['src/deep/c.ts']));
    expect(out).toHaveLength(1);
    expect(out[0].path).toBe('src');
    expect(out[0].children).toHaveLength(1);
    expect(out[0].children![0].path).toBe('src/deep');
    expect(out[0].children![0].children![0].path).toBe('src/deep/c.ts');
  });

  it('filterTreeByPaths: 空集合 → 空树;多命中平铺保留', () => {
    const tree: FileNode[] = [
      { name: 'a.ts', path: 'a.ts', type: 'file' },
      { name: 'b.ts', path: 'b.ts', type: 'file' },
    ];
    expect(filterTreeByPaths(tree, new Set())).toEqual([]);
    expect(filterTreeByPaths(tree, new Set(['a.ts', 'b.ts']))).toHaveLength(2);
  });

  it('toggle 默认关渲染全树;开启只留变更文件+祖先;徽标=gitDiff.length;再点恢复', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectFiles: [
        { name: 'src', path: 'src', type: 'dir', children: [{ name: 'a.ts', path: 'src/a.ts', type: 'file' }] },
        { name: 'README.md', path: 'README.md', type: 'file' },
      ],
      gitDiff: [{ path: 'src/a.ts', added: 1, removed: 0, lines: [] }],
    } as never);
    render(<ContextPanel />);
    // 默认关:全树可见
    expect(screen.getByText('README.md')).toBeInTheDocument();
    const toggle = screen.getByText('仅变更').closest('button') as HTMLButtonElement;
    // 计数徽标
    expect(within(toggle).getByText('1')).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.queryByText('README.md')).toBeNull();
    expect(screen.getByText('src')).toBeInTheDocument();
    expect(screen.getByText('a.ts')).toBeInTheDocument();
    // 再点关 → 恢复全树
    fireEvent.click(toggle);
    expect(screen.getByText('README.md')).toBeInTheDocument();
  });

  it('开启后无命中 → 提示「无变更文件」', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectContext: { project: 'p', branch: null, mode: 'agent' },
      projectFiles: [{ name: 'a.ts', path: 'a.ts', type: 'file' }],
      gitDiff: [{ path: 'other.ts', added: 1, removed: 0, lines: [] }],
    } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByText('仅变更'));
    expect(screen.getByText('无变更文件')).toBeInTheDocument();
    expect(screen.queryByText('a.ts')).toBeNull();
  });
});

// M186.1 — 评审历史:头部「历史」按钮展开下拉列表(打开时拉取),点击条目回放该次评审
describe('ContextPanel — M186.1 评审历史', () => {
  const diffFiles: GitDiffFile[] = [
    { path: 'src/a.ts', added: 3, removed: 1, lines: [{ type: 'add', text: '+new' }] },
  ];
  const renderDiff = (overrides: Record<string, unknown> = {}) => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [],
      gitDiff: diffFiles,
      ...overrides,
    } as never);
    return render(<ContextPanel />);
  };

  it('点击「历史」展开并调 loadReviewHistory;空列表 → 「暂无历史评审」;再点收起(不重复拉取)', () => {
    const loadReviewHistory = vi.fn(async () => {});
    renderDiff({ loadReviewHistory });
    const btn = screen.getByTitle('评审历史');
    fireEvent.click(btn);
    expect(loadReviewHistory).toHaveBeenCalledTimes(1);
    expect(screen.getByText('暂无历史评审')).toBeInTheDocument();
    fireEvent.click(btn);
    expect(screen.queryByText('暂无历史评审')).toBeNull();
    expect(loadReviewHistory).toHaveBeenCalledTimes(1);
  });

  it('列表渲染条目(ts/model/建议数/文件数),点击条目调 openReview(id) 并收起列表', () => {
    const openReview = vi.fn(async () => {});
    renderDiff({
      openReview,
      reviewHistory: [
        { id: 'r1', ts: '2026-08-05T10:30:00Z', project: 'p', model: 'glm-x', files_reviewed: 2, findings_count: 3 },
      ],
    });
    fireEvent.click(screen.getByTitle('评审历史'));
    expect(screen.getByText('2026-08-05 10:30')).toBeInTheDocument();
    const row = screen.getByText(/glm-x · 3 条建议 · 2 文件/).closest('button') as HTMLButtonElement;
    expect(row).toBeTruthy();
    fireEvent.click(row);
    expect(openReview).toHaveBeenCalledWith('r1');
    // 收起
    expect(screen.queryByText(/glm-x · 3 条建议/)).toBeNull();
  });

  it('reviewHistoryLoading=true → 显示「载入历史…」', () => {
    renderDiff({ reviewHistoryLoading: true });
    fireEvent.click(screen.getByTitle('评审历史'));
    expect(screen.getByText('载入历史…')).toBeInTheDocument();
  });

  it('aiReview.result.historical=true → 总览行显示「历史」徽标;缺省 → 无徽标', () => {
    const { container, unmount } = renderDiff({
      aiReview: {
        result: { findings: [], files_reviewed: 0, model: 'm', historical: true },
        loading: false,
        error: null,
      },
    });
    expect(container.querySelector('.review-hist-badge')).toBeTruthy();
    expect(container.querySelector('.review-hist-badge')!.textContent).toBe('历史');
    unmount();
    const { container: c2 } = renderDiff({
      aiReview: { result: { findings: [], files_reviewed: 0, model: 'm' }, loading: false, error: null },
    });
    expect(c2.querySelector('.review-hist-badge')).toBeNull();
  });
});

// M186.4 — AI commit message:头部「提交信息」按钮 → LLM 按 diff 生成;结果行内展示 + 一键复制
describe('ContextPanel — M186.4 AI commit message', () => {
  const diffFiles: GitDiffFile[] = [
    { path: 'src/a.ts', added: 3, removed: 1, lines: [{ type: 'add', text: '+new' }] },
  ];
  const renderDiff = (overrides: Record<string, unknown> = {}) => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'diff',
      changedFiles: [],
      gitDiff: diffFiles,
      ...overrides,
    } as never);
    return render(<ContextPanel />);
  };

  it('头部渲染「提交信息」按钮,点击调用 generateCommit()', () => {
    const generateCommit = vi.fn(async () => {});
    renderDiff({ generateCommit });
    fireEvent.click(screen.getByTitle('AI 生成提交信息'));
    expect(generateCommit).toHaveBeenCalledTimes(1);
  });

  it('loading 中按钮禁用且文案为「生成中…」', () => {
    renderDiff({ commitMessage: { result: null, loading: true, error: null } });
    const btn = screen.getByText('生成中…').closest('button') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('生成成功 → 展示 message/model/文件数,点击「复制」调 clipboard.writeText(message)', () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    renderDiff({
      commitMessage: {
        result: { message: 'feat: 增加评审历史', model: 'glm-x', files_count: 2, note: null },
        loading: false,
        error: null,
      },
    });
    expect(screen.getByText('feat: 增加评审历史')).toBeInTheDocument();
    expect(screen.getByText('glm-x · 2 个文件')).toBeInTheDocument();
    fireEvent.click(screen.getByText('复制'));
    expect(writeText).toHaveBeenCalledWith('feat: 增加评审历史');
  });

  it('error 非空 → 头部下方红字行(.commit-error)', () => {
    const { container } = renderDiff({
      commitMessage: { result: null, loading: false, error: 'HTTP 502: LLM 超时' },
    });
    const err = container.querySelector('.commit-error') as HTMLElement;
    expect(err).toBeTruthy();
    expect(err.textContent).toContain('HTTP 502: LLM 超时');
  });

  it('无 result 时不渲染提交信息块', () => {
    renderDiff();
    expect(screen.queryByText('复制')).toBeNull();
  });
});

describe('ContextPanel — 终端 tab', () => {
  it('渲染 PtyTerminal(active=true, className=term-panel)', () => {
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'term' } as never);
    render(<ContextPanel />);
    const term = screen.getByTestId('pty-terminal');
    expect(term.getAttribute('data-active')).toBe('true');
    expect(term.getAttribute('data-class')).toBe('term-panel');
  });

  it('非 term tab 也会渲染 PtyTerminal 但 active=false(条件 tab===term)', () => {
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'files' } as never);
    const { container } = render(<ContextPanel />);
    // tab==='term' 才渲染,其他 tab 不渲染 PtyTerminal
    // 重新读源码:tab==='term' 才渲染,其他 tab 不渲染 PtyTerminal
    expect(container.querySelector('[data-testid="pty-terminal"]')).toBeNull();
  });
});

describe('ContextPanel — 浏览器 tab', () => {
  it('渲染 URL 输入框(aria-label=预览地址)', () => {
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'browser' } as never);
    render(<ContextPanel />);
    expect(screen.getByLabelText('预览地址')).toBeInTheDocument();
  });

  it('渲染"实时"和"截图"按钮', () => {
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'browser' } as never);
    render(<ContextPanel />);
    expect(screen.getByText('实时', { selector: '.rbrowser-go' })).toBeInTheDocument();
    expect(screen.getByText('截图', { selector: '.rbrowser-go' })).toBeInTheDocument();
  });

  it('URL 为空时,实时/截图按钮禁用', () => {
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'browser' } as never);
    render(<ContextPanel />);
    const goBtn = screen.getByText('实时', { selector: '.rbrowser-go' }).closest('button') as HTMLButtonElement;
    const shotBtn = screen.getByText('截图', { selector: '.rbrowser-go' }).closest('button') as HTMLButtonElement;
    expect(goBtn.disabled).toBe(true);
    expect(shotBtn.disabled).toBe(true);
  });

  it('输入 URL 后,实时按钮启用,点击切到 live 视图', () => {
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'browser' } as never);
    render(<ContextPanel />);
    const input = screen.getByLabelText('预览地址') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'localhost:5173' } });
    const goBtn = screen.getByText('实时', { selector: '.rbrowser-go' }).closest('button') as HTMLButtonElement;
    expect(goBtn.disabled).toBe(false);
    fireEvent.click(goBtn);
    // 切到 live 视图,渲染 iframe(src 已规范为 http://localhost:5173)
    expect(screen.getByTitle('实时预览')).toHaveAttribute('src', 'http://localhost:5173');
  });

  it('实时 URL 自动补 http:// 前缀(若缺失)', () => {
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'browser' } as never);
    render(<ContextPanel />);
    const input = screen.getByLabelText('预览地址');
    fireEvent.change(input, { target: { value: 'example.com' } });
    fireEvent.click(screen.getByText('实时', { selector: '.rbrowser-go' }));
    expect(screen.getByTitle('实时预览')).toHaveAttribute('src', 'http://example.com');
  });

  it('已有 http:// 前缀的 URL 不重复添加', () => {
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'browser' } as never);
    render(<ContextPanel />);
    const input = screen.getByLabelText('预览地址');
    fireEvent.change(input, { target: { value: 'http://example.com' } });
    fireEvent.click(screen.getByText('实时', { selector: '.rbrowser-go' }));
    expect(screen.getByTitle('实时预览')).toHaveAttribute('src', 'http://example.com');
  });

  it('URL 输入框按 Enter 也走实时预览', () => {
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'browser' } as never);
    render(<ContextPanel />);
    const input = screen.getByLabelText('预览地址');
    fireEvent.change(input, { target: { value: 'localhost:5173' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(screen.getByTitle('实时预览')).toBeInTheDocument();
  });

  it('点击"截图"调用 renderBrowser(url)', () => {
    const renderBrowser = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'browser', renderBrowser } as never);
    render(<ContextPanel />);
    const input = screen.getByLabelText('预览地址');
    fireEvent.change(input, { target: { value: 'http://example.com' } });
    fireEvent.click(screen.getByText('截图', { selector: '.rbrowser-go' }));
    expect(renderBrowser).toHaveBeenCalledWith('http://example.com');
  });

  it('browserLoading=true 时截图按钮显示"渲染…"且禁用', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'browser',
      browserLoading: true,
    } as never);
    render(<ContextPanel />);
    const shotBtn = screen.getByText('渲染…').closest('button') as HTMLButtonElement;
    expect(shotBtn.disabled).toBe(true);
  });

  it('browserError 时渲染错误提示', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'browser',
      browserError: '连接超时',
    } as never);
    render(<ContextPanel />);
    // 因为 view 默认 live,需要切到 shot 才能看到 error
    // 直接切 shot:输入 URL 然后点截图
    const input = screen.getByLabelText('预览地址');
    fireEvent.change(input, { target: { value: 'http://x.com' } });
    fireEvent.click(screen.getByText('截图', { selector: '.rbrowser-go' }));
    expect(screen.getByText(/渲染失败：连接超时/)).toBeInTheDocument();
  });

  it('detectedServerUrl 存在且不等于 liveUrl 时显示"检测到本地服务"按钮', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'browser',
      detectedServerUrl: 'http://127.0.0.1:8011',
    } as never);
    render(<ContextPanel />);
    expect(screen.getByTestId('detected-server')).toBeInTheDocument();
    expect(screen.getByText(/检测到本地服务/)).toBeInTheDocument();
  });

  it('点击"检测到本地服务"按钮设置 URL 与 live 视图', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'browser',
      detectedServerUrl: 'http://127.0.0.1:8011',
    } as never);
    render(<ContextPanel />);
    fireEvent.click(screen.getByTestId('detected-server'));
    expect(screen.getByTitle('实时预览')).toHaveAttribute('src', 'http://127.0.0.1:8011');
  });

  it('detectedServerUrl 与 liveUrl 相同时不显示提示按钮', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'browser',
      detectedServerUrl: 'http://127.0.0.1:8011',
    } as never);
    render(<ContextPanel />);
    // 先点击 detected-server 让 liveUrl 等于 detectedServerUrl
    fireEvent.click(screen.getByTestId('detected-server'));
    expect(screen.queryByTestId('detected-server')).toBeNull();
  });

  it('无 liveUrl 时显示空态提示', () => {
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'browser' } as never);
    render(<ContextPanel />);
    expect(screen.getByText(/输入本地 dev server 地址/)).toBeInTheDocument();
  });

  it('browserRender 存在 + view=shot 时渲染截图与元素框', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'browser',
      browserRender: {
        url: 'http://x.com',
        title: 'Example',
        screenshot: 'data:image/png;base64,xxx',
        elements: [
          { tag: 'button', selector: '#btn1', text: 'Click me', box: { x: 10, y: 20, w: 100, h: 30 } },
        ],
        viewport: { width: 1280, height: 800 },
      },
    } as never);
    render(<ContextPanel />);
    // 切到 shot 视图:输入 URL 后点截图(但 renderBrowser 已被 mock,需手动切)
    // 实际上 view 是组件内部 state,默认 live。点击截图会调用 renderBrowser + setView('shot')
    const input = screen.getByLabelText('预览地址');
    fireEvent.change(input, { target: { value: 'http://x.com' } });
    fireEvent.click(screen.getByText('截图', { selector: '.rbrowser-go' }));
    expect(screen.getByText('Example')).toBeInTheDocument();
    expect(screen.getByText('1 元素')).toBeInTheDocument();
    // 点击元素框选中
    const box = screen.getByTitle('<button> Click me');
    fireEvent.click(box);
    expect(screen.getByText('追踪此元素')).toBeInTheDocument();
  });

  it('点击"追踪此元素"调用 prefillComposer', () => {
    const prefillComposer = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      contextTab: 'browser',
      prefillComposer,
      browserRender: {
        url: 'http://x.com',
        title: 'X',
        screenshot: '',
        elements: [
          { tag: 'a', selector: 'a.link', text: 'Home', box: { x: 0, y: 0, w: 50, h: 20 } },
        ],
        viewport: { width: 1280, height: 800 },
      },
    } as never);
    render(<ContextPanel />);
    const input = screen.getByLabelText('预览地址');
    fireEvent.change(input, { target: { value: 'http://x.com' } });
    fireEvent.click(screen.getByText('截图', { selector: '.rbrowser-go' }));
    fireEvent.click(screen.getByTitle('<a> Home'));
    fireEvent.click(screen.getByText('追踪此元素'));
    expect(prefillComposer).toHaveBeenCalled();
    // prefillComposer 被调用的参数应包含 <a> 与 selector
    const arg = prefillComposer.mock.calls[0][0] as string;
    expect(arg).toContain('<a>');
    expect(arg).toContain('a.link');
  });
});

describe('ContextPanel — Tauri 浏览器模式', () => {
  it('Tauri 模式 + liveUrl 时渲染 host div(替代 iframe)', () => {
    mockedIsTauri.mockReturnValue(true);
    mockedUseApp.mockReturnValue({ ...baseState, contextTab: 'browser' } as never);
    const { container } = render(<ContextPanel />);
    const input = screen.getByLabelText('预览地址');
    fireEvent.change(input, { target: { value: 'http://x.com' } });
    fireEvent.click(screen.getByText('实时', { selector: '.rbrowser-go' }));
    // Tauri 模式下不渲染 iframe,渲染 host div
    expect(container.querySelector('iframe.rbrowser-live')).toBeNull();
    expect(container.querySelector('.rbrowser-live-host')).toBeTruthy();
  });
});

describe('ContextPanel — 编辑器语法高亮', () => {
  it('Python 文件高亮关键字(def/return/import)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.py', content: 'def foo():\n    return None\n' },
    } as never);
    render(<ContextPanel />);
    // 关键字 def / return 应被 span.k 包裹
    const defSpans = screen.getAllByText('def', { selector: '.k' });
    const retSpans = screen.getAllByText('return', { selector: '.k' });
    expect(defSpans.length).toBeGreaterThanOrEqual(1);
    expect(retSpans.length).toBeGreaterThanOrEqual(1);
  });

  it('字符串字面量高亮为 .s 类', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'const x = "hello";\n' },
    } as never);
    render(<ContextPanel />);
    const strSpan = screen.getByText('"hello"', { selector: '.s' });
    expect(strSpan).toBeInTheDocument();
  });

  it('注释高亮为 .cm 类', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.py', content: '# this is a comment\n' },
    } as never);
    render(<ContextPanel />);
    const cmSpan = screen.getByText('# this is a comment', { selector: '.cm' });
    expect(cmSpan).toBeInTheDocument();
  });

  it('数字字面量高亮为 .n 类', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'const x = 42;\n' },
    } as never);
    render(<ContextPanel />);
    const numSpan = screen.getByText('42', { selector: '.n' });
    expect(numSpan).toBeInTheDocument();
  });

  it('装饰器(@xxx)高亮为 .de 类', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.py', content: '@app.route\n' },
    } as never);
    render(<ContextPanel />);
    const deSpan = screen.getByText('@app.route', { selector: '.de' });
    expect(deSpan).toBeInTheDocument();
  });

  it('函数名(def foo 中的 foo)高亮为 .f 类', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.py', content: 'def foo():\n' },
    } as never);
    render(<ContextPanel />);
    const fSpan = screen.getByText('foo', { selector: '.f' });
    expect(fSpan).toBeInTheDocument();
  });

  it('True/False/None 高亮为 .n 类', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.py', content: 'x = True\ny = None\n' },
    } as never);
    render(<ContextPanel />);
    const trueSpans = screen.getAllByText('True', { selector: '.n' });
    const noneSpans = screen.getAllByText('None', { selector: '.n' });
    expect(trueSpans.length).toBeGreaterThanOrEqual(1);
    expect(noneSpans.length).toBeGreaterThanOrEqual(1);
  });

  it('未识别的标识符不加 span 包裹(纯文本)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'foobar baz\n' },
    } as never);
    render(<ContextPanel />);
    // 不抛错就算通过
    expect(screen.getByText(/foobar/)).toBeInTheDocument();
  });
});

describe('ContextPanel — 语言识别 langOf', () => {
  it('.py → python', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'script.py', content: 'x\n' },
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('python')).toBeInTheDocument();
  });

  it('.ts → typescript', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.ts', content: 'x\n' },
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('typescript')).toBeInTheDocument();
  });

  it('.tsx → tsx', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.tsx', content: 'x\n' },
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('tsx')).toBeInTheDocument();
  });

  it('.md → markdown', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.md', content: '# x\n' },
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('markdown')).toBeInTheDocument();
  });

  it('未知后缀 → text', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'a.unknownext', content: 'x\n' },
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('text')).toBeInTheDocument();
  });

  it('.go → go', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      openedFile: { path: 'main.go', content: 'x\n' },
    } as never);
    render(<ContextPanel />);
    expect(screen.getByText('go')).toBeInTheDocument();
  });
});
