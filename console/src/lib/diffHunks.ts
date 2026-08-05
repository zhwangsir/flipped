import type { GitDiffLine } from '../types';

/** M193.2 — 逐 hunk 接受/拒绝:把扁平 diff 行按 type==='hunk' 分组,并给每个 hunk 算内容指纹 key。 */
export interface DiffHunk {
  header: string;
  lines: GitDiffLine[];
  key: string;
}
export interface DiffBlocks {
  prelude: GitDiffLine[];
  hunks: DiffHunk[];
}

/** djb2 哈希 → base36 字符串(内容指纹,非加密用途)。 */
function djb2(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(36);
}

/**
 * 按 hunk 行分组。首个 hunk 前的行(理论不出现,防御)归 prelude。
 * key = djb2(path + '\n' + add/del 行文本 join('\n'))——内容指纹不含 header 行号:
 * 拒绝其他 hunk 后行号漂移但内容不变 → key 稳定;内容变了 → 指纹自然失效。
 */
export function splitDiffHunks(path: string, lines: GitDiffLine[]): DiffBlocks {
  const prelude: GitDiffLine[] = [];
  const hunks: DiffHunk[] = [];
  let current: DiffHunk | null = null;
  for (const l of lines) {
    if (l.type === 'hunk') {
      current = { header: l.text, lines: [], key: '' };
      hunks.push(current);
    } else if (current) {
      current.lines.push(l);
    } else {
      prelude.push(l);
    }
  }
  for (const h of hunks) {
    const fingerprint = h.lines
      .filter((l) => l.type === 'add' || l.type === 'del')
      .map((l) => l.text)
      .join('\n');
    h.key = djb2(path + '\n' + fingerprint);
  }
  return { prelude, hunks };
}
