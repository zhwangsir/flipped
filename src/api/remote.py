"""M181.1 · 移动远程控制：token 注册表 + LAN IP 探测 + 自包含移动页 + QR（纯逻辑模块）。

手机扫码 → 远程查看会话进度/补需求/审批确认（对标 ZCode 远程控制）。
本模块零 FastAPI import、零 main/assistant import，时钟全部经 now 参数注入
（单测确定性，同 tasks.py 惯例）。端点在 main.py M181 区块。

安全边界：token=secrets.token_urlsafe(24)，TTL 到期即 purge；无效/过期一律 404
（不区分，无 oracle）；移动页零外部资源，动态文本一律 textContent 赋值防 XSS。
"""
from __future__ import annotations

import json
import os
import secrets
import socket
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class RemoteToken:
    """一条远程访问令牌（JSON 落盘形状 = asdict 原样，list 根元素）。"""

    token: str            # secrets.token_urlsafe(24) → 32 字符 urlsafe
    session_id: str       # 绑定单会话（远程面只暴露这一个会话）
    created_at: float     # epoch 秒
    expires_at: float     # created_at + ttl_s


class RemoteRegistry:
    """token 注册表：内存 list + JSON 持久化（tmp + os.replace 原子写，复刻 TaskRegistry 惯例）。

    文件不存在/JSON 损坏/结构非 list → 空注册表（不炸，防坏文件拖垮启动）。
    所有变更方法落盘后返回，构造时自动 load；过期 token 惰性 purge（issue/resolve 触发）。
    """

    def __init__(self, path: Path, ttl_s: int = 1800):
        self._path = Path(path)
        self._ttl_s = ttl_s
        self._tokens: list[RemoteToken] = []
        self._load()

    def _load(self) -> None:
        """从 JSON 文件加载 token 表（不存在/损坏/非 list → 保持空表）。"""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 坏文件不炸，回退空表
            return
        if not isinstance(data, list):
            return
        for raw in data:
            try:
                tok = RemoteToken(**raw)
            except TypeError:
                continue  # 字段漂移的脏条目跳过，不污染整表
            self._tokens.append(tok)

    def _save(self) -> None:
        """持久化到 JSON 文件（tmp + os.replace 原子写，防并发/崩溃写坏）。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = f"{self._path}.tmp"
        Path(tmp).write_text(
            json.dumps([asdict(t) for t in self._tokens], ensure_ascii=False, indent=2),
            encoding="utf-8")
        os.replace(tmp, self._path)

    def _purge_expired(self, now: float) -> int:
        """移除全部过期 token，返回移除条数（不落盘，由调用方决定）。"""
        before = len(self._tokens)
        self._tokens = [t for t in self._tokens if t.expires_at > now]
        return before - len(self._tokens)

    def issue(self, session_id: str, *, now: float) -> RemoteToken:
        """签发 token：同 session 旧 token 全部移除（单活），惰性 purge 过期，落盘。"""
        self._purge_expired(now)
        self._tokens = [t for t in self._tokens if t.session_id != session_id]
        tok = RemoteToken(
            token=secrets.token_urlsafe(24),
            session_id=session_id,
            created_at=now,
            expires_at=now + self._ttl_s,
        )
        self._tokens.append(tok)
        self._save()
        return tok

    def resolve(self, token: str, *, now: float) -> RemoteToken | None:
        """按 token  lookup：未知 → None；过期 → purge 落盘后 None（无 oracle 由端点统一 404）。"""
        for tok in self._tokens:
            if tok.token == token:
                if tok.expires_at <= now:
                    self._purge_expired(now)
                    self._save()
                    return None
                return tok
        return None

    def revoke(self, token: str) -> bool:
        """撤销 token：存在删 → True 落盘；不存在 → False（幂等由端点兜底成 200）。"""
        before = len(self._tokens)
        self._tokens = [t for t in self._tokens if t.token != token]
        if len(self._tokens) == before:
            return False
        self._save()
        return True


def detect_lan_ip() -> str:
    """探测主网卡 LAN IP：UDP connect 8.8.8.8:80（不发包，仅路由表查询）。

    任何异常（无网/沙箱拦截）→ '127.0.0.1' 回退（端点据此带 host_note 提示）。
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0] or "127.0.0.1"
    except Exception:  # noqa: BLE001 探测失败不炸，回退回环
        return "127.0.0.1"


# 自包含移动页：内联 CSS/JS 零外部资源；token 由服务端 replace 渲入 JS 常量。
# 所有动态文本一律 element.textContent 赋值（绝不 innerHTML 拼接），防 XSS。
_MOBILE_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>flipped 远程控制</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0f1115; color: #e6e6e6; font-family: system-ui, -apple-system, sans-serif;
       display: flex; flex-direction: column; height: 100vh; }
header { display: flex; align-items: center; gap: 10px; padding: 12px 14px;
         border-bottom: 1px solid #262a33; }
h1 { font-size: 15px; font-weight: 600; flex: 1; overflow: hidden;
     text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 12px; padding: 3px 10px; border-radius: 999px;
         background: #1d2330; color: #7aa2f7; flex-shrink: 0; }
main { flex: 1; overflow-y: auto; padding: 12px 14px 90px; }
.turns { display: flex; flex-direction: column; gap: 8px; }
.bubble { max-width: 82%; padding: 10px 13px; border-radius: 14px; font-size: 14px;
          line-height: 1.55; white-space: pre-wrap; word-break: break-word; }
.bubble.user { align-self: flex-end; background: #2563eb; color: #fff;
               border-bottom-right-radius: 4px; }
.bubble.assistant { align-self: flex-start; background: #262a33;
                    border-bottom-left-radius: 4px; }
.approval { border: 1px solid #b45309; background: #221a10; border-radius: 12px;
            padding: 12px 14px; margin-bottom: 12px; }
.approval.hidden { display: none; }
.approval-action { font-size: 14px; font-weight: 600; color: #fbbf24;
                   white-space: pre-wrap; word-break: break-word; }
.approval-reason { font-size: 12px; color: #a8adb8; margin-top: 4px; }
.approval-btns { display: flex; gap: 10px; margin-top: 10px; }
.btn { border: 0; border-radius: 10px; font-size: 15px; min-height: 46px;
       padding: 0 18px; cursor: pointer; }
.btn:disabled { opacity: 0.45; }
.btn.approve { flex: 1; background: #16a34a; color: #fff; }
.btn.reject { flex: 1; background: #3a2020; color: #f87171; }
.btn.send { background: #2563eb; color: #fff; }
.dead { text-align: center; color: #a8adb8; font-size: 15px; padding-top: 40vh; }
footer { position: fixed; left: 0; right: 0; bottom: 0; display: flex; gap: 8px;
         padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
         background: #14171d; border-top: 1px solid #262a33; }
#input { flex: 1; min-height: 46px; border-radius: 10px; border: 1px solid #262a33;
         background: #0f1115; color: #e6e6e6; font-size: 15px; padding: 0 12px; }
</style>
</head>
<body>
<header>
  <h1 id="title">flipped 远程控制</h1>
  <span id="status" class="badge"></span>
</header>
<main id="main">
  <div id="approval" class="approval hidden">
    <div id="approval-action" class="approval-action"></div>
    <div id="approval-reason" class="approval-reason"></div>
    <div class="approval-btns">
      <button id="btn-approve" class="btn approve" type="button">放行</button>
      <button id="btn-reject" class="btn reject" type="button">否决</button>
    </div>
  </div>
  <div id="turns" class="turns"></div>
</main>
<footer>
  <input id="input" type="text" placeholder="补充一句需求…" autocomplete="off">
  <button id="btn-send" class="btn send" type="button">发送</button>
</footer>
<script>
const TOKEN = '__REMOTE_TOKEN__';
const API = '/api/v1/remote/' + TOKEN;
let timer = null;
let sending = false;

function el(id) { return document.getElementById(id); }

function dead() {
  if (timer !== null) { clearInterval(timer); timer = null; }
  const main = el('main');
  main.textContent = '';
  const d = document.createElement('div');
  d.className = 'dead';
  d.textContent = '链接已失效';
  main.appendChild(d);
  el('input').disabled = true;
  el('btn-send').disabled = true;
}

async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (r.status === 404) { dead(); throw new Error('gone'); }
  return r;
}

function render(state) {
  el('title').textContent = state.title || 'flipped 远程控制';
  el('status').textContent = state.status || '';
  const turns = el('turns');
  turns.textContent = '';
  (state.turns || []).forEach(function (t) {
    const div = document.createElement('div');
    div.className = 'bubble ' + (t.role === 'user' ? 'user' : 'assistant');
    div.textContent = t.text || '';
    turns.appendChild(div);
  });
  const ap = el('approval');
  if (state.pending_approval) {
    ap.classList.remove('hidden');
    el('approval-action').textContent = state.pending_approval.action || '';
    el('approval-reason').textContent = state.pending_approval.reason || '';
    el('btn-approve').disabled = false;
    el('btn-reject').disabled = false;
  } else {
    ap.classList.add('hidden');
  }
}

async function poll() {
  try {
    const r = await api('/state');
    if (!r.ok) { return; }
    render(await r.json());
  } catch (e) { /* 网络抖动继续轮询；404 已在 api() 里 dead() */ }
}

async function decide(decision) {
  el('btn-approve').disabled = true;  // 点击即禁用，防重复提交
  el('btn-reject').disabled = true;
  try {
    await api('/decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision: decision }),
    });
  } catch (e) { /* 404 已 dead()；其余下一轮 poll 自愈 */ }
  poll();
}

async function send() {
  const input = el('input');
  const text = input.value.trim();
  if (!text || sending) { return; }
  sending = true;
  el('btn-send').disabled = true;  // 发送中禁用
  try {
    await api('/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text }),
    });
    input.value = '';
  } catch (e) { /* 404 已 dead()；其余下一轮 poll 自愈 */ }
  sending = false;
  el('btn-send').disabled = false;
  poll();
}

el('btn-approve').addEventListener('click', function () { decide('approve'); });
el('btn-reject').addEventListener('click', function () { decide('reject'); });
el('btn-send').addEventListener('click', send);
el('input').addEventListener('keydown', function (e) { if (e.key === 'Enter') { send(); } });
poll();
timer = setInterval(poll, 2500);
</script>
</body>
</html>
"""


def mobile_page_html(token: str) -> str:
    """返回自包含移动远程控制页 HTML（token 渲入 JS 常量 const TOKEN）。

    token 是 secrets.token_urlsafe 产物（仅 [A-Za-z0-9_-]），嵌入单引号 JS 字符串安全。
    页面全部 fetch 走同源相对路径（/api/v1/remote/<token>/...），零 CORS。
    """
    return _MOBILE_PAGE.replace("__REMOTE_TOKEN__", token)


def qr_svg(data: str) -> str:
    """把 data 编码成 QR 的 SVG 字符串（segno 纯 Python，零外部依赖）。"""
    import io  # 函数级 import：纯逻辑模块保持轻量，仅在出码时加载

    import segno

    buf = io.BytesIO()
    segno.make(data).save(buf, kind="svg", xmldecl=False, dark="#111", light="#fff")
    return buf.getvalue().decode("utf-8")
