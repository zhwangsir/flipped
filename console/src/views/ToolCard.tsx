/**
 * M151.4 · Assistant 视图工具卡(从 Conversation.ToolRow 抽取,Codex 风折叠态)。
 *
 * 与 Conversation.ToolRow 的差异:
 * - 数据源是 AssistantTool(后端 /assistant/history 折叠后),不是事件流 ToolCall;
 * - 没有子节点数组,工具 body 只展示 output + summary 文本;
 * - 状态语义一致:running=spinner / ok=折叠+点击展开 / error=自动展开。
 */
import { useEffect, useState } from 'react';
import type { AssistantTool } from '../types';
import { IconCheck, IconChevronDown, IconTerminal, IconFile, IconBrowser, IconSearch } from '../icons';

/** 工具图标:与 Conversation.ToolIcon 一致,但本视图不引 Conversation 模块(避免循环依赖)。 */
function ToolIcon({ name, size = 13 }: { name: string; size?: number }) {
  if (name === 'terminal') return <IconTerminal size={size} />;
  if (name === 'browser') return <IconBrowser size={size} />;
  if (name === 'search') return <IconSearch size={size} />;
  return <IconFile size={size} />;
}

const STATUS_TEXT: Record<string, string> = {
  ok: '完成',
  running: '运行中',
  error: '失败',
};

/** 工具主文本:终端显示 `$ 命令`,文件显示路径,其余显示 summary 或工具名。 */
function toolPrimary(tool: AssistantTool): { text: string; mono: boolean } {
  const summary = (tool.summary && tool.summary !== tool.tool ? tool.summary : '').trim();
  if (tool.tool === 'terminal') {
    const cmd = (tool.args as { command?: string } | undefined)?.command;
    return { text: '$ ' + (cmd || summary || '命令'), mono: true };
  }
  if (tool.tool === 'file_editor') {
    const path = (tool.args as { path?: string } | undefined)?.path;
    return { text: path || summary || '编辑文件', mono: true };
  }
  return { text: summary || tool.tool || '工具', mono: false };
}

export interface ToolCardProps {
  tool: AssistantTool;
  /** 受控展开(可选)。不传时由组件内部自管,默认 error 自动展开。 */
  defaultOpen?: boolean;
}

export function ToolCard({ tool, defaultOpen }: ToolCardProps) {
  const body = (tool.output && tool.output.trim().length > 0) || (tool.summary && tool.summary.trim().length > 0);
  const hasBody = !!body;
  // error 自动展开;running/ok 默认折叠
  const [open, setOpen] = useState(defaultOpen ?? tool.status === 'error');

  // tool.status 在外部变化(如 running → ok)时,error 才自动展开,其余保持原状
  useEffect(() => {
    if (tool.status === 'error') setOpen(true);
  }, [tool.status]);

  const primary = toolPrimary(tool);

  return (
    <div className={'assistant-tool ' + tool.status} data-testid='assistant-tool-card'>
      <button
        type='button'
        className='tool-head'
        aria-expanded={hasBody ? open : undefined}
        onClick={() => hasBody && setOpen((o) => !o)}
        disabled={!hasBody}
        data-testid='assistant-tool-head'
      >
        <span className='tool-ic'>
          <ToolIcon name={tool.tool} />
        </span>
        <span className={'tool-label' + (primary.mono ? ' mono' : '')}>{primary.text}</span>
        <span className={'tool-status ' + tool.status} data-testid='assistant-tool-status'>
          {tool.status === 'running' && <span className='tool-spin' data-testid='assistant-tool-spinner' />}
          {tool.status === 'ok' && <IconCheck size={11} />}
          {STATUS_TEXT[tool.status] || tool.status}
        </span>
        {hasBody && (
          <span className={'tool-chev' + (open ? ' open' : '')} aria-hidden='true'>
            <IconChevronDown size={13} />
          </span>
        )}
      </button>
      {open && hasBody && (
        <div className='tool-body' data-testid='assistant-tool-body'>
          {tool.summary && tool.summary.trim() && <div>{tool.summary}</div>}
          {tool.output && tool.output.trim() && <div>{tool.output}</div>}
        </div>
      )}
    </div>
  );
}
