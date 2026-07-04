import { describe, it, expect } from 'vitest';
import { createElement, Fragment } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { renderMarkdown } from './markdown';

/** 把 markdown 渲染成静态 HTML 串(便于断言)。 */
function html(src: string): string {
  return renderToStaticMarkup(createElement(Fragment, null, ...renderMarkdown(src)));
}

describe('renderMarkdown — 安全(XSS 防护)', () => {
  it('javascript: 链接被拦截(渲染成纯文本, 非 <a>)', () => {
    const out = html('点[这里](javascript:alert(1))试试');
    expect(out).not.toContain('javascript:');
    expect(out).not.toContain('<a ');
    expect(out).toContain('这里'); // 链接文字仍在
  });

  it('data: 链接被拦截', () => {
    const out = html('[x](data:text/html,<script>alert(1)</script>)');
    expect(out).not.toContain('<a ');
    expect(out).not.toContain('data:text/html');
  });

  it('原始 HTML 被转义(不作为活标签注入)', () => {
    const out = html('危险:<script>alert(document.cookie)</script> 结束');
    expect(out).not.toContain('<script>');
    expect(out).toContain('&lt;script&gt;');
  });

  it('img onerror 之类不被当活标签', () => {
    const out = html('<img src=x onerror=alert(1)>');
    expect(out).not.toContain('<img');
    expect(out).toContain('&lt;img');
  });
});

describe('renderMarkdown — 合法链接放行', () => {
  it('https 链接 → <a target=_blank rel=noreferrer>', () => {
    const out = html('见[官网](https://example.com/x)');
    expect(out).toContain('href="https://example.com/x"');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noreferrer"');
  });
  it('相对路径链接放行', () => {
    expect(html('[a](/docs/x.md)')).toContain('href="/docs/x.md"');
  });
  it('锚点链接放行', () => {
    expect(html('[a](#sec)')).toContain('href="#sec"');
  });
});

describe('renderMarkdown — 基本渲染', () => {
  it('标题', () => expect(html('# 标题')).toContain('<h1'));
  it('粗体/斜体/行内代码', () => {
    const out = html('**粗** *斜* `代码`');
    expect(out).toContain('<strong>粗</strong>');
    expect(out).toContain('<em>斜</em>');
    expect(out).toContain('md-code-inline');
  });
  it('围栏代码块内的 markdown 不被解析(保持字面)', () => {
    const out = html('```\n**不该变粗**\n```');
    expect(out).toContain('<pre');
    expect(out).toContain('**不该变粗**'); // 字面保留
    expect(out).not.toContain('<strong>不该变粗</strong>');
  });
  it('无序列表', () => {
    const out = html('- 一\n- 二');
    expect(out).toContain('<ul');
    expect((out.match(/<li>/g) || []).length).toBe(2);
  });
});
