import type { ReactNode } from 'react';

/**
 * 极小 Markdown → React 渲染(不用 dangerouslySetInnerHTML，全部生成 React 元素，天然防 XSS)。
 * 仅覆盖真实文档常见语法：ATX 标题、有序/无序列表、围栏代码块、引用、分隔线、段落、
 * 行内 **粗** *斜* `代码` [链接](url)。够 Codex review 面板把 HANDOFF.md / README 渲染成文档。
 */

/** 行内标记 → ReactNode[]。安全:链接只接受 http(s)/相对路径。 */
function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  // 顺序:代码 > 链接 > 粗 > 斜。代码内不再解析。
  const re = /(`[^`]+`)|(\[[^\]]+\]\([^)]+\))|(\*\*[^*]+\*\*)|(\*[^*]+\*|_[^_]+_)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const key = keyBase + '-' + k++;
    if (m[1]) {
      out.push(<code key={key} className="md-code-inline">{m[1].slice(1, -1)}</code>);
    } else if (m[2]) {
      const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(m[2])!;
      const href = mm[2];
      const safe = /^(https?:\/\/|\/|\.{0,2}\/|#)/.test(href);
      out.push(
        safe ? (
          <a key={key} href={href} target="_blank" rel="noreferrer" className="md-link">{mm[1]}</a>
        ) : (
          <span key={key}>{mm[1]}</span>
        )
      );
    } else if (m[3]) {
      out.push(<strong key={key}>{m[3].slice(2, -2)}</strong>);
    } else if (m[4]) {
      out.push(<em key={key}>{m[4].slice(1, -1)}</em>);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** 把 markdown 源码渲染成块级 React 元素数组。 */
export function renderMarkdown(src: string): ReactNode[] {
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // 围栏代码块 ```
    const fence = /^```(\w*)\s*$/.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) body.push(lines[i++]);
      i++; // 跳过收尾 ```
      blocks.push(
        <pre key={key++} className="md-pre">
          <code>{body.join('\n')}</code>
        </pre>
      );
      continue;
    }

    // 标题 # .. ######
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      const Tag = ('h' + Math.min(level, 6)) as 'h1';
      blocks.push(
        <Tag key={key++} className={'md-h md-h' + level}>{inline(h[2], 'h' + key)}</Tag>
      );
      i++;
      continue;
    }

    // 分隔线
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      blocks.push(<hr key={key++} className="md-hr" />);
      i++;
      continue;
    }

    // 引用块 >
    if (/^>\s?/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) body.push(lines[i++].replace(/^>\s?/, ''));
      blocks.push(
        <blockquote key={key++} className="md-quote">{inline(body.join(' '), 'q' + key)}</blockquote>
      );
      continue;
    }

    // 无序列表
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*+]\s+/, ''));
      blocks.push(
        <ul key={key++} className="md-ul">
          {items.map((it, j) => <li key={j}>{inline(it, 'u' + key + '-' + j)}</li>)}
        </ul>
      );
      continue;
    }

    // 有序列表
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+\.\s+/, ''));
      blocks.push(
        <ol key={key++} className="md-ol">
          {items.map((it, j) => <li key={j}>{inline(it, 'o' + key + '-' + j)}</li>)}
        </ol>
      );
      continue;
    }

    // 空行
    if (/^\s*$/.test(line)) {
      i++;
      continue;
    }

    // 段落:聚合到下一空行/块起始
    const para: string[] = [];
    while (
      i < lines.length &&
      !/^\s*$/.test(lines[i]) &&
      !/^```/.test(lines[i]) &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^>\s?/.test(lines[i])
    ) {
      para.push(lines[i++]);
    }
    blocks.push(<p key={key++} className="md-p">{inline(para.join(' '), 'p' + key)}</p>);
  }

  return blocks;
}
