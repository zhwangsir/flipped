import { describe, it, expect } from 'vitest';
import { diffLines, terminalLines, editorCode, fileTree, mcpServers, problems, type TreeNode } from './mock';

describe('mock data — 演示数据结构完整性', () => {
  it('diffLines 至少包含 add 与 ctx 两种类型', () => {
    expect(diffLines.length).toBeGreaterThan(0);
    const types = new Set(diffLines.map((l) => l.type));
    expect(types.has('add')).toBe(true);
    expect(types.has('ctx')).toBe(true);
  });

  it('diffLines 每行都有 text 字段(可为空字符串)', () => {
    for (const line of diffLines) {
      expect(typeof line.text).toBe('string');
    }
  });

  it('diffLines 包含 FastAPI 应用代码特征', () => {
    const joined = diffLines.map((l) => l.text).join('\n');
    expect(joined).toContain('FastAPI');
    expect(joined).toContain('@app.get');
    expect(joined).toContain('@app.post');
  });

  it('terminalLines 包含 pytest 与 uvicorn 输出', () => {
    expect(terminalLines.length).toBeGreaterThan(0);
    const joined = terminalLines.join('\n');
    expect(joined).toContain('pytest');
    expect(joined).toContain('uvicorn');
    expect(joined).toContain('200 OK');
  });

  it('editorCode 是非空字符串且含 Python 代码', () => {
    expect(typeof editorCode).toBe('string');
    expect(editorCode.length).toBeGreaterThan(0);
    expect(editorCode).toContain('FastAPI');
    expect(editorCode).toContain('def list_todos');
    expect(editorCode).toContain('def create_todo');
    expect(editorCode).toContain('def delete_todo');
  });

  it('fileTree 第一个是根目录 todo-api 且 open=true', () => {
    expect(fileTree.length).toBeGreaterThan(0);
    const root = fileTree[0];
    expect(root.name).toBe('todo-api');
    expect(root.kind).toBe('folder');
    expect(root.depth).toBe(0);
    expect(root.open).toBe(true);
  });

  it('fileTree 包含 app.py 与 test_app.py 文件(带 add badge)', () => {
    const appPy = fileTree.find((n) => n.name === 'app.py');
    expect(appPy).toBeDefined();
    expect(appPy?.kind).toBe('file');
    expect(appPy?.badge).toBe('add');
    expect(appPy?.active).toBe(true);
    const testApp = fileTree.find((n) => n.name === 'test_app.py');
    expect(testApp).toBeDefined();
    expect(testApp?.badge).toBe('add');
  });

  it('fileTree TreeNode 类型守卫:depth 与 kind 一致', () => {
    for (const node of fileTree) {
      expect(['folder', 'file']).toContain(node.kind);
      expect(typeof node.depth).toBe('number');
      expect(node.depth).toBeGreaterThanOrEqual(0);
    }
  });

  it('mcpServers 至少 4 个,且每个有 name/tools/on 字段', () => {
    expect(mcpServers.length).toBeGreaterThanOrEqual(4);
    for (const s of mcpServers) {
      expect(typeof s.name).toBe('string');
      expect(typeof s.desc).toBe('string');
      expect(typeof s.tools).toBe('number');
      expect(typeof s.on).toBe('boolean');
    }
  });

  it('mcpServers 包含 filesystem 与 searxng', () => {
    expect(mcpServers.find((s) => s.name === 'filesystem')).toBeDefined();
    expect(mcpServers.find((s) => s.name === 'searxng')).toBeDefined();
  });

  it('mcpServers 中 playwright 默认关闭(on=false)', () => {
    const pw = mcpServers.find((s) => s.name === 'playwright');
    expect(pw).toBeDefined();
    expect(pw?.on).toBe(false);
  });

  it('problems 至少 1 条,且 level 为 warn/error', () => {
    expect(problems.length).toBeGreaterThanOrEqual(1);
    for (const p of problems) {
      expect(['warn', 'error']).toContain(p.level);
      expect(typeof p.file).toBe('string');
      expect(typeof p.msg).toBe('string');
    }
  });

  it('problems 第一条指向 app.py:14', () => {
    expect(problems[0].file).toBe('app.py:14');
    expect(problems[0].msg).toContain('create_todo');
  });

  it('TreeNode 类型可被显式构造', () => {
    const n: TreeNode = { name: 'x', kind: 'file', depth: 0 };
    expect(n.name).toBe('x');
  });
});
