import { afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { RulesPanel } from './RulesPanel';
import type { ProjectRulesInfo } from '../types';

// 面板自取数:mock ../api 模块(不经 store),与 ProjectMapPanel.test 同范式
vi.mock('../api', () => ({
  fetchProjectRules: vi.fn(),
  saveProjectRules: vi.fn(),
}));

import { fetchProjectRules, saveProjectRules } from '../api';

const mockedFetch = vi.mocked(fetchProjectRules);
const mockedSave = vi.mocked(saveProjectRules);

const sampleRules: ProjectRulesInfo = {
  files: ['.flipped/rules.md', 'AGENTS.md'],
  markdown: '## .flipped/rules.md\n\n- 禁止 console.log\n\n## AGENTS.md\n\n先计划后动手\n',
  total_chars: 120,
  rules_content: '- 禁止 console.log\n',
  needs_project: false,
};

const emptyRules: ProjectRulesInfo = {
  files: [],
  markdown: '',
  total_chars: 0,
  rules_content: '',
  needs_project: false,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('RulesPanel', () => {
  it('查看态渲染 files 徽标(多文件 chip 齐全)', async () => {
    mockedFetch.mockResolvedValue(sampleRules);
    render(<RulesPanel />);
    await waitFor(() => expect(document.querySelectorAll('.rules-chip').length).toBe(2));
    const chips = [...document.querySelectorAll('.rules-chip')].map((c) => c.textContent);
    expect(chips).toEqual(['.flipped/rules.md', 'AGENTS.md']);
  });

  it('markdown 经 renderMarkdown 渲染(.md-doc 内含规则文本)', async () => {
    mockedFetch.mockResolvedValue(sampleRules);
    render(<RulesPanel />);
    await waitFor(() => expect(screen.getByText('禁止 console.log')).toBeInTheDocument());
    expect(screen.getByText('先计划后动手')).toBeInTheDocument();
    expect(document.querySelector('.md-doc')).toBeTruthy();
    expect(screen.getByText('禁止 console.log').tagName).toBe('LI');
  });

  it('files 空 → 空态「暂无规则」+ 引导文案 + 「新建规则」按钮', async () => {
    mockedFetch.mockResolvedValue(emptyRules);
    render(<RulesPanel />);
    await waitFor(() => expect(screen.getByText('暂无规则')).toBeInTheDocument());
    expect(screen.getByText(/规则将注入每次对话|将注入每次对话/)).toBeInTheDocument();
    expect(screen.getByText('新建规则')).toBeInTheDocument();
    expect(screen.queryByText('编辑')).toBeNull();
  });

  it('点「编辑」→ textarea 初值 === rules_content', async () => {
    mockedFetch.mockResolvedValue(sampleRules);
    render(<RulesPanel />);
    await waitFor(() => expect(screen.getByText('禁止 console.log')).toBeInTheDocument());
    fireEvent.click(screen.getByText('编辑'));
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    expect(textarea.value).toBe(sampleRules.rules_content);
  });

  it('点「保存」→ 调 saveProjectRules(编辑后文本),成功后回查看态渲染新 markdown', async () => {
    mockedFetch.mockResolvedValue(sampleRules);
    mockedSave.mockResolvedValue({
      ...sampleRules,
      markdown: '## .flipped/rules.md\n\n- 全部函数式组件\n',
      rules_content: '- 全部函数式组件\n',
      total_chars: 30,
    });
    render(<RulesPanel />);
    await waitFor(() => expect(screen.getByText('禁止 console.log')).toBeInTheDocument());
    fireEvent.click(screen.getByText('编辑'));
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '- 全部函数式组件\n' } });
    fireEvent.click(screen.getByText('保存'));
    await waitFor(() => expect(screen.getByText('全部函数式组件')).toBeInTheDocument());
    expect(mockedSave).toHaveBeenCalledTimes(1);
    expect(mockedSave).toHaveBeenCalledWith('- 全部函数式组件\n');
    // 已回查看态:textarea 消失,旧内容被 PUT 返回值刷新
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByText('禁止 console.log')).toBeNull();
  });

  it('保存中按钮禁用 + 文案「保存中…」', async () => {
    mockedFetch.mockResolvedValue(sampleRules);
    mockedSave.mockReturnValue(new Promise(() => {})); // 永不 resolve,保持 busy
    render(<RulesPanel />);
    await waitFor(() => expect(screen.getByText('禁止 console.log')).toBeInTheDocument());
    fireEvent.click(screen.getByText('编辑'));
    fireEvent.click(screen.getByText('保存'));
    const saveBtn = screen.getByText('保存中…') as HTMLButtonElement;
    expect(saveBtn.disabled).toBe(true);
  });

  it('保存失败 → 红字行展示 error 且编辑态不收起(textarea 仍在)', async () => {
    mockedFetch.mockResolvedValue(sampleRules);
    mockedSave.mockRejectedValue(new Error('HTTP 422: content 超长'));
    render(<RulesPanel />);
    await waitFor(() => expect(screen.getByText('禁止 console.log')).toBeInTheDocument());
    fireEvent.click(screen.getByText('编辑'));
    fireEvent.click(screen.getByText('保存'));
    await waitFor(() => expect(screen.getByText(/HTTP 422: content 超长/)).toBeInTheDocument());
    expect(screen.getByRole('textbox')).toBeInTheDocument(); // 编辑态不收起
    expect(screen.getByText('保存')).toBeInTheDocument();
  });

  it('点「取消」→ 不调 api、回查看态、改动丢弃', async () => {
    mockedFetch.mockResolvedValue(sampleRules);
    render(<RulesPanel />);
    await waitFor(() => expect(screen.getByText('禁止 console.log')).toBeInTheDocument());
    fireEvent.click(screen.getByText('编辑'));
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '改过的内容' } });
    fireEvent.click(screen.getByText('取消'));
    expect(mockedSave).not.toHaveBeenCalled();
    expect(screen.queryByRole('textbox')).toBeNull(); // 回查看态
    expect(screen.getByText('禁止 console.log')).toBeInTheDocument();
    // 再次进入编辑:初值仍是 rules_content,改动已丢弃
    fireEvent.click(screen.getByText('编辑'));
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe(sampleRules.rules_content);
  });

  it('needs_project=true → side-empty 空态', async () => {
    mockedFetch.mockResolvedValue({ ...emptyRules, needs_project: true });
    render(<RulesPanel />);
    await waitFor(() => expect(screen.getByText(/未选择项目 · 在底部「选择项目」导入或新建/)).toBeInTheDocument());
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('加载失败 → 红字 + 重试可恢复', async () => {
    mockedFetch.mockRejectedValueOnce(new Error('HTTP 500: boom'));
    render(<RulesPanel />);
    await waitFor(() => expect(screen.getByText(/规则加载失败：HTTP 500: boom/)).toBeInTheDocument());
    mockedFetch.mockResolvedValue(sampleRules);
    fireEvent.click(screen.getByText('重试'));
    await waitFor(() => expect(screen.getByText('禁止 console.log')).toBeInTheDocument());
    expect(mockedFetch).toHaveBeenCalledTimes(2);
  });
});
