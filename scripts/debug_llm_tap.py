"""M149.15 LLM 请求窃听代理：:4100 监听，转发到 LiteLLM :4000，
把每个请求的关键字段(stream/extra_body/messages 总长/tools 数)落盘到 /tmp/llm_tap.log。

用法: .venv/bin/python scripts/debug_llm_tap.py  (前台运行)
"""
import json
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "http://localhost:4000"
LOG = "/tmp/llm_tap.log"


def _log(obj):
    with open(LOG, "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


class Tap(BaseHTTPRequestHandler):
    def _proxy(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        path = self.path
        if path.rstrip("/").endswith("chat/completions") and body:
            try:
                j = json.loads(body)
                msgs = j.get("messages") or []
                total = sum(len(json.dumps(m, ensure_ascii=False)) for m in msgs)
                # 全量落盘大请求(>5k),供与探针 payload 逐字节 diff
                if total > 5000:
                    n = int(time.time())
                    with open(f"/tmp/llm_tap_body_{n}.json", "w") as bf:
                        json.dump(j, bf, ensure_ascii=False, indent=1)
                _log({
                    "ts": time.strftime("%H:%M:%S"),
                    "path": path,
                    "model": j.get("model"),
                    "stream": j.get("stream"),
                    "temperature": j.get("temperature"),
                    "has_extra_body": "extra_body" in j,
                    "extra_body": j.get("extra_body"),
                    "n_messages": len(msgs),
                    "roles": [m.get("role") for m in msgs],
                    "total_chars": total,
                    "n_tools": len(j.get("tools") or []),
                    "other_keys": sorted(k for k in j if k not in
                                         ("messages", "tools", "model", "stream",
                                          "temperature", "extra_body")),
                })
            except Exception as exc:
                _log({"ts": time.strftime("%H:%M:%S"), "parse_err": str(exc)})
        req = urllib.request.Request(
            UPSTREAM + path, data=body if body else None, method=method,
            headers={k: v for k, v in self.headers.items()
                     if k.lower() not in ("host", "content-length")})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = resp.read()
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    # M149.17: 必须滤掉 server/date——send_response 会自动加 Server/Date，
                    # 再转发上游的就会形成重复 Server 头，aiohttp 严格解析直接 400
                    # （agent-server 报 "Connection error" 的真实根因，urllib 探针 tolerates 故漏检）。
                    if k.lower() not in ("transfer-encoding", "connection", "content-length",
                                         "server", "date"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(exc).encode())

    do_GET = lambda s: s._proxy("GET")
    do_POST = lambda s: s._proxy("POST")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    _log({"ts": time.strftime("%H:%M:%S"), "event": "tap_start", "port": 4100})
    # M149.17: HTTPServer→ThreadingHTTPServer。单线程时并发 LLM 调用被串行饿死，
    # agent-server 侧表现为 Connection error + 同 payload 重试（实测 3727ch 3 连重试）。
    ThreadingHTTPServer(("127.0.0.1", 4100), Tap).serve_forever()
