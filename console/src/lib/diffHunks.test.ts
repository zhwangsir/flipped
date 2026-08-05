import { describe, it, expect } from 'vitest';
import { splitDiffHunks } from './diffHunks';
import type { GitDiffLine } from '../types';

// M193.2 — 逐 hunk 接受/拒绝:分组 + prelude + 内容指纹 key 稳定性

const twoHunkLines: GitDiffLine[] = [
  { type: 'hunk', text: '@@ -1,3 +1,3 @@' },
  { type: 'ctx', text: 'line a' },
  { type: 'del', text: 'old 1' },
  { type: 'add', text: 'new 1' },
  { type: 'hunk', text: '@@ -10,3 +10,3 @@' },
  { type: 'ctx', text: 'line b' },
  { type: 'del', text: 'old 2' },
  { type: 'add', text: 'new 2' },
];

describe('splitDiffHunks — 分组', () => {
  it('两 hunk 正确分组(header/lines 归属)', () => {
    const { prelude, hunks } = splitDiffHunks('src/a.ts', twoHunkLines);
    expect(prelude).toEqual([]);
    expect(hunks).toHaveLength(2);
    expect(hunks[0].header).toBe('@@ -1,3 +1,3 @@');
    expect(hunks[0].lines.map((l) => l.text)).toEqual(['line a', 'old 1', 'new 1']);
    expect(hunks[1].header).toBe('@@ -10,3 +10,3 @@');
    expect(hunks[1].lines.map((l) => l.text)).toEqual(['line b', 'old 2', 'new 2']);
  });

  it('首个 hunk 前的行(防御)归 prelude', () => {
    const lines: GitDiffLine[] = [
      { type: 'ctx', text: 'stray' },
      { type: 'hunk', text: '@@ -1 +1 @@' },
      { type: 'add', text: 'x' },
    ];
    const { prelude, hunks } = splitDiffHunks('a.ts', lines);
    expect(prelude).toEqual([{ type: 'ctx', text: 'stray' }]);
    expect(hunks).toHaveLength(1);
    expect(hunks[0].lines).toEqual([{ type: 'add', text: 'x' }]);
  });

  it('空 lines → 空 prelude + 空 hunks', () => {
    expect(splitDiffHunks('a.ts', [])).toEqual({ prelude: [], hunks: [] });
  });

  it('无 hunk 行 → 全部进 prelude', () => {
    const lines: GitDiffLine[] = [
      { type: 'add', text: 'x' },
      { type: 'del', text: 'y' },
    ];
    const { prelude, hunks } = splitDiffHunks('a.ts', lines);
    expect(prelude).toEqual(lines);
    expect(hunks).toEqual([]);
  });
});

describe('splitDiffHunks — key 内容指纹', () => {
  it('header 行号变、add/del 内容不变 → key 相同', () => {
    const shifted: GitDiffLine[] = [
      { type: 'hunk', text: '@@ -99,3 +99,3 @@' },
      { type: 'ctx', text: 'line a' },
      { type: 'del', text: 'old 1' },
      { type: 'add', text: 'new 1' },
    ];
    const a = splitDiffHunks('src/a.ts', twoHunkLines).hunks[0];
    const b = splitDiffHunks('src/a.ts', shifted).hunks[0];
    expect(a.key).toBe(b.key);
  });

  it('add/del 行内容变 → key 不同', () => {
    const changed: GitDiffLine[] = [
      { type: 'hunk', text: '@@ -1,3 +1,3 @@' },
      { type: 'ctx', text: 'line a' },
      { type: 'del', text: 'old 1' },
      { type: 'add', text: 'new 1 modified' },
    ];
    const a = splitDiffHunks('src/a.ts', twoHunkLines).hunks[0];
    const b = splitDiffHunks('src/a.ts', changed).hunks[0];
    expect(a.key).not.toBe(b.key);
  });

  it('不同 path 相同内容 → key 不同', () => {
    const a = splitDiffHunks('src/a.ts', twoHunkLines).hunks[0];
    const b = splitDiffHunks('src/b.ts', twoHunkLines).hunks[0];
    expect(a.key).not.toBe(b.key);
  });

  it('ctx 行不参与指纹(行号漂移伴随 ctx 变化时 key 仍稳定)', () => {
    const ctxShifted: GitDiffLine[] = [
      { type: 'hunk', text: '@@ -50,3 +50,3 @@' },
      { type: 'ctx', text: 'different ctx' },
      { type: 'del', text: 'old 1' },
      { type: 'add', text: 'new 1' },
    ];
    const a = splitDiffHunks('src/a.ts', twoHunkLines).hunks[0];
    const b = splitDiffHunks('src/a.ts', ctxShifted).hunks[0];
    expect(a.key).toBe(b.key);
  });

  it('key 为非空字符串', () => {
    const { hunks } = splitDiffHunks('src/a.ts', twoHunkLines);
    for (const h of hunks) {
      expect(typeof h.key).toBe('string');
      expect(h.key.length).toBeGreaterThan(0);
    }
  });
});
