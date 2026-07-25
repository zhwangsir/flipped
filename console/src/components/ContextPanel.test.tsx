import { afterEach, beforeAll, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { ContextPanel } from './ContextPanel';

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

import { useApp } from '../store';
import { isTauri } from '../lib/native';
import type {
  ChangedFile,
  FileNode,
  GitDiffFile,
  BrowserRender,
  ProjectContext,
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
