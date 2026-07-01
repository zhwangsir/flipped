import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { Session, StreamItem, ApiEvent } from "./types";
import { eventToStreamItem } from "./types";
import { fetchSessions, createSession as apiCreateSession, createTask as apiCreateTask, connectEvents } from "./api";

export type ConnectionState = "idle" | "connecting" | "connected" | "error";

interface AppState {
  sessions: Session[];
  selectedSessionId: string | null;
  stream: StreamItem[];
  connection: ConnectionState;
  error?: string;
  selectSession: (id: string) => void;
  createSession: (title?: string) => Promise<string>;
  sendTask: (description: string) => Promise<void>;
  refreshSessions: () => Promise<void>;
}

const AppContext = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [stream, setStream] = useState<StreamItem[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("idle");
  const [error, setError] = useState<string | undefined>();
  const wsRef = useRef<{ close: () => void } | null>(null);

  const refreshSessions = useCallback(async () => {
    try {
      const list = await fetchSessions();
      setSessions(list);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  const selectSession = useCallback((id: string) => {
    setSelectedSessionId(id);
  }, []);

  const createSession = useCallback(async (title = "新任务") => {
    const s = await apiCreateSession(title);
    setSessions((prev) => [s, ...prev]);
    setSelectedSessionId(s.id);
    return s.id;
  }, []);

  const sendTask = useCallback(
    async (description: string) => {
      let sid = selectedSessionId;
      if (!sid) {
        sid = await createSession();
      }
      await apiCreateTask(sid, description);
    },
    [selectedSessionId, createSession]
  );

  // 当选中会话变化时，连接 / 断开 WebSocket
  useEffect(() => {
    if (!selectedSessionId) {
      setStream([]);
      setConnection("idle");
      return;
    }

    setConnection("connecting");
    setStream([]);
    setError(undefined);

    const appendEvent = (ev: ApiEvent) => {
      if (ev.type === "tool_result") {
        // 尝试把 tool_result 合并到同工具的 running 条目
        setStream((prev) => {
          const tool = ev.payload?.tool as string;
          for (let i = prev.length - 1; i >= 0; i--) {
            const item = prev[i];
            if (item.tools && item.tools.some((t) => t.tool === tool && t.status === "running")) {
              const updated = [...prev];
              updated[i] = {
                ...item,
                tools: item.tools.map((t) =>
                  t.tool === tool
                    ? { ...t, status: ev.payload?.status || "ok", detail: ev.payload?.summary || t.detail }
                    : t
                ),
              };
              return updated;
            }
          }
          const item = eventToStreamItem(ev);
          return item ? [...prev, item] : prev;
        });
      } else {
        setStream((prev) => {
          const item = eventToStreamItem(ev);
          return item ? [...prev, item] : prev;
        });
      }
    };

    const ws = connectEvents(selectedSessionId, {
      onOpen: () => setConnection("connected"),
      onClose: () => setConnection("idle"),
      onError: () => {
        setConnection("error");
        setError("WebSocket 连接失败");
      },
      onMessage: appendEvent,
    });

    wsRef.current = ws;
    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [selectedSessionId]);

  return (
    <AppContext.Provider
      value={{
        sessions,
        selectedSessionId,
        stream,
        connection,
        error,
        selectSession,
        createSession,
        sendTask,
        refreshSessions,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within <AppProvider>");
  return ctx;
}
