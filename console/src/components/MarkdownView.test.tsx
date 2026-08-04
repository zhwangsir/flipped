import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { MarkdownView } from './MarkdownView';

// M167.1 — MarkdownView 单测:零依赖 GFM 子集渲染。
// 覆盖:标题/粗斜体/行内码/链接/围栏代码块(含未闭合容错)/列表(含嵌套)/引用/表格/
// 分隔线/多段落/XSS 文本化/图片不加载/复制按钮反馈态/unicode 与未闭合行内标记容错。
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('MarkdownView — 块级元素', () => {
  it('渲染 # ~ #### 四级标题', () => {
    render(<MarkdownView text={'# 标题一\n## 标题二\n### 标题三\n#### 标题四'} />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('标题一');
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('标题二');
    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('标题三');
    expect(screen.getByRole('heading', { level: 4 }).textContent).toBe('标题四');
  });

  it('围栏代码块:语言标签 + pre>code 内容', () => {
    const { container } = render(<MarkdownView text={'```ts\nconst a = 1;\n```'} />);
    expect(container.querySelector('.md-code-lang')?.textContent).toBe('ts');
    const code = container.querySelector('pre.md-pre code');
    expect(code?.textContent).toBe('const a = 1;');
  });

  it('未闭合代码块(流式中途)按已闭合容错渲染', () => {
    const { container } = render(<MarkdownView text={'```js\nconst b = 2;'} streaming />);
    const code = container.querySelector('pre.md-pre code');
    expect(code?.textContent).toBe('const b = 2;');
    expect(container.querySelector('.md-code-lang')?.textContent).toBe('js');
  });

  it('无序列表:ul 包裹两个 li', () => {
    const { container } = render(<MarkdownView text={'- 苹果\n- 香蕉'} />);
    const ul = container.querySelector('ul.md-ul');
    expect(ul).not.toBeNull();
    const items = ul!.querySelectorAll(':scope > li');
    expect(items.length).toBe(2);
    expect(items[0].textContent).toBe('苹果');
    expect(items[1].textContent).toBe('香蕉');
  });

  it('有序列表:ol 包裹 li', () => {
    const { container } = render(<MarkdownView text={'1. 第一步\n2. 第二步'} />);
    const ol = container.querySelector('ol.md-ol');
    expect(ol).not.toBeNull();
    expect(ol!.querySelectorAll(':scope > li').length).toBe(2);
  });

  it('一层缩进嵌套列表:子 ul 挂在外层 li 内', () => {
    const { container } = render(<MarkdownView text={'- 外层A\n  - 内层B\n- 外层C'} />);
    const outer = container.querySelector('ul.md-ul');
    expect(outer).not.toBeNull();
    expect(outer!.querySelectorAll(':scope > li').length).toBe(2);
    const nested = outer!.querySelector('li > ul');
    expect(nested).not.toBeNull();
    expect(nested!.textContent).toContain('内层B');
  });

  it('引用块:> 渲染为 blockquote', () => {
    const { container } = render(<MarkdownView text={'> 这是一段引用'} />);
    const quote = container.querySelector('blockquote.md-quote');
    expect(quote?.textContent).toContain('这是一段引用');
  });

  it('GFM 表格:表头 th + 数据行 td', () => {
    const { container } = render(
      <MarkdownView text={'| 名称 | 类型 |\n| --- | --- |\n| foo | string |\n| bar | number |'} />
    );
    const table = container.querySelector('table.md-table');
    expect(table).not.toBeNull();
    const ths = table!.querySelectorAll('th');
    expect(ths.length).toBe(2);
    expect(ths[0].textContent).toBe('名称');
    expect(ths[1].textContent).toBe('类型');
    const tds = table!.querySelectorAll('td');
    expect(tds.length).toBe(4);
    expect(tds[0].textContent).toBe('foo');
    expect(tds[3].textContent).toBe('number');
  });

  it('分隔线:--- 与 *** 渲染为 hr', () => {
    const { container } = render(<MarkdownView text={'上段\n\n---\n\n下段\n\n***'} />);
    expect(container.querySelectorAll('hr.md-hr').length).toBe(2);
  });

  it('多段落:空行切分为两个 p.md-p', () => {
    const { container } = render(<MarkdownView text={'第一段\n\n第二段'} />);
    const ps = container.querySelectorAll('p.md-p');
    expect(ps.length).toBe(2);
    expect(ps[0].textContent).toBe('第一段');
    expect(ps[1].textContent).toBe('第二段');
  });
});

describe('MarkdownView — 行内元素', () => {
  it('**粗体** → strong,*斜体* → em', () => {
    const { container } = render(<MarkdownView text={'这是 **重点** 与 *斜体* 内容'} />);
    expect(container.querySelector('strong')?.textContent).toBe('重点');
    expect(container.querySelector('em')?.textContent).toBe('斜体');
  });

  it('`行内码` → code.md-code-inline', () => {
    const { container } = render(<MarkdownView text={'运行 `npm test` 即可'} />);
    const code = container.querySelector('code.md-code-inline');
    expect(code?.textContent).toBe('npm test');
  });

  it('[text](url) → a, target=_blank 且 rel 含 noreferrer', () => {
    const { container } = render(
      <MarkdownView text={'详见 [官方文档](https://example.com/docs) 章节'} />
    );
    const a = container.querySelector('a.md-link');
    expect(a).not.toBeNull();
    expect(a!.getAttribute('href')).toBe('https://example.com/docs');
    expect(a!.getAttribute('target')).toBe('_blank');
    expect(a!.getAttribute('rel')).toContain('noreferrer');
    expect(a!.textContent).toBe('官方文档');
  });

  it('javascript: 链接不渲染为 a(协议白名单)', () => {
    const { container } = render(<MarkdownView text={'[点我](javascript:alert(1))'} />);
    expect(container.querySelector('a')).toBeNull();
    expect(container.textContent).toContain('点我');
  });

  it('列表行首 * 不被误判为斜体(列表符号与斜体区分)', () => {
    const { container } = render(<MarkdownView text={'* 列表项\n* 第二项'} />);
    expect(container.querySelector('ul.md-ul')).not.toBeNull();
    expect(container.querySelector('em')).toBeNull();
  });
});

describe('MarkdownView — 安全与容错', () => {
  it('XSS:<script>alert(1)</script> 渲染为可见文本节点而非脚本', () => {
    const { container } = render(<MarkdownView text={'<script>alert(1)</script>'} />);
    expect(container.textContent).toContain('<script>alert(1)</script>');
    expect(container.querySelector('script')).toBeNull();
  });

  it('HTML 标签原样显示为文本', () => {
    const { container } = render(<MarkdownView text={'<div class="x">hello</div>'} />);
    expect(container.textContent).toContain('<div class="x">hello</div>');
    // 除 MarkdownView 自身结构外不产生 div.x
    expect(container.querySelector('div.x')).toBeNull();
  });

  it('图片语法不加载:无 img 元素,渲染为链接文本', () => {
    const { container } = render(
      <MarkdownView text={'![架构图](https://example.com/a.png)'} />
    );
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('架构图');
  });

  it('unicode 前缀 + 未闭合行内标记不 crash,按原文渲染', () => {
    const { container } = render(<MarkdownView text={'😀 前缀 **加粗未完成 与 `代码未闭合'} />);
    expect(container.textContent).toContain('😀 前缀');
    expect(container.textContent).toContain('**加粗未完成');
    expect(container.querySelector('strong')).toBeNull();
  });
});

describe('MarkdownView — 复制按钮', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('点击 Copy 调 clipboard.writeText(代码内容),1.5s 内显示"已复制"后恢复', () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    render(<MarkdownView text={'```sh\nnpm run dev\n```'} />);
    const btn = screen.getByRole('button', { name: /copy/i });
    fireEvent.click(btn);
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0][0]).toBe('npm run dev');
    // 反馈态:已复制
    expect(btn.textContent).toContain('已复制');
    // 1.5s 后恢复
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(btn.textContent).not.toContain('已复制');
  });
});
