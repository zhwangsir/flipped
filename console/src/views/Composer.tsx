/**
 * M151.4 · Assistant 视图 Composer(底部固定多行 textarea + slash 自动补全)。
 *
 * 设计要点:
 * - Enter 发送,Shift+Enter 换行(与 Codex / ChatGPT 一致);
 * - slash 命令补全:/clear /compact /mode /help /files 5 项;
 * - 12k 字符警告(超过则在 composer 下方显示红色提示,仍允许发送);
 * - 空输入不发送;
 * - M167.4(opencode 对标):busy(running)时输入框保持可用,Enter 把消息入队
 *   (store 自动 drain),发送键位换成停止按钮,Esc 中断当前生成;
 * - slash 命令(/clear /compact /mode /help /files)不通过 onSend,通过 onSlash 回调,
 *   让外层决定如何处置(/clear=清空对话,/help=显示帮助,etc)。
 * - M192 — 图像附件(仅 chat/plan):ImagePlus 按钮/隐藏 file input/textarea 粘贴
 *   三入口同一 addFiles;≤4 张、单张 ≤2MB、png/jpeg/webp/gif 白名单;onSend 升级
 *   为 (text, images),发送成功清空 chips,onSend 返回 rejected promise 时保留供重试。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { IconSend, IconStop, IconImagePlus } from '../icons';
import { useApp } from '../store';
import { fetchProjectFiles } from '../api';
import type { FileNode, PendingImage } from '../types';

// M192 — 供外层(store/Assistant)引用的附件类型(定义在 types.ts,此处再导出保持 Composer 契约面)
export type { PendingImage } from '../types';

/** M192 — 图像附件约束(与后端契约 FLIPPED_IMG_MAX_COUNT / FLIPPED_IMG_MAX_BYTES 对齐)。 */
export const IMG_MAX_COUNT = 4;
export const IMG_MAX_BYTES = 2 * 1024 * 1024;
const IMG_ACCEPT = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

/** M192 — chips 内部态:PendingImage + 预览 dataURL(preview 不进请求体)。 */
type PendingAtt = PendingImage & { preview: string };

const SLASH_COMMANDS: { cmd: string; desc: string }[] = [
  { cmd: '/clear', desc: '清空当前对话' },
  { cmd: '/compact', desc: '压缩上下文' },
  { cmd: '/mode', desc: '切换模式 (agent/chat/plan)' },
  { cmd: '/help', desc: '查看帮助' },
  { cmd: '/files', desc: '查看项目文件' },
  { cmd: '/undo', desc: '撤销最近一轮改动' },
  // M176 — Goal 模式:目标驱动自循环(带参数,pick 只填充,submit 走 onGoal)
  { cmd: '/goal', desc: '目标驱动自循环:/goal <可验证目标>' },
];

export const CHAR_WARN_THRESHOLD = 12000;

export interface ComposerProps {
  /** M192 — 第二参为图像附件(无附件为空数组);返回 promise 时成功才清空 chips,失败保留供重试 */
  onSend: (text: string, images: PendingImage[]) => void | Promise<void>;
  onSlash?: (cmd: string) => void;
  /** M176 — /goal <目标> 提交回调(带参时优先于 onSend) */
  onGoal?: (objective: string) => void;
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
  onGoal,
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
  // M175 — @ 文件引用补全(镜像 slash 模式;filesRef=null 表示尚未拉取)
  const [atOpen, setAtOpen] = useState(false);
  const [atSel, setAtSel] = useState(0);
  const filesRef = useRef<{ path: string; name: string }[] | null>(null);
  // 拉取完成后 bump 一下让 atMatches 重算(ref 变更不触发渲染)
  const [filesTick, setFilesTick] = useState(0);
  // pickAt 替换 token 后 DOM selection 不会自动移到替换文本末尾,这里记录目标光标位
  // 供 atQuery 优先消费(用户再次输入时清空)
  const pendingCursorRef = useRef<number | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  // M192 — 图像附件 chips 状态(pendingRef 镜像供 addFiles 同步读取最新张数,防快速连选竞态)
  const [pending, setPending] = useState<PendingAtt[]>([]);
  const pendingRef = useRef<PendingAtt[]>([]);
  const [attachWarn, setAttachWarn] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  // M192 — 仅 chat/plan 支持图像附件(agent/auto 的 supervisor/worker 模型为 text-only)
  const imageEnabled = mode === 'chat' || mode === 'plan';

  /** M192 — 按钮选文件/粘贴共用入口:白名单过滤 → 张数/大小校验 → FileReader 读 dataURL 进 chips。 */
  const addFiles = (files: File[]) => {
    const imgs = files.filter((f) => IMG_ACCEPT.includes(f.type));
    if (imgs.length === 0) return; // 非图像静默忽略(文本粘贴不受影响)
    let warn: string | null = null;
    const accepted: { att: PendingAtt; file: File }[] = [];
    let count = pendingRef.current.length;
    for (const f of imgs) {
      if (count >= IMG_MAX_COUNT) {
        warn = `最多附加 ${IMG_MAX_COUNT} 张图片`;
        break;
      }
      if (f.size > IMG_MAX_BYTES) {
        warn = `图片 ${f.name} 超过 2MB 上限`;
        continue;
      }
      count += 1;
      accepted.push({ att: { name: f.name, media_type: f.type, data_base64: '', preview: '' }, file: f });
    }
    if (accepted.length > 0) {
      const next = [...pendingRef.current, ...accepted.map((a) => a.att)];
      pendingRef.current = next;
      setPending(next);
    }
    setAttachWarn(warn);
    // 异步读 dataURL,按对象 identity 回写占位 chip(移除过的自动跳过)
    for (const { att, file } of accepted) {
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = String(reader.result || '');
        const comma = dataUrl.indexOf(',');
        const b64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl; // 剥掉 "data:<mt>;base64," 前缀
        setPending((prev) => {
          const idx = prev.indexOf(att);
          if (idx < 0) return prev;
          const copy = [...prev];
          copy[idx] = { ...att, data_base64: b64, preview: dataUrl };
          pendingRef.current = copy;
          return copy;
        });
      };
      reader.readAsDataURL(file);
    }
  };

  const removeAtt = (i: number) => {
    const copy = pendingRef.current.filter((_, j) => j !== i);
    pendingRef.current = copy;
    setPending(copy);
  };

  const clearAtts = () => {
    pendingRef.current = [];
    setPending([]);
    setAttachWarn(null);
  };
  // M167.4 — 排队/停止能力直接取自 store,Assistant 无需新增 props
  // (assistantQueue 兜底 []:旧 mock 未提供该字段时不炸渲染)
  const {
    assistantQueue = [],
    enqueueAssistantMessage,
    removeAssistantQueued,
    stopAssistantTask,
  } = useApp();

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

  // 当前 @ 查询串(textarea 光标前最近的 @xxx token,可含引号包裹的带空格路径)
  const atQuery = useMemo(() => {
    if (!text) return null;
    const cursor = pendingCursorRef.current ?? taRef.current?.selectionStart ?? text.length;
    const m = /(?:^|\s)(@(?:"[^"]*)?[^\s@"]*)$/.exec(text.slice(0, cursor));
    return m ? m[1] : null;
  }, [text]);

  // 首次出现 @ 查询时拉取项目文件树并拍平缓存;失败则置空数组(不再重试,静默)
  useEffect(() => {
    if (atQuery === null || filesRef.current !== null) return;
    fetchProjectFiles()
      .then(({ tree }) => {
        const flat: { path: string; name: string }[] = [];
        const walk = (nodes: FileNode[]) => {
          for (const n of nodes) {
            if (n.type === 'file') {
              flat.push({ path: n.path, name: n.path.split('/').pop() || n.path });
            }
            if (n.children) walk(n.children);
          }
        };
        walk(tree);
        filesRef.current = flat;
        setFilesTick((t) => t + 1);
      })
      .catch(() => {
        filesRef.current = [];
        setFilesTick((t) => t + 1);
      });
  }, [atQuery]);

  const atMatches = useMemo(() => {
    if (atQuery === null) return [];
    const files = filesRef.current;
    if (!files) return [];
    const q = atQuery
      .slice(1)
      .replace(/^"|"$/g, '')
      .toLowerCase();
    const rank = (f: { path: string; name: string }) => {
      const name = f.name.toLowerCase();
      const path = f.path.toLowerCase();
      if (name.startsWith(q)) return 0;
      if (path.startsWith(q)) return 1;
      return 2;
    };
    return files
      .filter((f) => f.name.toLowerCase().includes(q) || f.path.toLowerCase().includes(q))
      .sort((a, b) => rank(a) - rank(b))
      .slice(0, 8);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [atQuery, filesTick]);

  useEffect(() => {
    setAtOpen(atMatches.length > 0);
    setAtSel(0);
  }, [atMatches.length]);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    // M167.4 — busy(running)中:Enter 入队而非发送,清空输入框;
    // store 的 drain effect 会在 busy 落下后依序自动发送
    if (busy) {
      enqueueAssistantMessage?.(trimmed);
      setText('');
      return;
    }
    // M176 — /goal <目标>(slash 精确匹配前检测):带参走 onGoal;
    // 空参数或未提供 onGoal → 退化为普通发送流程
    if (trimmed.startsWith('/goal ') && onGoal) {
      const objective = trimmed.slice(6).trim();
      if (objective) {
        onGoal(objective);
        setText('');
        return;
      }
    }
    // 纯 slash 命令走 onSlash 回调,不走 onSend
    const slashMatch = SLASH_COMMANDS.find((c) => c.cmd === trimmed);
    if (slashMatch && onSlash) {
      onSlash(slashMatch.cmd);
      setText('');
      return;
    }
    // M192 — 附件随消息发出(preview 仅本地展示,不进请求体);
    // onSend 返回 promise:成功清空 chips,失败(rejected)保留供重试;
    // 返回 void(旧调用方):按同步成功处理,与 text 清空时机一致
    const images: PendingImage[] = pendingRef.current.map(({ name, media_type, data_base64 }) => ({
      name,
      media_type,
      data_base64,
    }));
    const res = onSend(trimmed, images);
    setText('');
    if (res && typeof (res as Promise<void>).then === 'function') {
      Promise.resolve(res)
        .then(() => clearAtts())
        .catch(() => {
          /* 发送失败:保留 chips 供重试(错误反馈走 store assistantError) */
        });
    } else {
      clearAtts();
    }
  };

  const pickSlash = (cmd: string) => {
    // M176 — /goal 带参数:pick 只填充 "/goal " 等用户补目标,不立即执行
    if (cmd === '/goal') {
      setText('/goal ');
      setSlashOpen(false);
      requestAnimationFrame(() => taRef.current?.focus());
      return;
    }
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

  // M175 — 选中文件:把光标前 @query token 替换为 @path(含空格则引号包裹)
  const pickAt = (path: string) => {
    if (atQuery !== null) {
      const cursor = pendingCursorRef.current ?? taRef.current?.selectionStart ?? text.length;
      const replacement = path.includes(' ') ? `@"${path}" ` : `@${path} `;
      const nextCursor = cursor - atQuery.length + replacement.length;
      pendingCursorRef.current = nextCursor;
      setText(text.slice(0, cursor - atQuery.length) + replacement + text.slice(cursor));
      requestAnimationFrame(() => {
        taRef.current?.setSelectionRange(nextCursor, nextCursor);
        taRef.current?.focus();
      });
    }
    setAtOpen(false);
  };

  const overCharLimit = text.length > CHAR_WARN_THRESHOLD;
  // M167.4 — busy 不再禁用输入框(仅 disabled prop 禁用);
  // isDisabled 仅保留给模式/模型下拉(busy 中不切模式/模型,避免影响后续发送)
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
        {atOpen && atMatches.length > 0 && (
          <div className='at-menu' role='listbox' aria-label='文件引用' data-testid='at-menu'>
            {atMatches.map((f, i) => (
              <button
                key={f.path}
                type='button'
                role='option'
                aria-selected={i === atSel}
                className={'at-item' + (i === atSel ? ' active' : '')}
                data-testid='at-item'
                onMouseMove={() => setAtSel(i)}
                onClick={() => pickAt(f.path)}
              >
                <span className='at-name'>{f.name}</span>
                <span className='at-path'>{f.path}</span>
              </button>
            ))}
          </div>
        )}
        {assistantQueue.length > 0 && (
          <div
            className='composer-queue'
            data-testid='composer-queue'
            style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '8px 12px 0' }}
          >
            {assistantQueue.map((q, i) => (
              <span
                key={`${i}-${q}`}
                className='chip'
                data-testid={`queue-chip-${i}`}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                <span>
                  {i + 1}. {q.length > 40 ? `${q.slice(0, 40)}…` : q}
                </span>
                <button
                  type='button'
                  data-testid={`queue-remove-${i}`}
                  aria-label={`移除第 ${i + 1} 条排队消息`}
                  onClick={() => removeAssistantQueued?.(i)}
                  style={{
                    background: 'none',
                    border: 'none',
                    padding: 0,
                    cursor: 'pointer',
                    color: 'inherit',
                    font: 'inherit',
                    lineHeight: 1,
                  }}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        {pending.length > 0 && (
          <div
            className='composer-atts'
            data-testid='composer-atts'
            style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '8px 12px 0' }}
          >
            {pending.map((p, i) => (
              <span
                key={`${i}-${p.name}`}
                className='chip'
                data-testid={`composer-att-${i}`}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                {p.preview && (
                  <img
                    src={p.preview}
                    alt={p.name}
                    style={{ width: 32, height: 32, objectFit: 'cover', borderRadius: 4, display: 'block' }}
                  />
                )}
                <span>{p.name}</span>
                <button
                  type='button'
                  data-testid={`composer-att-remove-${i}`}
                  aria-label={`移除图片 ${p.name}`}
                  onClick={() => removeAtt(i)}
                  style={{
                    background: 'none',
                    border: 'none',
                    padding: 0,
                    cursor: 'pointer',
                    color: 'inherit',
                    font: 'inherit',
                    lineHeight: 1,
                  }}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        {/* M192 — 隐藏 file input:ImagePlus 按钮触发;accept 与后端白名单一致 */}
        <input
          ref={fileRef}
          type='file'
          accept='image/png,image/jpeg,image/webp,image/gif'
          multiple
          data-testid='composer-attach-input'
          style={{ display: 'none' }}
          onChange={(e) => {
            addFiles(Array.from(e.target.files ?? []));
            e.target.value = ''; // 允许重选同一文件
          }}
        />
        <textarea
          ref={taRef}
          data-testid='assistant-composer-input'
          rows={2}
          placeholder={placeholder}
          aria-label='助手输入'
          value={text}
          disabled={disabled}
          onChange={(e) => {
            pendingCursorRef.current = null;
            setText(e.target.value);
          }}
          onPaste={(e) => {
            // M192 — 剪贴板图像文件与按钮选文件走同一入口;纯文本粘贴不受影响
            const files = Array.from(e.clipboardData?.files ?? []).filter((f) =>
              IMG_ACCEPT.includes(f.type)
            );
            if (files.length > 0) {
              e.preventDefault();
              addFiles(files);
            }
          }}
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
            // M175 — @ 菜单键盘(与 slash 天然互斥:一个以 / 开头一个以 @ 开头)
            if (atOpen && atMatches.length > 0) {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setAtSel((s) => Math.min(s + 1, atMatches.length - 1));
                return;
              }
              if (e.key === 'ArrowUp') {
                e.preventDefault();
                setAtSel((s) => Math.max(s - 1, 0));
                return;
              }
              if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault();
                pickAt(atMatches[atSel].path);
                return;
              }
              if (e.key === 'Escape') {
                e.preventDefault();
                setAtOpen(false);
                return;
              }
            }
            // M167.4 — Esc 中断当前生成(opencode 行为);slash 菜单打开时 Esc 优先关菜单
            if (e.key === 'Escape' && busy) {
              e.preventDefault();
              stopAssistantTask?.();
              return;
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
              <option value='coder'>GLM-5.2 · coder</option>
              <option value='architect'>GLM-5.2 · architect</option>
            </select>
          )}
          <span className='spacer' />
          {/* M192 — 图像附件按钮(仅 chat/plan 可用;agent/auto 禁用并说明原因) */}
          <button
            type='button'
            data-testid='composer-attach-btn'
            aria-label='添加图像附件'
            title={imageEnabled ? '添加图像附件' : '仅 chat/plan 支持图像附件'}
            disabled={disabled || !imageEnabled}
            onClick={() => fileRef.current?.click()}
            style={{
              background: 'none',
              border: 'none',
              padding: 4,
              cursor: disabled || !imageEnabled ? 'not-allowed' : 'pointer',
              color: 'inherit',
              opacity: disabled || !imageEnabled ? 0.35 : 0.8,
              display: 'inline-flex',
              alignItems: 'center',
            }}
          >
            <IconImagePlus size={15} />
          </button>
          {attachWarn && (
            <span className='char-warn' data-testid='composer-attach-warn'>
              {attachWarn}
            </span>
          )}
          {overCharLimit && (
            <span className='char-warn' data-testid='assistant-char-warn'>
              字符数 {text.length} 已超 12k 警告线
            </span>
          )}
          {busy ? (
            <button
              className='send-btn stop'
              type='button'
              data-testid='composer-stop-btn'
              onClick={() => stopAssistantTask?.()}
              disabled={disabled}
              aria-label='停止生成'
              title='停止当前生成(Esc)'
              style={{ background: 'var(--assistant-coral)' }}
            >
              <IconStop size={14} /> 停止
            </button>
          ) : (
            <button
              className='send-btn'
              type='button'
              data-testid='assistant-send-btn'
              onClick={submit}
              disabled={disabled || !text.trim()}
              aria-label='发送'
            >
              <IconSend size={14} /> 发送
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
