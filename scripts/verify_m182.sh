#!/usr/bin/env bash
# M182 验收 — Bot Channel 多平台接入（Telegram webhook + 企业微信应用回调：
# 统一消息接口 / 身份映射 / 加密验证 / 状态监控与异常处理）。
#
#   1) pytest 单测：test_m182_bot_channel.py（29）+ test_m182_bot_telegram.py（16）
#      + test_m182_bot_wecom.py（19）＝ 64 例（registry/stats/wait_for_reply/handle_inbound
#      纯逻辑；TG 验签/解析/sender；WeCom AES 加解密/XML 解析/sender token 缓存）
#   2) 真实后端黑盒 E2E：真 uvicorn ×2（:PORT 正常 + :PORT_OFF 置 FLIPPED_BOT=0）
#      + 假 OpenAI server（回显 "RE:<user>"，供 bot 入站消息走 canonical chat 通路）：
#        a. GET /bot/channels → 200，两平台按字典序且 configured=true
#        b. TG webhook：无 secret 头 403 / 错 secret 403 / 非文本 200 handled=false /
#           非法 JSON 200 handled=false
#        c. TG test 端点：无绑定 400 →（入站绑定后）假 token 发送失败 502 ok=false；
#           未知平台 404
#        d. TG 文本消息 → 200 handled=true；轮询 channels 至 inbound=1 且 error=1
#           （假 token 发 api.telegram.org 必失败 → 异常处理路径记 error）
#        e. WeCom URL 验证：正确签名 → 200 明文 == 原 echostr；坏签名 → 403
#        f. WeCom 消息回调：加密 text XML → "success"；轮询 wecom inbound=1；
#           test 端点假 corp 发送失败 502
#        g. FLIPPED_BOT=0 实例：channels 与 webhook 全 404
#      （前端 BotChannelPanel 证据在 vitest BotChannelPanel.test.tsx）
#
# 一键复跑: scripts/verify_m182.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8189}"
PORT_OFF="${FLIPPED_VERIFY_PORT_OFF:-8190}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8191}"
SRV_PID=""; SRV_OFF_PID=""; FAKE_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  [ -n "$SRV_OFF_PID" ] && kill "$SRV_OFF_PID" 2>/dev/null; wait "$SRV_OFF_PID" 2>/dev/null
  [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; wait "$FAKE_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"
export FLIPPED_SESSION_STORE_PATH="$TMPD/.sessions.json"

echo "== M182-1 单测（64 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m182_bot_channel.py tests/test_m182_bot_telegram.py tests/test_m182_bot_wecom.py -q \
  && pass "M182 单测全绿" || bad "M182 单测失败"

echo "== M182-2 真实后端黑盒 E2E（uvicorn :${PORT} + FLIPPED_BOT=0 实例 :${PORT_OFF} + 假 LLM :${FAKE_PORT}） =="

# 假 OpenAI 兼容端点：回显 "RE:<user 文本>"（chat 通路，与 verify_m181.sh 同款）
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        user = ""
        for m in body.get("messages", []):
            if m.get("role") == "user":
                user = str(m.get("content", ""))
        out = {"choices": [{"message": {"role": "assistant", "content": "RE:" + user}}],
               "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def log_message(self, *a):
        pass

HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
FAKEEOF
$PY "$TMPD/fake_llm.py" "${FAKE_PORT}" &
FAKE_PID=$!

# 企业微信 EncodingAESKey：43 字符 base64（32 字节密钥的 b64 去掉尾 '='）
AES_KEY=$($PY -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode()[:43])")

FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 FLIPPED_RULES_AUTO=0 \
FLIPPED_TASKS=0 \
FLIPPED_BOT_TELEGRAM_TOKEN="fake-tg-token-m182" \
FLIPPED_BOT_TELEGRAM_SECRET="tg-secret-m182" \
FLIPPED_BOT_WECOM_TOKEN="wc-token-m182" \
FLIPPED_BOT_WECOM_AES_KEY="${AES_KEY}" \
FLIPPED_BOT_WECOM_CORP_ID="wwfakem182" \
FLIPPED_BOT_WECOM_SECRET="wc-corpsecret-m182" \
FLIPPED_BOT_WECOM_AGENT_ID="1000002" \
FLIPPED_BOT_DB="$TMPD/bot_sessions.json" \
FLIPPED_BOT_STATS_DB="$TMPD/bot_stats.json" \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!

FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 FLIPPED_RULES_AUTO=0 \
FLIPPED_TASKS=0 \
FLIPPED_BOT=0 \
FLIPPED_BOT_DB="$TMPD/bot_sessions_off.json" \
FLIPPED_BOT_STATS_DB="$TMPD/bot_stats_off.json" \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT_OFF}" --log-level warning &
SRV_OFF_PID=$!

ready=0
for _ in $(seq 1 60); do
  ok1=$(curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1 && echo 1)
  ok2=$(curl -sf "http://127.0.0.1:${PORT_OFF}/api/v1/health" -o /dev/null 2>&1 && echo 1)
  if [ "${ok1}" = "1" ] && [ "${ok2}" = "1" ]; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M182 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
FLIPPED_BASE_OFF="http://127.0.0.1:${PORT_OFF}" \
TG_SECRET="tg-secret-m182" \
WECOM_TOKEN="wc-token-m182" \
WECOM_AES_KEY="${AES_KEY}" \
WECOM_CORP_ID="wwfakem182" \
PYTHONPATH=src ${PY} - <<'PYEOF'
import json, os, sys, time, urllib.request, urllib.error, urllib.parse

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
BASE_OFF = os.environ["FLIPPED_BASE_OFF"] + "/api/v1"
TG_SECRET = os.environ["TG_SECRET"]
fails = []

from api.bot_wecom import WeComCrypto  # PYTHONPATH=src 由外层注入

crypto = WeComCrypto(os.environ["WECOM_TOKEN"], os.environ["WECOM_AES_KEY"],
                     os.environ["WECOM_CORP_ID"])

def call(method, path, body=None, raw=False, headers=None, base=BASE, timeout=40):
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    data = body
    if body is not None and not isinstance(body, (bytes, str)):
        data = json.dumps(body).encode()
    if isinstance(data, str):
        data = data.encode()
    req = urllib.request.Request(base + path, method=method, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            return r.status, (payload if raw else json.loads(payload or b"{}"))
    except urllib.error.HTTPError as e:
        payload = e.read()
        if raw:
            return e.code, payload
        try:
            return e.code, json.loads(payload or b"{}")
        except json.JSONDecodeError:
            return e.code, payload

def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)

def channels():
    st, body = call("GET", "/bot/channels")
    assert st == 200, f"channels HTTP {st}"
    return {c["platform"]: c for c in body["channels"]}

# ---------- a. channels 列表：两平台字典序、configured/enabled 齐 ----------
st, body = call("GET", "/bot/channels")
plats = [c["platform"] for c in body.get("channels", [])]
check("a.GET /bot/channels → 200，[telegram, wecom] 字典序且 configured/enabled=true",
      st == 200 and plats == ["telegram", "wecom"]
      and all(c["configured"] is True and c["enabled"] is True for c in body["channels"])
      and all(c["inbound_count"] == 0 and c["error_count"] == 0 for c in body["channels"]),
      detail=f"HTTP {st} {json.dumps(body)[:200]}")

# ---------- b. TG webhook 验签与容错 ----------
st, _ = call("POST", "/bot/telegram/webhook", {"update_id": 1})
check("b1.TG webhook 无 secret 头 → 403", st == 403, detail=f"HTTP {st}")
st, _ = call("POST", "/bot/telegram/webhook", {"update_id": 1},
             headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"})
check("b2.TG webhook 错 secret → 403", st == 403, detail=f"HTTP {st}")
st, body = call("POST", "/bot/telegram/webhook",
                {"update_id": 2, "message": {"message_id": 5, "chat": {"id": 67890},
                                             "from": {"id": 123}, "photo": []}},
                headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET})
check("b3.TG 非文本消息 → 200 handled=false",
      st == 200 and body.get("ok") is True and body.get("handled") is False,
      detail=f"HTTP {st} {json.dumps(body)[:120]}")
st, body = call("POST", "/bot/telegram/webhook", b"not-json{{{", raw=False,
                headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET})
check("b4.TG 非法 JSON → 200 handled=false（防 Telegram 重试风暴）",
      st == 200 and isinstance(body, dict) and body.get("handled") is False,
      detail=f"HTTP {st} {str(body)[:120]}")

# ---------- c. TG test 端点：无绑定 400 / 未知平台 404 ----------
st, body = call("POST", "/bot/channels/telegram/test", {"text": "hi"})
check("c1.TG test 无绑定 → 400", st == 400, detail=f"HTTP {st} {str(body)[:120]}")
st, _ = call("POST", "/bot/channels/slack/test", {"text": "hi"})
check("c2.未知平台 test → 404", st == 404, detail=f"HTTP {st}")

# ---------- d. TG 文本消息全链路：绑定 → 编排 → 假 LLM 回复 → 发送失败记 error ----------
MARK_TG = "M182TG_机器人你好"
tg_update = {"update_id": 3,
             "message": {"message_id": 10,
                         "from": {"id": 12345, "username": "e2euser"},
                         "chat": {"id": 67890}, "text": MARK_TG}}
st, body = call("POST", "/bot/telegram/webhook", tg_update,
                headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET})
check("d1.TG 文本消息 → 200 handled=true",
      st == 200 and body.get("handled") is True, detail=f"HTTP {st} {json.dumps(body)[:120]}")

tg_in = tg_err = False
for _ in range(60):
    time.sleep(0.5)
    ch = channels()
    tg_in = ch["telegram"]["inbound_count"] >= 1
    tg_err = ch["telegram"]["error_count"] >= 1
    if tg_in and tg_err:
        break
check("d2.轮询 channels：telegram inbound=1 且 error=1（假 token 发送必失败 → 异常处理记 error）",
      tg_in and tg_err, detail=f"inbound={tg_in} error={tg_err}")

st, body = call("POST", "/bot/channels/telegram/test", {"text": "绑定后测试"})
check("d3.TG test 已绑定但假 token → 502 ok=false（error 字段非空）",
      st == 502 and isinstance(body, dict) and body.get("ok") is False and bool(body.get("error")),
      detail=f"HTTP {st} {str(body)[:160]}")

# ---------- e. WeCom URL 验证：正确签名明文直出；坏签名 403 ----------
ECHO = "m182-echo-随机串123"
echostr = crypto.encrypt(ECHO)
ts, nonce = "1700000000", "nonce-m182"
sig = crypto.verify_signature  # noqa 仅防误用提示
import hashlib
def wecom_sig(encrypt):
    return hashlib.sha1("".join(sorted([os.environ["WECOM_TOKEN"], ts, nonce, encrypt])).encode()).hexdigest()

qs = urllib.parse.urlencode({"msg_signature": wecom_sig(echostr), "timestamp": ts,
                             "nonce": nonce, "echostr": echostr})
st, payload = call("GET", f"/bot/wecom/callback?{qs}", raw=True)
check("e1.WeCom URL 验证正确签名 → 200 明文 == 原 echostr",
      st == 200 and payload.decode("utf-8") == ECHO,
      detail=f"HTTP {st} body={payload[:60]!r}")
qs_bad = urllib.parse.urlencode({"msg_signature": "0" * 40, "timestamp": ts,
                                 "nonce": nonce, "echostr": echostr})
st, _ = call("GET", f"/bot/wecom/callback?{qs_bad}", raw=True)
check("e2.WeCom URL 验证坏签名 → 403", st == 403, detail=f"HTTP {st}")

# ---------- f. WeCom 消息回调：加密 text XML → success；inbound=1；test 502 ----------
MARK_WC = "M182WC_微信你好"
inner_xml = (
    "<xml>"
    f"<ToUserName><![CDATA[{os.environ['WECOM_CORP_ID']}]]></ToUserName>"
    "<FromUserName><![CDATA[zhangsan]]></FromUserName>"
    "<CreateTime>1700000001</CreateTime>"
    "<MsgType><![CDATA[text]]></MsgType>"
    f"<Content><![CDATA[{MARK_WC}]]></Content>"
    "<MsgId>1234567890123456</MsgId>"
    "<AgentID>1000002</AgentID>"
    "</xml>"
)
encrypt = crypto.encrypt(inner_xml)
outer_xml = (
    "<xml>"
    f"<Encrypt><![CDATA[{encrypt}]]></Encrypt>"
    f"<MsgSignature><![CDATA[{wecom_sig(encrypt)}]]></MsgSignature>"
    f"<TimeStamp>{ts}</TimeStamp>"
    f"<Nonce><![CDATA[{nonce}]]></Nonce>"
    "</xml>"
)
qs2 = urllib.parse.urlencode({"msg_signature": wecom_sig(encrypt),
                              "timestamp": ts, "nonce": nonce})
st, payload = call("POST", f"/bot/wecom/callback?{qs2}", outer_xml.encode(), raw=True)
check("f1.WeCom 加密 text 回调 → 200 明文 success",
      st == 200 and payload.decode("utf-8") == "success",
      detail=f"HTTP {st} body={payload[:40]!r}")

wc_in = False
for _ in range(60):
    time.sleep(0.5)
    ch = channels()
    wc_in = ch["wecom"]["inbound_count"] >= 1
    if wc_in:
        break
check("f2.轮询 channels：wecom inbound=1（身份映射+入站编排生效）",
      wc_in, detail=f"inbound={wc_in}")

st, body = call("POST", "/bot/channels/wecom/test", {"text": "绑定后测试"})
check("f3.WeCom test 已绑定但假 corp → 502 ok=false（error 字段非空）",
      st == 502 and isinstance(body, dict) and body.get("ok") is False and bool(body.get("error")),
      detail=f"HTTP {st} {str(body)[:160]}")

# ---------- g. FLIPPED_BOT=0 实例：全端点 404 ----------
st1, _ = call("GET", "/bot/channels", base=BASE_OFF)
st2, _ = call("POST", "/bot/telegram/webhook", tg_update,
              headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET}, base=BASE_OFF)
st3, _ = call("GET", f"/bot/wecom/callback?{qs}", raw=True, base=BASE_OFF)
st4, _ = call("POST", "/bot/channels/telegram/test", {"text": "x"}, base=BASE_OFF)
check("g.FLIPPED_BOT=0 实例：channels/webhook/callback/test 全 404",
      st1 == 404 and st2 == 404 and st3 == 404 and st4 == 404,
      detail=f"channels={st1} tg={st2} wc={st3} test={st4}")

print("")
if fails:
    print("M182 黑盒失败项: " + ", ".join(fails))
    sys.exit(1)
print("  ✅ 黑盒 E2E 全绿")
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 有失败"

echo ""
if [ $fail -eq 0 ]; then
  echo "M182（Bot Channel 多平台接入）验收：通过 ✅"
else
  echo "M182 验收：有未通过 ❌"
fi
exit $fail
