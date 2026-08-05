import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import { Composer } from './Composer';

// M167.4 — Composer 内部直接消费 store 的排队/停止能力(assistantQueue/
// enqueueAssistantMessage/removeAssistantQueued/stopAssistantTask),测试环境 mock useApp
vi.mock('../store', () => ({ useApp: vi.fn() }));
// M175 — @ 文件引用补全拉取项目文件树,测试环境 mock api
vi.mock('../api', () => ({ fetchProjectFiles: vi.fn() }));
import { useApp } from '../store';
import { fetchProjectFiles } from '../api';

const mockedUseApp = vi.mocked(useApp);
const mockedFetchFiles = vi.mocked(fetchProjectFiles);

const baseStore = {
  assistantQueue: [] as string[],
  enqueueAssistantMessage: vi.fn(),
  removeAssistantQueued: vi.fn(),
  stopAssistantTask: vi.fn(async () => {}),
};

beforeEach(() => {
  mockedUseApp.mockReturnValue({ ...baseStore } as never);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('Composer — 输入守卫与 slash 补全', () => {
  it('空输入不发(发送按钮禁用,点击无效果)', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const btn = screen.getByTestId('assistant-send-btn') as HTMLButtonElement;
    // 空输入时按钮禁用
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    expect(onSend).not.toHaveBeenCalled();
  });

  // M167.4 行为变更:busy 时输入框不再禁用(可排队),发送键位换成停止按钮
  it('busy=true 时输入框保持可用,发送键位渲染停止按钮(M167.4)', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} busy={true} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    expect(ta.disabled).toBe(false);
    expect(screen.getByTestId('composer-stop-btn')).toBeTruthy();
    expect(screen.queryByTestId('assistant-send-btn')).toBeNull();
  });

  it('disabled=true 时输入框与发送键均禁用(不受 M167.4 影响)', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} disabled={true} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    const btn = screen.getByTestId('assistant-send-btn') as HTMLButtonElement;
    expect(ta.disabled).toBe(true);
    expect(btn.disabled).toBe(true);
  });

  it('输入 / 唤起 slash 补全菜单,显示 7 项命令', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/' } });
    const menu = screen.getByTestId('slash-menu');
    expect(menu).toBeTruthy();
    // 7 项命令（M168 新增 /undo,M176 新增 /goal）
    const items = menu.querySelectorAll('.slash-item');
    expect(items.length).toBe(7);
    // 命令文本检查
    const cmds = Array.from(items).map((i) => i.querySelector('.slash-cmd')?.textContent);
    expect(cmds).toEqual(['/clear', '/compact', '/mode', '/help', '/files', '/undo', '/goal']);
  });
});

// M167.4 — busy 交互对标 opencode:running 中 Enter 入队 / Esc 或停止键中断
describe('Composer — M167.4 busy 排队与停止', () => {
  it('busy 时 Enter 入队而不发送(onSend 未调),输入框清空', () => {
    const onSend = vi.fn();
    const enqueueAssistantMessage = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseStore, enqueueAssistantMessage } as never);
    render(<Composer onSend={onSend} busy={true} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '接着做第三步' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(enqueueAssistantMessage).toHaveBeenCalledWith('接着做第三步');
    expect(onSend).not.toHaveBeenCalled();
    expect(ta.value).toBe('');
  });

  it('busy 时空输入 Enter 不入队', () => {
    const enqueueAssistantMessage = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseStore, enqueueAssistantMessage } as never);
    render(<Composer onSend={vi.fn()} busy={true} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(enqueueAssistantMessage).not.toHaveBeenCalled();
  });

  it('busy 时点击停止按钮 → stopAssistantTask', () => {
    const stopAssistantTask = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseStore, stopAssistantTask } as never);
    render(<Composer onSend={vi.fn()} busy={true} />);
    fireEvent.click(screen.getByTestId('composer-stop-btn'));
    expect(stopAssistantTask).toHaveBeenCalledTimes(1);
  });

  it('busy 时 Esc → stopAssistantTask;非 busy 时 Esc 不停止', () => {
    const stopAssistantTask = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseStore, stopAssistantTask } as never);
    const { unmount } = render(<Composer onSend={vi.fn()} busy={true} />);
    const ta = screen.getByTestId('assistant-composer-input');
    fireEvent.keyDown(ta, { key: 'Escape' });
    expect(stopAssistantTask).toHaveBeenCalledTimes(1);
    unmount();
    render(<Composer onSend={vi.fn()} busy={false} />);
    const ta2 = screen.getByTestId('assistant-composer-input');
    fireEvent.keyDown(ta2, { key: 'Escape' });
    expect(stopAssistantTask).toHaveBeenCalledTimes(1); // 不新增调用
  });

  it('非 busy Enter 正常发送(回归)', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '正常消息' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    // M192 — onSend 签名升级 (text, images):无附件时 images 为空数组
    expect(onSend).toHaveBeenCalledWith('正常消息', []);
    expect(ta.value).toBe('');
  });

  it('排队 chips 渲染(序号 + 文本截断),× 按钮按 index 回调移除', () => {
    const removeAssistantQueued = vi.fn();
    const long = '这是一条特别长的排队消息'.repeat(5); // 65 字 > 40 截断线
    mockedUseApp.mockReturnValue({
      ...baseStore,
      assistantQueue: [long, '短消息'],
      removeAssistantQueued,
    } as never);
    render(<Composer onSend={vi.fn()} busy={true} />);
    expect(screen.getByTestId('composer-queue')).toBeTruthy();
    const chip0 = screen.getByTestId('queue-chip-0');
    expect(chip0.textContent).toContain('1. ');
    expect(chip0.textContent).toContain('…'); // 超 40 字截断
    expect(chip0.textContent!.length).toBeLessThan(long.length);
    const chip1 = screen.getByTestId('queue-chip-1');
    expect(chip1.textContent).toContain('2. 短消息');
    fireEvent.click(screen.getByTestId('queue-remove-1'));
    expect(removeAssistantQueued).toHaveBeenCalledWith(1);
  });

  it('无排队消息 → 不渲染 composer-queue', () => {
    render(<Composer onSend={vi.fn()} />);
    expect(screen.queryByTestId('composer-queue')).toBeNull();
  });
});

// M175 — @ 文件引用补全:输入 @ 触发 fetchProjectFiles,拍平树过滤排序,pick 替换 token
describe('Composer — M175 @ 文件引用补全', () => {
  const fileTree = {
    root: '/proj',
    tree: [
      {
        name: 'src',
        path: 'src',
        type: 'dir' as const,
        children: [
          { name: 'hello.py', path: 'src/hello.py', type: 'file' as const },
          { name: 'helper.py', path: 'src/helper.py', type: 'file' as const },
        ],
      },
      { name: 'doc.md', path: 'doc.md', type: 'file' as const },
      {
        name: 'docs',
        path: 'docs',
        type: 'dir' as const,
        children: [{ name: 'my file.md', path: 'docs/my file.md', type: 'file' as const }],
      },
    ],
  };

  beforeEach(() => {
    mockedFetchFiles.mockResolvedValue(fileTree);
  });

  it('输入 "看下 @he" → at-menu 出现且含匹配文件项', async () => {
    render(<Composer onSend={vi.fn()} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '看下 @he' } });
    const menu = await screen.findByTestId('at-menu');
    expect(mockedFetchFiles).toHaveBeenCalledTimes(1);
    const items = menu.querySelectorAll('.at-item');
    expect(items.length).toBe(2);
    const paths = Array.from(items).map((i) => i.querySelector('.at-path')?.textContent);
    expect(paths).toContain('src/hello.py');
    expect(paths).toContain('src/helper.py');
  });

  it('过滤排序:name startsWith 的排在 path startsWith 之前', async () => {
    render(<Composer onSend={vi.fn()} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '@doc' } });
    const menu = await screen.findByTestId('at-menu');
    const items = Array.from(menu.querySelectorAll('.at-item'));
    // doc.md(name 以 doc 开头)排最前;docs/my file.md(仅 path 以 doc 开头)其次
    expect(items[0].querySelector('.at-path')?.textContent).toBe('doc.md');
    expect(items[1].querySelector('.at-path')?.textContent).toBe('docs/my file.md');
  });

  it('Enter pick 首项 → textarea 变为 "看下 @src/hello.py " 且菜单关闭', async () => {
    render(<Composer onSend={vi.fn()} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '看下 @he' } });
    await screen.findByTestId('at-menu');
    fireEvent.keyDown(ta, { key: 'Enter' });
    expect(ta.value).toBe('看下 @src/hello.py ');
    expect(screen.queryByTestId('at-menu')).toBeNull();
  });

  it('点击 pick 含空格路径 → 文本含 @"docs/my file.md" ', async () => {
    render(<Composer onSend={vi.fn()} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '看下 @my' } });
    const menu = await screen.findByTestId('at-menu');
    const item = Array.from(menu.querySelectorAll('.at-item')).find(
      (i) => i.querySelector('.at-path')?.textContent === 'docs/my file.md'
    );
    expect(item).toBeTruthy();
    fireEvent.click(item!);
    expect(ta.value).toContain('@"docs/my file.md" ');
    expect(screen.queryByTestId('at-menu')).toBeNull();
  });

  it('Escape 关闭菜单', async () => {
    render(<Composer onSend={vi.fn()} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '@he' } });
    await screen.findByTestId('at-menu');
    fireEvent.keyDown(ta, { key: 'Escape' });
    expect(screen.queryByTestId('at-menu')).toBeNull();
  });

  it('fetchProjectFiles reject → 不炸、菜单不出现(cache=[])', async () => {
    mockedFetchFiles.mockRejectedValueOnce(new Error('boom'));
    render(<Composer onSend={vi.fn()} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '@he' } });
    await waitFor(() => expect(mockedFetchFiles).toHaveBeenCalledTimes(1));
    // 等 rejection 消化(cache 置空,不再重试)
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByTestId('at-menu')).toBeNull();
  });
});

// M176 — /goal 目标驱动自循环:slash 菜单含 /goal;pick 只填充不执行;submit 带参走 onGoal;空参退化
describe('Composer — M176 /goal 目标驱动自循环', () => {
  it('输入 /go → slash 菜单过滤出 /goal 项(带描述)', () => {
    render(<Composer onSend={vi.fn()} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/go' } });
    const menu = screen.getByTestId('slash-menu');
    const items = menu.querySelectorAll('.slash-item');
    expect(items.length).toBe(1);
    expect(items[0].querySelector('.slash-cmd')?.textContent).toBe('/goal');
    expect(items[0].querySelector('.slash-desc')?.textContent).toContain('目标驱动自循环');
  });

  it('pick /goal → 只填充 "/goal " 到输入框,不执行(onGoal/onSend 均不调),菜单关闭', () => {
    const onSend = vi.fn();
    const onGoal = vi.fn();
    render(<Composer onSend={onSend} onGoal={onGoal} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/go' } });
    screen.getByTestId('slash-menu');
    // Enter 选中菜单首项(/goal)
    fireEvent.keyDown(ta, { key: 'Enter' });
    expect(ta.value).toBe('/goal ');
    expect(onGoal).not.toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.queryByTestId('slash-menu')).toBeNull();
  });

  it('submit "/goal <目标>" → onGoal(目标文本),不走 onSend,输入框清空', () => {
    const onSend = vi.fn();
    const onGoal = vi.fn();
    render(<Composer onSend={onSend} onGoal={onGoal} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/goal 修复所有 TS 错误并让测试全过' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(onGoal).toHaveBeenCalledWith('修复所有 TS 错误并让测试全过');
    expect(onSend).not.toHaveBeenCalled();
    expect(ta.value).toBe('');
  });

  it('空参数退化:"/goal"(无目标)点发送 → 普通发送流程(onSend),不调 onGoal', () => {
    const onSend = vi.fn();
    const onGoal = vi.fn();
    render(<Composer onSend={onSend} onGoal={onGoal} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/goal' } });
    // 菜单打开时 Enter 会走 pick,此处直接点发送按钮走 submit 验证退化路径
    fireEvent.click(screen.getByTestId('assistant-send-btn'));
    expect(onGoal).not.toHaveBeenCalled();
    expect(onSend).toHaveBeenCalledWith('/goal', []);
  });

  it('无 onGoal 时 "/goal x" 退化为普通发送(向后兼容)', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/goal 做点事' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(onSend).toHaveBeenCalledWith('/goal 做点事', []);
  });
});

// M192 — 图像附件:ImagePlus 按钮/隐藏 file input/粘贴捕获 → chips;onSend 携带 PendingImage[];
// >4 张或单张 >2MB 拒绝并提示;agent/auto 模式按钮禁用;发送成功清空,失败保留
describe('Composer — M192 图像附件', () => {
  const makeFile = (name: string, size = 128, type = 'image/png') =>
    new File([new Uint8Array(size)], name, { type });

  /** 走隐藏 file input 添加文件,并等 FileReader 把缩略图 dataURL 填进 chip。 */
  const addViaInput = async (files: File[], firstIdx = 0) => {
    const input = screen.getByTestId('composer-attach-input');
    fireEvent.change(input, { target: { files } });
    await waitFor(() => {
      const img = screen.getByTestId(`composer-att-${firstIdx}`).querySelector('img');
      expect(img?.getAttribute('src')?.startsWith('data:')).toBe(true);
    });
  };

  it('选择图像文件 → chips 渲染缩略图(dataURL)+name;× 移除', async () => {
    render(<Composer onSend={vi.fn()} mode='chat' />);
    await addViaInput([makeFile('shot.png')]);
    const chip = screen.getByTestId('composer-att-0');
    expect(chip.textContent).toContain('shot.png');
    const img = chip.querySelector('img') as HTMLImageElement;
    expect(img.getAttribute('src')?.startsWith('data:image/png;base64,')).toBe(true);
    expect(img.getAttribute('alt')).toBe('shot.png');
    fireEvent.click(screen.getByTestId('composer-att-remove-0'));
    expect(screen.queryByTestId('composer-atts')).toBeNull();
  });

  it('超过 4 张 → 第 5 张拒绝并提示「最多附加 4 张」', async () => {
    render(<Composer onSend={vi.fn()} mode='chat' />);
    await addViaInput([1, 2, 3, 4].map((i) => makeFile(`p${i}.png`)));
    expect(screen.getByTestId('composer-att-3')).toBeTruthy();
    const input = screen.getByTestId('composer-attach-input');
    fireEvent.change(input, { target: { files: [makeFile('p5.png')] } });
    expect(screen.queryByTestId('composer-att-4')).toBeNull();
    expect(screen.getByTestId('composer-attach-warn').textContent).toContain('最多附加 4 张');
  });

  it('单张超 2MB → 拒绝并提示,不进 chips', async () => {
    render(<Composer onSend={vi.fn()} mode='chat' />);
    const input = screen.getByTestId('composer-attach-input');
    fireEvent.change(input, { target: { files: [makeFile('big.png', 2 * 1024 * 1024 + 1)] } });
    expect(screen.queryByTestId('composer-atts')).toBeNull();
    expect(screen.getByTestId('composer-attach-warn').textContent).toContain('超过 2MB');
  });

  it('非白名单类型(text/plain)→ 静默忽略,不进 chips 也不提示', async () => {
    render(<Composer onSend={vi.fn()} mode='chat' />);
    const input = screen.getByTestId('composer-attach-input');
    fireEvent.change(input, { target: { files: [makeFile('note.txt', 64, 'text/plain')] } });
    expect(screen.queryByTestId('composer-atts')).toBeNull();
    expect(screen.queryByTestId('composer-attach-warn')).toBeNull();
  });

  it('textarea 粘贴剪贴板图像 → 与按钮同一入口进 chips', async () => {
    render(<Composer onSend={vi.fn()} mode='plan' />);
    const ta = screen.getByTestId('assistant-composer-input');
    fireEvent.paste(ta, { clipboardData: { files: [makeFile('clip.png')] } });
    await waitFor(() => {
      const img = screen.getByTestId('composer-att-0').querySelector('img');
      expect(img?.getAttribute('src')?.startsWith('data:')).toBe(true);
    });
    expect(screen.getByTestId('composer-att-0').textContent).toContain('clip.png');
  });

  it('agent/auto 模式附件按钮 disabled(title 提示仅 chat/plan);chat/plan 可用', () => {
    const { unmount } = render(<Composer onSend={vi.fn()} mode='agent' />);
    let btn = screen.getByTestId('composer-attach-btn') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.title).toBe('仅 chat/plan 支持图像附件');
    unmount();
    const { unmount: unmount2 } = render(<Composer onSend={vi.fn()} mode='auto' />);
    btn = screen.getByTestId('composer-attach-btn') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    unmount2();
    render(<Composer onSend={vi.fn()} mode='plan' />);
    btn = screen.getByTestId('composer-attach-btn') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    expect(btn.title).not.toBe('仅 chat/plan 支持图像附件');
  });

  it('onSend 第二参携带 PendingImage[](data_base64 无 data: 前缀),发送成功清空 chips', async () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} mode='chat' />);
    await addViaInput([makeFile('a.png')]);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '看这张图' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(onSend).toHaveBeenCalledTimes(1);
    const [text, images] = onSend.mock.calls[0] as unknown as [string, { name: string; media_type: string; data_base64: string }[]];
    expect(text).toBe('看这张图');
    expect(images).toHaveLength(1);
    expect(images[0].name).toBe('a.png');
    expect(images[0].media_type).toBe('image/png');
    expect(images[0].data_base64.length).toBeGreaterThan(0);
    expect(images[0].data_base64.startsWith('data:')).toBe(false);
    // 发送成功(onSend 返回 undefined 的同步路径)→ chips 清空
    expect(screen.queryByTestId('composer-atts')).toBeNull();
  });

  it('onSend 返回 rejected promise(发送失败)→ chips 保留供重试', async () => {
    const onSend = vi.fn(() => Promise.reject(new Error('net down')));
    render(<Composer onSend={onSend} mode='chat' />);
    await addViaInput([makeFile('a.png')]);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'hi' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByTestId('composer-att-0')).toBeTruthy();
  });
});
