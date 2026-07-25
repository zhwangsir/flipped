import { afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { ToolCard } from './ToolCard';
import type { AssistantTool } from '../types';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const makeTool = (overrides: Partial<AssistantTool> = {}): AssistantTool => ({
  tool: 'terminal',
  status: 'ok',
  summary: '$ ls -la',
  output: 'total 0\ndrwxr-xr-x 2 user staff 64 Jan 1 00:00 src',
  ...overrides,
});

describe('ToolCard — 状态与折叠行为', () => {
  it('running 时显示 spinner(无 body)', () => {
    render(<ToolCard tool={makeTool({ status: 'running', output: undefined, summary: '$ npm run build' })} />);
    const card = screen.getByTestId('assistant-tool-card');
    expect(card.className).toContain('running');
    expect(screen.getByTestId('assistant-tool-spinner')).toBeTruthy();
    // running 且无 output → 无 body
    expect(screen.queryByTestId('assistant-tool-body')).toBeNull();
  });

  it('ok 时默认折叠,点击展开 body', () => {
    render(<ToolCard tool={makeTool({ status: 'ok' })} />);
    // 默认折叠
    expect(screen.queryByTestId('assistant-tool-body')).toBeNull();
    // 点击 head 展开
    fireEvent.click(screen.getByTestId('assistant-tool-head'));
    expect(screen.getByTestId('assistant-tool-body')).toBeTruthy();
    expect(screen.getByTestId('assistant-tool-body').textContent).toContain('total 0');
    // 再点击折叠
    fireEvent.click(screen.getByTestId('assistant-tool-head'));
    expect(screen.queryByTestId('assistant-tool-body')).toBeNull();
  });

  it('error 时自动展开 body(无需点击)', () => {
    render(<ToolCard tool={makeTool({ status: 'error', output: 'Command failed: exit 1' })} />);
    // error 自动展开
    const body = screen.getByTestId('assistant-tool-body');
    expect(body).toBeTruthy();
    expect(body.textContent).toContain('Command failed');
    // 状态标签显示「失败」
    expect(screen.getByTestId('assistant-tool-status').textContent).toContain('失败');
  });
});
