/**
 * M151.4 · Assistant 视图 Composer(底部固定多行 textarea + slash 自动补全)。
 *
 * 设计要点:
 * - Enter 发送,Shift+Enter 换行(与 Codex / ChatGPT 一致);
 * - slash 命令补全:/clear /compact /mode /help /files 5 项;
 * - 12k 字符警告(超过则在 composer 下方显示红色提示,仍允许发送);
 * - 空输入不发送;busy 时禁用;
 * - slash 命令(/clear /compact /mode /help /files)不通过 onSend,通过 onSlash 回调,
 *   让外层决定如何处置(/clear=清空对话,/help=显示帮助,etc)。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { IconSend } from '../icons';

const SLASH_COMMANDS: { cmd: string; desc: string }[] = [
  { cmd: '/clear', desc: '清空当前对话' },
  { cmd: '/compact', desc: '压缩上下文' },
  { cmd: '/mode', desc: '切换模式 (agent/chat/plan)' },
  { cmd: '/help', desc: '查看帮助' },
  { cmd: '/files', desc: '查看项目文件' },
];

export const CHAR_WARN_THRESHOLD = 12000;

export interface ComposerProps {
  onSend: (text: string) => void;
  onSlash?: (cmd: string) => void;
  busy?: boolean;
  disabled?: boolean;
  mode?: string;
  onModeChange?: (mode: string) => void;
  model?: string;
  onModelChange?: (model: string) => void;
  placeholder?: string;
}

export function Composer({
  onSend,
  onSlash,
  busy = false,
  disabled = false,
  mode = 'agent',
  onModeChange,
  model = 'coder',
  onModelChange,
  placeholder = '给助手下指令,或问任何问题…',
}: ComposerProps) {
  const [text, setText] = useState('');
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashSel, setSlashSel] = useState(0);
  const taRef = useRef<HTMLTextAreaElement>(null);

  // 当前 slash 查询串(textarea 光标前最近的 /xxx token)
  const slashQuery = useMemo(() => {
    if (!text) return null;
    const cursor = taRef.current?.selectionStart ?? text.length;
    const m = /(?:^|\s)(\/[a-z]*)$/.exec(text.slice(0, cursor));
    return m ? m[1] : null;
  }, [text]);

  const matches = useMemo(() => {
    if (slashQuery === null) return [];
    const q = slashQuery.toLowerCase();
    return SLASH_COMMANDS.filter((c) => c.cmd.toLowerCase().startsWith(q));
  }, [slashQuery]);

  useEffect(() => {
    setSlashOpen(matches.length > 0);
    setSlashSel(0);
  }, [matches.length]);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || busy || disabled) return;
    // 纯 slash 命令走 onSlash 回调,不走 onSend
    const slashMatch = SLASH_COMMANDS.find((c) => c.cmd === trimmed);
    if (slashMatch && onSlash) {
      onSlash(slashMatch.cmd);
      setText('');
      return;
    }
    onSend(trimmed);
    setText('');
  };

  const pickSlash = (cmd: string) => {
    if (!onSlash) {
      // 无 onSlash 处理器 → 直接把命令填进输入框供用户回车
      setText(cmd + ' ');
      setSlashOpen(false);
      requestAnimationFrame(() => taRef.current?.focus());
      return;
    }
    onSlash(cmd);
    setText('');
    setSlashOpen(false);
  };

  const overCharLimit = text.length > CHAR_WARN_THRESHOLD;
  const isDisabled = busy || disabled;

  return (
    <div className='assistant-composer' data-testid='assistant-composer'>
      <div className='composer-wrap'>
        {slashOpen && matches.length > 0 && (
          <div className='slash-menu' role='listbox' aria-label='斜杠命令' data-testid='slash-menu'>
            {matches.map((m, i) => (
              <button
                key={m.cmd}
                type='button'
                role='option'
                aria-selected={i === slashSel}
                className={'slash-item' + (i === slashSel ? ' active' : '')}
                onMouseMove={() => setSlashSel(i)}
                onClick={() => pickSlash(m.cmd)}
              >
                <span className='slash-cmd'>{m.cmd}</span>
                <span className='slash-desc'>{m.desc}</span>
              </button>
            ))}
          </div>
        )}
        <textarea
          ref={taRef}
          data-testid='assistant-composer-input'
          rows={2}
          placeholder={placeholder}
          aria-label='助手输入'
          value={text}
          disabled={isDisabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (slashOpen && matches.length > 0) {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setSlashSel((s) => Math.min(s + 1, matches.length - 1));
                return;
              }
              if (e.key === 'ArrowUp') {
                e.preventDefault();
                setSlashSel((s) => Math.max(s - 1, 0));
                return;
              }
              if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault();
                pickSlash(matches[slashSel].cmd);
                return;
              }
              if (e.key === 'Escape') {
                e.preventDefault();
                setSlashOpen(false);
                return;
              }
            }
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className='composer-bar'>
          {onModeChange && (
            <select
              className='mode-sel'
              data-testid='assistant-mode-sel'
              value={mode}
              onChange={(e) => onModeChange(e.target.value)}
              disabled={isDisabled}
              title='模式'
            >
              <option value='auto'>自主</option>
              <option value='agent'>智能体</option>
              <option value='chat'>对话</option>
              <option value='plan'>规划</option>
            </select>
          )}
          {onModelChange && (
            <select
              className='model-sel'
              data-testid='assistant-model-sel'
              value={model}
              onChange={(e) => onModelChange(e.target.value)}
              disabled={isDisabled}
              title='模型'
            >
              <option value='coder'>Kimi-K2.7 · coder</option>
              <option value='architect'>GLM-5.2 · architect</option>
            </select>
          )}
          <span className='spacer' />
          {overCharLimit && (
            <span className='char-warn' data-testid='assistant-char-warn'>
              字符数 {text.length} 已超 12k 警告线
            </span>
          )}
          <button
            className='send-btn'
            type='button'
            data-testid='assistant-send-btn'
            onClick={submit}
            disabled={isDisabled || !text.trim()}
            aria-label='发送'
          >
            <IconSend size={14} /> 发送
          </button>
        </div>
      </div>
    </div>
  );
}
