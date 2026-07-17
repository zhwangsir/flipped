/**
 * M136-C — 最小 Node 类型垫片。
 *
 * 本仓库未安装 @types/node（约束：只允许新增 @xterm/headless 与 ws 两个依赖），
 * 而终端数据通路测试跑在 node 环境、需要 child_process/os/path/url/Buffer/ws。
 * 这里只声明测试实际用到的 API 面，不做全量 Node 类型。
 * 若日后正式引入 @types/node，删除本文件即可。
 */

declare module 'node:child_process' {
  export interface ChildProcess {
    stdout: { on(event: 'data', cb: (d: { toString(): string }) => void): void } | null;
    stderr: { on(event: 'data', cb: (d: { toString(): string }) => void): void } | null;
    exitCode: number | null;
    kill(signal?: string): boolean;
    on(event: 'exit', cb: (code: number | null) => void): void;
    once(event: 'exit', cb: (...args: unknown[]) => void): void;
  }
  export function spawn(
    cmd: string,
    args: string[],
    opts: { cwd?: string; env?: Record<string, string | undefined>; stdio?: unknown[] },
  ): ChildProcess;
}

declare module 'node:os' {
  export function tmpdir(): string;
}

declare module 'node:fs' {
  export function mkdirSync(path: string, opts?: { recursive?: boolean }): void;
}

declare module 'node:path' {
  const path: {
    join(...parts: string[]): string;
    resolve(...parts: string[]): string;
    dirname(p: string): string;
  };
  export default path;
}

declare module 'node:url' {
  export function fileURLToPath(url: string | URL): string;
}

declare module 'ws' {
  export type RawData = Buffer | ArrayBuffer | Buffer[];
  export default class WebSocket {
    constructor(url: string);
    send(data: string): void;
    close(): void;
    on(event: 'message', cb: (data: RawData) => void): this;
    once(event: 'open', cb: () => void): this;
    once(event: 'error', cb: (err: Error) => void): this;
  }
}

declare class Buffer {
  static from(data: string | ArrayBuffer | Buffer, encoding?: string): Buffer;
  static concat(list: Buffer[]): Buffer;
  static isBuffer(value: unknown): boolean;
  toString(encoding?: string): string;
  readonly length: number;
}

declare const process: {
  env: Record<string, string | undefined>;
};
