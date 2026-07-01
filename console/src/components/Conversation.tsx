import { useState } from "react";
import { useApp } from "../store";
import type { Role, StreamItem, ToolCall } from "../types";
import {
  ToolIcon,
  IconSend,
  IconCheck,
  IconSparkle,
  IconChat,
  IconLayout,
  IconAt,
  IconClip,
  IconPuzzle,
  IconCube,
  IconChevronDown,
} from "../icons";

const ROLE: Record<Role, { label: string; cls: string; avatar: string }> = {
  user: { label: "你", cls: "user", avatar: "你" },
  supervisor: { label: "Supervisor · 调度", cls: "supervisor", avatar: "S" },
  worker: { label: "Worker · 执行", cls: "worker", avatar: "W" },
  overseer: { label: "Overseer · 监督", cls: "overseer", avatar: "O" },
  verify: { label: "强制验收", cls: "verify", avatar: "✓" },
  system: { label: "系统", cls: "system", avatar: "⚙" },
};

function Turn({ item }: { item: StreamItem }) {
  const r = ROLE[item.role];
  return (
    <div className={"turn " + item.role}>
      <div className={"avatar " + r.cls}>{r.avatar}</div>
      <div>
        {item.role !== "user" && (
          <div className="role-line">
            <span className={"role-name rc-" + item.role}>{r.label}</span>
            {item.model && <span className="role-model">{item.model}</span>}
          </div>
        )}
        {item.text && <div className="turn-text">{item.text}</div>}

        {item.tools && (
          <div className="tools">
            {item.tools.map((t, i) => (
              <ToolRow key={i} tool={t} />
            ))}
          </div>
        )}

        {item.verdict && (
          <div className="verdict">
            <div className="meters">
              {(["efficiency", "direction"] as const).map((k) => (
                <div className="meter" key={k}>
                  <div className="meter-top">
                    <span>{k === "efficiency" ? "效率" : "方向"}</span>
                    <b>{item.verdict![k].toFixed(2)}</b>
                  </div>
                  <div className="meter-track">
                    <span className="meter-fill" style={{ width: `${item.verdict![k] * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <div className="verdict-note">{item.verdict.note}</div>
            <span className="verdict-action">action = {item.verdict.action}</span>
          </div>
        )}

        {item.role === "verify" && item.ok && (
          <div className="verify-banner">
            <IconCheck size={16} /> {item.text}
          </div>
        )}
      </div>
    </div>
  );
}

function ToolRow({ tool }: { tool: ToolCall }) {
  return (
    <div className="tool">
      <span className="tool-ic">
        <ToolIcon name={tool.tool} />
      </span>
      <div className="tool-body">
        <div className="tool-sum">{tool.summary}</div>
        {tool.detail && <div className="tool-det">{tool.detail}</div>}
      </div>
      <span className={"tool-status " + tool.status}>
        {tool.status === "ok" && <IconCheck size={11} />}
        {tool.status === "ok" ? "完成" : tool.status === "running" ? "运行中" : tool.status}
      </span>
    </div>
  );
}

export function Conversation() {
  const { stream, sendTask, connection, selectedSessionId } = useApp();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      await sendTask(text.trim());
      setText("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="center">
      <div className="stream">
        {stream.length === 0 && (
          <div className="empty-state">
            {selectedSessionId
              ? "等待事件流…（WebSocket " + connection + "）"
              : "选择左侧会话，或直接在下方输入任务新建会话。"}
          </div>
        )}
        {stream.map((it) => (
          <Turn key={it.id} item={it} />
        ))}
      </div>

      <div className="composer">
        <div className="modes">
          <button className="mode agent active">
            <IconSparkle size={13} /> 智能体
          </button>
          <button className="mode">
            <IconChat size={13} /> 对话
          </button>
          <button className="mode">
            <IconLayout size={13} /> 规划
          </button>
        </div>
        <div className="composer-box">
          <textarea
            rows={2}
            placeholder="给 flipped 一个任务，或 @ 引用文件、粘贴报错让它自主修复…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="composer-bar">
            <button className="tool-btn">
              <IconAt size={13} /> 上下文
            </button>
            <button className="tool-btn" aria-label="附件">
              <IconClip size={13} />
            </button>
            <button className="tool-btn on">
              <IconPuzzle size={13} /> 工具 · MCP
            </button>
            <button className="tool-btn">
              <IconCube size={13} /> Docker <IconChevronDown size={12} />
            </button>
            <button className="tool-btn">Kimi-K2.7 <IconChevronDown size={12} /></button>
            <button className="send" aria-label="发送" onClick={submit} disabled={busy}>
              <IconSend size={15} />
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
