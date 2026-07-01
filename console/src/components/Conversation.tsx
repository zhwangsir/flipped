import type { Role, StreamItem } from "../mock";
import { stream } from "../mock";
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
              <div className="tool" key={i}>
                <span className="tool-ic">
                  <ToolIcon name={t.tool} />
                </span>
                <div className="tool-body">
                  <div className="tool-sum">{t.summary}</div>
                  {t.detail && <div className="tool-det">{t.detail}</div>}
                </div>
                <span className={"tool-status " + t.status}>
                  {t.status === "ok" && <IconCheck size={11} />}
                  {t.status === "ok" ? "完成" : t.status}
                </span>
              </div>
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

export function Conversation() {
  return (
    <section className="center">
      <div className="stream">
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
          <textarea rows={2} placeholder="给 flipped 一个任务，或 @ 引用文件、粘贴报错让它自主修复…" />
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
            <button className="tool-btn">
              Kimi-K2.7 <IconChevronDown size={12} />
            </button>
            <button className="send" aria-label="发送">
              <IconSend size={15} />
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
