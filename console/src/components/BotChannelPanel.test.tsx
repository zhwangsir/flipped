import { afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { BotChannelPanel } from './BotChannelPanel';
import type { BotChannelInfo } from '../types';

// 面板自取数:mock ../api 模块(不经 store),与 RulesPanel.test 同范式
vi.mock('../api', () => ({
  fetchBotChannels: vi.fn(),
  testBotChannel: vi.fn(),
}));

import { fetchBotChannels, testBotChannel } from '../api';

const mockedFetch = vi.mocked(fetchBotChannels);
const mockedTest = vi.mocked(testBotChannel);

const tgChannel: BotChannelInfo = {
  platform: 'telegram',
  enabled: true,
  configured: true,
  inbound_count: 3,
  outbound_count: 5,
  error_count: 1,
  last_inbound_at: Math.floor(Date.now() / 1000) - 300, // 5 分钟前
  last_outbound_at: Math.floor(Date.now() / 1000) - 120,
  last_error: '',
};

const wecomChannel: BotChannelInfo = {
  platform: 'wecom',
  enabled: false,
  configured: false,
  inbound_count: 0,
  outbound_count: 0,
  error_count: 0,
  last_inbound_at: null,
  last_outbound_at: null,
  last_error: '',
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('BotChannelPanel', () => {
  it('mount 即调 fetchBotChannels 一次', async () => {
    mockedFetch.mockResolvedValue([tgChannel]);
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByTestId('bot-card-telegram')).toBeInTheDocument());
    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  it('loading 骨架渲染「加载中…」', () => {
    mockedFetch.mockReturnValue(new Promise(() => {})); // 永不 resolve
    render(<BotChannelPanel />);
    expect(screen.getByText('加载中…')).toBeInTheDocument();
    expect(screen.getByTestId('bot-panel')).toBeInTheDocument();
  });

  it('双通道卡片渲染(显示名映射 + configured 绿「已配置」徽标 + 启用徽标)', async () => {
    mockedFetch.mockResolvedValue([tgChannel, { ...wecomChannel, configured: true, enabled: true }]);
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByTestId('bot-card-telegram')).toBeInTheDocument());
    expect(screen.getByTestId('bot-card-wecom')).toBeInTheDocument();
    expect(screen.getByText('Telegram')).toBeInTheDocument();
    expect(screen.getByText('企业微信')).toBeInTheDocument();
    const badges = screen.getAllByText('已配置');
    expect(badges.length).toBe(2);
    expect(badges[0].className).toContain('ok');
    expect(screen.getAllByText('启用').length).toBe(2);
  });

  it('未配置/停用 → 灰徽标(无 ok 类)', async () => {
    mockedFetch.mockResolvedValue([tgChannel, wecomChannel]);
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByTestId('bot-card-wecom')).toBeInTheDocument());
    const unconf = screen.getByText('未配置');
    expect(unconf.className).not.toContain('ok');
    const disabled = screen.getByText('停用');
    expect(disabled.className).not.toContain('ok');
  });

  it('三计数行显示「入站 n · 出站 n · 错误 n」', async () => {
    mockedFetch.mockResolvedValue([tgChannel]);
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByText('入站 3 · 出站 5 · 错误 1')).toBeInTheDocument());
  });

  it('last_inbound_at 非空 → 「最近入站 x 分钟前」相对时间', async () => {
    mockedFetch.mockResolvedValue([tgChannel]);
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByText(/最近入站 5 分钟前/)).toBeInTheDocument());
  });

  it('last_inbound_at=null 不渲染最近入站行', async () => {
    mockedFetch.mockResolvedValue([{ ...tgChannel, last_inbound_at: null }]);
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByTestId('bot-card-telegram')).toBeInTheDocument());
    expect(screen.queryByText(/最近入站/)).toBeNull();
  });

  it('last_error 非空 → 红字行', async () => {
    mockedFetch.mockResolvedValue([{ ...tgChannel, last_error: 'token 过期' }]);
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByText('token 过期')).toBeInTheDocument());
    expect(screen.getByText('token 过期').className).toContain('bot-error');
  });

  it('「发测试消息」调 testBotChannel 成功 → 绿「已发送」', async () => {
    mockedFetch.mockResolvedValue([tgChannel]);
    mockedTest.mockResolvedValue({ ok: true });
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByTestId('bot-test-telegram')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('bot-test-telegram'));
    await waitFor(() => expect(screen.getByText('已发送')).toBeInTheDocument());
    expect(mockedTest).toHaveBeenCalledWith('telegram', 'ping from console');
    expect(screen.getByText('已发送').className).toContain('bot-sent');
  });

  it('「发测试消息」失败 → 红字 error', async () => {
    mockedFetch.mockResolvedValue([tgChannel]);
    mockedTest.mockResolvedValue({ ok: false, error: 'chat_id 未配置' });
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByTestId('bot-test-telegram')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('bot-test-telegram'));
    await waitFor(() => expect(screen.getByText('chat_id 未配置')).toBeInTheDocument());
    expect(screen.queryByText('已发送')).toBeNull();
  });

  it('发送中按钮禁用 + 文案「发送中…」', async () => {
    mockedFetch.mockResolvedValue([tgChannel]);
    mockedTest.mockReturnValue(new Promise(() => {})); // 永不 resolve
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByTestId('bot-test-telegram')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('bot-test-telegram'));
    const btn = screen.getByTestId('bot-test-telegram') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain('发送中…');
  });

  it('configured=false 的通道不渲染「发测试消息」按钮', async () => {
    mockedFetch.mockResolvedValue([tgChannel, wecomChannel]); // tg configured,wecom 未配置
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByTestId('bot-card-wecom')).toBeInTheDocument());
    expect(screen.getByTestId('bot-test-telegram')).toBeInTheDocument();
    expect(screen.queryByTestId('bot-test-wecom')).toBeNull();
  });

  it('全部 configured=false → 空态引导「未配置任何 Bot 通道」+ env 提示(<code>)', async () => {
    mockedFetch.mockResolvedValue([wecomChannel]);
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByText('未配置任何 Bot 通道')).toBeInTheDocument());
    expect(screen.getByText('FLIPPED_BOT_TELEGRAM_TOKEN').tagName).toBe('CODE');
    expect(screen.getByText('FLIPPED_BOT_WECOM_CORP_ID').tagName).toBe('CODE');
    expect(screen.getByText('FLIPPED_BOT_WECOM_AGENT_ID').tagName).toBe('CODE');
    expect(screen.getByText('FLIPPED_BOT_WECOM_SECRET').tagName).toBe('CODE');
    expect(screen.getByText('FLIPPED_BOT_WECOM_TOKEN').tagName).toBe('CODE');
    // 空态不渲染通道卡
    expect(screen.queryByTestId('bot-card-wecom')).toBeNull();
  });

  it('加载失败 → 红字 + 「重试」按钮点击后恢复', async () => {
    mockedFetch.mockRejectedValueOnce(new Error('HTTP 500: boom'));
    render(<BotChannelPanel />);
    await waitFor(() => expect(screen.getByText(/加载失败：HTTP 500: boom/)).toBeInTheDocument());
    mockedFetch.mockResolvedValue([tgChannel]);
    fireEvent.click(screen.getByTestId('bot-retry'));
    await waitFor(() => expect(screen.getByTestId('bot-card-telegram')).toBeInTheDocument());
    expect(mockedFetch).toHaveBeenCalledTimes(2);
  });
});
