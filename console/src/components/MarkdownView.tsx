/**
 * M167.1+2 · MarkdownView:零依赖自研 GFM 子集渲染(对标 opencode 富文本体验)。
 *
 * 两阶段解析:
 * - 阶段一(块级):行 split → 围栏代码块/标题/分隔线/表格/引用/列表(栈式缩进嵌套)/段落;
 * - 阶段二(行内):单正则一趟切分 `行内码` ![图](u) [链](u) **粗** *斜*,代码段内不再解析。
 *
 * 硬约束:
 * - 零新依赖,不引 react-markdown/unified;
 * - 防 XSS:不 dangerouslySetInnerHTML,全靠 React 文本转义,HTML 标签原样显示为文本;
 *   链接协议白名单(http/https/相对路径/#锚点),javascript: 等降级为纯文本;
 * - 流式安全:未闭合围栏按已闭合容错;未闭合行内标记按原文渲染;任意 unicode 输入不 crash;
 * - 远程图片不加载,渲染为链接文本;
 * - key 用稳定索引(b{块序号}-{行内序号}),无 React key 警告。
 */
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

type ListNode = { text: string; ordered: boolean; children: ListNode[] };

type Block =
  | { kind: 'code'; lang: string; code: string }
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'hr' }
  | { kind: 'quote'; lines: string[] }
  | { kind: 'list'; nodes: ListNode[] }
  | { kind: 'table'; header: string[]; rows: string[][] }
  | { kind: 'para'; lines: string[] };

/* ---------------- 阶段一:块级解析 ---------------- */

const FENCE_RE = /^```\s*([^\s`]*)\s*$/;
const FENCE_CLOSE_RE = /^```\s*$/;
const HEADING_RE = /^(#{1,4})\s+(.*)$/;
const HR_RE = /^\s*(\*{3,}|-{3,}|_{3,})\s*$/;
const QUOTE_RE = /^>\s?/;
const LIST_RE = /^(\s*)([-*+]|\d+\.)\s+(.*)$/;
const BLANK_RE = /^\s*$/;

/** 表格行切分:去首尾 | 后按 | 分列,单元格 trim。 */
function splitRow(line: string): string[] {
  let t = line.trim();
  if (t.startsWith('|')) t = t.slice(1);
  if (t.endsWith('|')) t = t.slice(0, -1);
  return t.split('|').map((c) => c.trim());
}

/** GFM 表头分隔行:每列只允许 :--- 形态(对齐冒号收下但不对齐)。 */
function isTableDelim(line: string): boolean {
  if (!line.includes('-')) return false;
  const cells = splitRow(line);
  return cells.length > 0 && cells.every((c) => /^:?-+:?$/.test(c));
}

/** 表格起点:当前行含 | 且下一行是分隔行,且两行列数一致(GFM 要求)。 */
function isTableStart(lines: string[], i: number): boolean {
  if (i + 1 >= lines.length) return false;
  if (!lines[i].includes('|')) return false;
  if (!isTableDelim(lines[i + 1])) return false;
  return splitRow(lines[i]).length === splitRow(lines[i + 1]).length;
}

/** 行是否开启一个新块(用于段落聚合的停止条件;围栏用宽松前缀防死循环)。 */
function isBlockStart(lines: string[], i: number): boolean {
  const l = lines[i];
  return (
    l.startsWith('```') ||
    HEADING_RE.test(l) ||
    HR_RE.test(l) ||
    QUOTE_RE.test(l) ||
    LIST_RE.test(l) ||
    isTableStart(lines, i)
  );
}

function parseBlocks(lines: string[]): Block[] {
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (BLANK_RE.test(line)) {
      i++;
      continue;
    }

    // 围栏代码块(未闭合时收到 EOF 为止,按已闭合容错)
    const fence = FENCE_RE.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !FENCE_CLOSE_RE.test(lines[i])) body.push(lines[i++]);
      if (i < lines.length) i++; // 跳过收尾围栏
      blocks.push({ kind: 'code', lang: fence[1], code: body.join('\n') });
      continue;
    }

    // ATX 标题 # ~ ####
    const h = HEADING_RE.exec(line);
    if (h) {
      blocks.push({ kind: 'heading', level: h[1].length, text: h[2] });
      i++;
      continue;
    }

    // 分隔线 --- / ***
    if (HR_RE.test(line)) {
      blocks.push({ kind: 'hr' });
      i++;
      continue;
    }

    // GFM 表格
    if (isTableStart(lines, i)) {
      const header = splitRow(line);
      const rows: string[][] = [];
      i += 2; // 跳过表头行 + 分隔行
      while (i < lines.length && !BLANK_RE.test(lines[i]) && lines[i].includes('|')) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      blocks.push({ kind: 'table', header, rows });
      continue;
    }

    // 引用块
    if (QUOTE_RE.test(line)) {
      const qlines: string[] = [];
      while (i < lines.length && QUOTE_RE.test(lines[i])) {
        qlines.push(lines[i].replace(QUOTE_RE, ''));
        i++;
      }
      blocks.push({ kind: 'quote', lines: qlines });
      continue;
    }

    // 列表(栈式:缩进大于栈顶 → 成为其子节点,天然支持一层及更深嵌套)
    if (LIST_RE.test(line)) {
      const roots: ListNode[] = [];
      const stack: { indent: number; node: ListNode }[] = [];
      while (i < lines.length) {
        const m = LIST_RE.exec(lines[i]);
        if (!m) break;
        const indent = m[1].replace(/\t/g, '    ').length;
        const node: ListNode = { text: m[3], ordered: /^\d/.test(m[2]), children: [] };
        while (stack.length > 0 && stack[stack.length - 1].indent >= indent) stack.pop();
        if (stack.length === 0) roots.push(node);
        else stack[stack.length - 1].node.children.push(node);
        stack.push({ indent, node });
        i++;
      }
      blocks.push({ kind: 'list', nodes: roots });
      continue;
    }

    // 段落:首行无条件消费(保证前进、防死循环),后续行遇块起始/空行即停
    const para: string[] = [];
    while (i < lines.length && !BLANK_RE.test(lines[i])) {
      if (para.length > 0 && isBlockStart(lines, i)) break;
      para.push(lines[i++]);
    }
    blocks.push({ kind: 'para', lines: para });
  }
  return blocks;
}

/* ---------------- 阶段二:行内解析 ---------------- */

// 顺序:行内码 > 图片 > 链接 > 粗 > 斜。行内码先匹配,其内容不再解析。
const INLINE_RE =
  /(`[^`\n]+`)|(!\[[^\]]*\]\([^)\s]+\))|(\[[^\]]+\]\([^)\s]+\))|(\*\*[^*]+\*\*)|(\*[^*\n]+\*)/g;

/** 链接协议白名单:http(s)/站内路径/相对路径/#锚点;javascript: 等一律降级。 */
function isSafeHref(href: string): boolean {
  return /^(https?:\/\/|\/|\.{1,2}\/|#)/i.test(href);
}

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  INLINE_RE.lastIndex = 0;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = INLINE_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const key = keyBase + '-' + k++;
    if (m[1]) {
      out.push(
        <code key={key} className='md-code-inline'>
          {m[1].slice(1, -1)}
        </code>
      );
    } else if (m[2]) {
      // 图片:不加载远程资源,渲染为链接文本
      const mm = /!\[([^\]]*)\]\(([^)\s]+)\)/.exec(m[2])!;
      const alt = mm[1] || mm[2];
      out.push(
        isSafeHref(mm[2]) ? (
          <a key={key} className='md-link' href={mm[2]} target='_blank' rel='noreferrer'>
            {alt}
          </a>
        ) : (
          <span key={key}>{alt}</span>
        )
      );
    } else if (m[3]) {
      const mm = /\[([^\]]+)\]\(([^)\s]+)\)/.exec(m[3])!;
      out.push(
        isSafeHref(mm[2]) ? (
          <a key={key} className='md-link' href={mm[2]} target='_blank' rel='noreferrer'>
            {mm[1]}
          </a>
        ) : (
          <span key={key}>{mm[1]}</span>
        )
      );
    } else if (m[4]) {
      out.push(<strong key={key}>{m[4].slice(2, -2)}</strong>);
    } else if (m[5]) {
      out.push(<em key={key}>{m[5].slice(1, -1)}</em>);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/* ---------------- 渲染 ---------------- */

/** 多行文本(段落/引用):行间补 <br/>,保留源换行。 */
function InlineLines({ lines, keyBase }: { lines: string[]; keyBase: string }) {
  return (
    <>
      {lines.map((l, idx) => (
        <Fragment key={keyBase + '-' + idx}>
          {idx > 0 && <br />}
          {inline(l, keyBase + '-' + idx)}
        </Fragment>
      ))}
    </>
  );
}

/** 列表递归渲染:同级列表类型取首个节点的标记(ul/ol)。 */
function renderList(nodes: ListNode[], keyBase: string): ReactNode {
  if (nodes.length === 0) return null;
  const ordered = nodes[0].ordered;
  const Tag = ordered ? 'ol' : 'ul';
  return (
    <Tag className={ordered ? 'md-ol' : 'md-ul'}>
      {nodes.map((n, idx) => (
        <li key={keyBase + '-' + idx}>
          {inline(n.text, keyBase + '-' + idx)}
          {n.children.length > 0 && renderList(n.children, keyBase + '-' + idx + 'c')}
        </li>
      ))}
    </Tag>
  );
}

/** 围栏代码块:头部右侧语言标签 + 复制按钮(1.5s 反馈态)。 */
function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );
  const onCopy = () => {
    try {
      void navigator.clipboard?.writeText?.(code)?.catch(() => {});
    } catch {
      // 非安全上下文剪贴板不可用时静默降级,仅展示反馈态
    }
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className='md-code'>
      <div className='md-code-head'>
        {lang && <span className='md-code-lang'>{lang}</span>}
        <button type='button' className='md-code-copy' onClick={onCopy}>
          {copied ? '✓ 已复制' : 'Copy'}
        </button>
      </div>
      <pre className='md-pre'>
        <code>{code}</code>
      </pre>
    </div>
  );
}

function renderBlock(block: Block, index: number): ReactNode {
  const key = 'b' + index;
  switch (block.kind) {
    case 'code':
      return <CodeBlock key={key} lang={block.lang} code={block.code} />;
    case 'heading': {
      const Tag = `h${block.level}` as 'h1' | 'h2' | 'h3' | 'h4';
      return (
        <Tag key={key} className={`md-h md-h${block.level}`}>
          {inline(block.text, key)}
        </Tag>
      );
    }
    case 'hr':
      return <hr key={key} className='md-hr' />;
    case 'quote':
      return (
        <blockquote key={key} className='md-quote'>
          <InlineLines lines={block.lines} keyBase={key} />
        </blockquote>
      );
    case 'list':
      return <Fragment key={key}>{renderList(block.nodes, key)}</Fragment>;
    case 'table':
      return (
        <div key={key} className='md-table-wrap'>
          <table className='md-table'>
            <thead>
              <tr>
                {block.header.map((c, ci) => (
                  <th key={ci}>{inline(c, key + '-h' + ci)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((c, ci) => (
                    <td key={ci}>{inline(c, key + '-' + ri + '-' + ci)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case 'para':
      return (
        <p key={key} className='md-p'>
          <InlineLines lines={block.lines} keyBase={key} />
        </p>
      );
  }
}

export function MarkdownView({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const blocks = useMemo(() => parseBlocks(text.replace(/\r\n/g, '\n').split('\n')), [text]);
  return (
    <div className={streaming ? 'md-view streaming' : 'md-view'}>
      {blocks.map((b, i) => renderBlock(b, i))}
    </div>
  );
}
