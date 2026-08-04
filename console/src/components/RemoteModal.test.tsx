import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { RemoteModal } from './RemoteModal';
import type { RemoteSessionInfo } from '../types';

// M181.2 — RemoteModal 单测:mock global.fetch(api.ts 底层 fetch 封装直通),
// 断言真实 URL/method/body,与 RulesPanel.test 的「面板自取数」范式同构(不经 store)。
const fetchMock = vi.fn();

const API = 'http://127.0.0.1:8011/api/v1';

const jsonRes = (body: unknown): Response =>
  ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) }) as Response;

const errRes = (status: number, text: string): Response =>
  ({ ok: false, status, json: async () => ({}), text: async () => text }) as Response;

const sample = (over: Partial<RemoteSessionInfo> = {}): RemoteSessionInfo => ({
  token: 'tok-1',
  url: 'http://192.168.1.5:8011/r/tok-1',
  qr_url: '/api/v1/remote/tok-1/qr.svg',
  session_id: 'sess-1',
  session_title: '我的会话',
  expires_at: Math.floor(Date.now() / 1000) + 600,
  host_note: '',
  ...over,
});

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('RemoteModal', () => {
  it('打开即调 POST /remote/sessions(body 含 session_id)', async () => {
    fetchMock.mockResolvedValue(jsonRes(sample()));
    render(<RemoteModal sessionId='sess-1' onClose={() => {}} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API}/remote/sessions`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ session_id: 'sess-1' });
  });

  it('sessionId=null → body 为 {}', async () => {
    fetchMock.mockResolvedValue(jsonRes(sample()));
    render(<RemoteModal sessionId={null} onClose={() => {}} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({});
  });

  it('成功 → QR img src = API_BASE + qr_url,展示标题/会话名/URL/倒计时', async () => {
    fetchMock.mockResolvedValue(jsonRes(sample()));
    render(<RemoteModal sessionId='sess-1' onClose={() => {}} />);
    const img = (await screen.findByAltText('远程控制二维码')) as HTMLImageElement;
    expect(img.getAttribute('src')).toBe(`${API}/remote/tok-1/qr.svg`);
    expect(screen.getByText('手机远程控制')).toBeInTheDocument();
    expect(screen.getByText('我的会话')).toBeInTheDocument();
    expect(screen.getByText('http://192.168.1.5:8011/r/tok-1')).toBeInTheDocument();
    expect(document.querySelector('.remote-countdown')?.textContent).toMatch(/链接有效期 \d{2}:\d{2}/);
  });

  it('host_note 非空 → 显示黄色提示行;空串 → 不显示', async () => {
    fetchMock.mockResolvedValue(jsonRes(sample({ host_note: '当前为回环地址，手机无法访问' })));
    const { unmount } = render(<RemoteModal sessionId='sess-1' onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByTestId('remote-host-note').textContent).toContain('回环地址')
    );
    unmount();
    fetchMock.mockResolvedValue(jsonRes(sample({ host_note: '' })));
    render(<RemoteModal sessionId='sess-1' onClose={() => {}} />);
    await screen.findByAltText('远程控制二维码');
    expect(screen.queryByTestId('remote-host-note')).toBeNull();
  });

  it('点「复制」→ clipboard.writeText(url) 且按钮变「已复制」', async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    fetchMock.mockResolvedValue(jsonRes(sample()));
    render(<RemoteModal sessionId='sess-1' onClose={() => {}} />);
    await screen.findByAltText('远程控制二维码');
    fireEvent.click(screen.getByText('复制'));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('http://192.168.1.5:8011/r/tok-1'));
    expect(screen.getByText('已复制')).toBeInTheDocument();
  });

  it('倒计时到期 → 显示「已过期，关闭重开可重新生成」', async () => {
    fetchMock.mockResolvedValue(
      jsonRes(sample({ expires_at: Math.floor(Date.now() / 1000) - 5 }))
    );
    render(<RemoteModal sessionId='sess-1' onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByText('已过期，关闭重开可重新生成')).toBeInTheDocument()
    );
    expect(screen.queryByText(/链接有效期/)).toBeNull();
  });

  it('点「撤销链接」→ 调 DELETE /remote/{token},按钮禁用并显示「已撤销」', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonRes(sample()))
      .mockResolvedValueOnce(jsonRes({ ok: true }));
    render(<RemoteModal sessionId='sess-1' onClose={() => {}} />);
    await screen.findByAltText('远程控制二维码');
    fireEvent.click(screen.getByTestId('remote-revoke'));
    await waitFor(() => expect(screen.getByText('已撤销')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe(`${API}/remote/tok-1`);
    expect(init.method).toBe('DELETE');
    expect((screen.getByTestId('remote-revoke') as HTMLButtonElement).disabled).toBe(true);
  });

  it('生成失败 → 红字错误 + 点「重试」再调一次 POST 成功恢复', async () => {
    fetchMock
      .mockResolvedValueOnce(errRes(500, 'boom'))
      .mockResolvedValueOnce(jsonRes(sample()));
    render(<RemoteModal sessionId='sess-1' onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByText(/生成失败：HTTP 500: boom/)).toBeInTheDocument()
    );
    fireEvent.click(screen.getByTestId('remote-retry'));
    await screen.findByAltText('远程控制二维码');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe('POST');
  });

  it('点「关闭」调 onClose', async () => {
    const onClose = vi.fn();
    fetchMock.mockResolvedValue(jsonRes(sample()));
    render(<RemoteModal sessionId='sess-1' onClose={onClose} />);
    await screen.findByAltText('远程控制二维码');
    fireEvent.click(screen.getByText('关闭'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('按 Escape 调 onClose', async () => {
    const onClose = vi.fn();
    fetchMock.mockResolvedValue(jsonRes(sample()));
    render(<RemoteModal sessionId='sess-1' onClose={onClose} />);
    await screen.findByAltText('远程控制二维码');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
