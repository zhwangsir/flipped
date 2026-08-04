import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE, createRemoteSession, revokeRemoteToken } from '../api';
import type { RemoteSessionInfo } from '../types';
import { IconSmartphone } from '../icons';

/**
 * M181.2 — 移动远程控制弹窗(扫码在手机浏览器接管当前会话)。
 * 直调 api 不经 store,与 RulesPanel/ProjectMapPanel 同范式:
 * 打开即 POST /remote/sessions 生成限时 token;展示 QR/URL/倒计时;支持撤销与失败重试。
 * 遮罩点击不关闭(防误触),仅「关闭」按钮 / Escape 关闭;unmount 清理 interval 与复制提示 timer。
 */
export function RemoteModal({ sessionId, onClose }: { sessionId: string | null; onClose: () => void }) {
  const [info, setInfo] = useState<RemoteSessionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [remain, setRemain] = useState<number | null>(null); // 剩余秒
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [revoked, setRevoked] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await createRemoteSession(sessionId ?? undefined);
      setInfo(res);
      setRemain(Math.max(0, Math.floor((res.expires_at * 1000 - Date.now()) / 1000)));
      setRevoked(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  // 打开(mount)即生成一次;「重试」走同一 load
  useEffect(() => {
    load();
  }, [load]);

  // 倒计时:每秒按 expires_at*1000 - Date.now() 重算,到 0 停住不再减
  useEffect(() => {
    if (!info) return;
    const timer = setInterval(() => {
      setRemain((r) => {
        if (r !== null && r <= 0) return 0;
        return Math.max(0, Math.floor((info.expires_at * 1000 - Date.now()) / 1000));
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [info]);

  // Escape 关闭;遮罩点击不关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // unmount 清理「已复制」提示 timer
  useEffect(
    () => () => {
      if (copyTimer.current !== null) clearTimeout(copyTimer.current);
    },
    []
  );

  const copyUrl = async () => {
    if (!info) return;
    try {
      await navigator.clipboard.writeText(info.url);
    } catch {
      // fallback:无 clipboard 权限时走 textarea 选中 + execCommand
      const ta = document.createElement('textarea');
      ta.value = info.url;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setCopied(true);
    if (copyTimer.current !== null) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(false), 2000);
  };

  const revoke = async () => {
    if (!info || revoking || revoked) return; // busy/已撤销防连点
    setRevoking(true);
    setError(null);
    try {
      await revokeRemoteToken(info.token);
      setRevoked(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRevoking(false);
    }
  };

  const expired = remain !== null && remain <= 0;
  const mm = String(Math.floor((remain ?? 0) / 60)).padStart(2, '0');
  const ss = String((remain ?? 0) % 60).padStart(2, '0');

  return (
    <div className='remote-overlay'>
      <div className='remote-modal' role='dialog' aria-modal='true' aria-label='手机远程控制'>
        <div className='remote-title'>
          <IconSmartphone size={15} /> 手机远程控制
        </div>
        {loading && <div className='remote-loading'>生成中…</div>}
        {!loading && error && !info && (
          <>
            <div className='remote-error'>生成失败：{error}</div>
            <div className='remote-actions'>
              <button className='remote-btn' data-testid='remote-retry' onClick={() => load()}>
                重试
              </button>
              <button className='remote-btn' onClick={onClose}>
                关闭
              </button>
            </div>
          </>
        )}
        {!loading && info && (
          <>
            <div className='remote-sub'>{info.session_title}</div>
            <img className='remote-qr' src={`${API_BASE}${info.qr_url}`} alt='远程控制二维码' />
            <div className='remote-url-row'>
              <span className='remote-url'>{info.url}</span>
              <button className='remote-btn' onClick={copyUrl}>
                {copied ? '已复制' : '复制'}
              </button>
            </div>
            {info.host_note && (
              <div className='remote-host-note' data-testid='remote-host-note'>
                {info.host_note}
              </div>
            )}
            {expired ? (
              <div className='remote-countdown expired'>已过期，关闭重开可重新生成</div>
            ) : (
              <div className='remote-countdown'>
                链接有效期 {mm}:{ss}
              </div>
            )}
            {error && <div className='remote-error'>{error}</div>}
            <div className='remote-actions'>
              <button
                className='remote-btn danger'
                data-testid='remote-revoke'
                onClick={revoke}
                disabled={revoking || revoked}
              >
                {revoked ? '已撤销' : revoking ? '撤销中…' : '撤销链接'}
              </button>
              <button className='remote-btn' onClick={onClose}>
                关闭
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
