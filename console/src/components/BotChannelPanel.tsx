import { useCallback, useEffect, useState } from 'react';
import { fetchBotChannels, testBotChannel } from '../api';
import type { BotChannelInfo } from '../types';
import { formatWhen } from '../types';
import { IconBot } from '../icons';

/**
 * M182 — Bot 通道面板(多平台消息接入:telegram/wecom)。
 * 不经 store,直接调 api.ts 自取数(useState + useEffect),与 RulesPanel/RemoteModal 范式同构。
 * mount 即拉取通道状态;configured 通道可行内发测试消息;全部未配置时给 env 配置引导。
 */

/** 平台显示名映射(未命中原样透传)。 */
const PLATFORM_NAME: Record<string, string> = {
  telegram: 'Telegram',
  wecom: '企业微信',
};

/** 空态 env 配置引导(与后端读取的环境变量一一对应)。 */
const ENV_HINTS = [
  'FLIPPED_BOT_TELEGRAM_TOKEN',
  'FLIPPED_BOT_WECOM_CORP_ID',
  'FLIPPED_BOT_WECOM_AGENT_ID',
  'FLIPPED_BOT_WECOM_SECRET',
  'FLIPPED_BOT_WECOM_TOKEN',
];

/** Unix 秒 → 相对时间(复用 types.ts 既有 formatWhen,内部转 ISO)。 */
function relWhen(tsSec: number): string {
  return formatWhen(new Date(tsSec * 1000).toISOString());
}

export function BotChannelPanel() {
  const [channels, setChannels] = useState<BotChannelInfo[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null); // 发送中的 platform
  const [results, setResults] = useState<Record<string, { ok: boolean; error?: string }>>({});

  const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchBotChannels();
      setChannels(res);
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const sendTest = async (platform: string) => {
    if (testing) return; // busy 态防连点
    setTesting(platform);
    try {
      const r = await testBotChannel(platform, 'ping from console');
      setResults((m) => ({ ...m, [platform]: r }));
    } catch (e) {
      setResults((m) => ({ ...m, [platform]: { ok: false, error: errText(e) } }));
    } finally {
      setTesting(null);
    }
  };

  if (loading && !channels) {
    return (
      <div className="side-empty" data-testid="bot-panel">
        加载中…
      </div>
    );
  }
  if (error && !channels) {
    return (
      <div className="side-empty" data-testid="bot-panel">
        <div>加载失败：{error}</div>
        <button className="rdiff-refresh bot-retry" data-testid="bot-retry" onClick={() => load()}>
          重试
        </button>
      </div>
    );
  }

  const list = channels ?? [];
  const noneConfigured = list.every((c) => !c.configured);

  if (noneConfigured) {
    return (
      <div className="bot" data-testid="bot-panel">
        <div className="bot-empty">
          <IconBot size={20} />
          <div>未配置任何 Bot 通道</div>
          <div className="bot-empty-sub">在后端环境变量中配置以下项后重启服务即可接入：</div>
          <div className="bot-envs">
            {ENV_HINTS.map((v) => (
              <code key={v} className="bot-env">
                {v}
              </code>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bot" data-testid="bot-panel">
      {list.map((c) => {
        const res = results[c.platform];
        return (
          <div className="bot-card" data-testid={`bot-card-${c.platform}`} key={c.platform}>
            <div className="bot-card-head">
              <IconBot size={14} />
              <span className="bot-name">{PLATFORM_NAME[c.platform] ?? c.platform}</span>
              <span className={'bot-badge' + (c.configured ? ' ok' : '')}>
                {c.configured ? '已配置' : '未配置'}
              </span>
              <span className={'bot-badge' + (c.enabled ? ' ok' : '')}>{c.enabled ? '启用' : '停用'}</span>
            </div>
            <div className="bot-counts">
              入站 {c.inbound_count} · 出站 {c.outbound_count} · 错误 {c.error_count}
            </div>
            {c.last_inbound_at != null && <div className="bot-last">最近入站 {relWhen(c.last_inbound_at)}</div>}
            {c.last_error && <div className="bot-error">{c.last_error}</div>}
            {c.configured && (
              <div className="bot-actions">
                <button
                  className="rdiff-refresh"
                  data-testid={`bot-test-${c.platform}`}
                  disabled={testing === c.platform}
                  onClick={() => sendTest(c.platform)}
                >
                  {testing === c.platform ? '发送中…' : '发测试消息'}
                </button>
                {res &&
                  (res.ok ? (
                    <span className="bot-sent">已发送</span>
                  ) : (
                    <span className="bot-error">{res.error || '发送失败'}</span>
                  ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
