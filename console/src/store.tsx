import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import type {
  Session,
  StreamItem,
  ApiEvent,
  SessionStatus,
  ApprovalInfo,
  ToolChild,
  TerminalBlock,
  BrowserView,
  ChangedFile,
  Metrics,
} from './types';
import { eventToStreamItem } from './types';
import {
  fetchSessions,
  createSession as apiCreateSession,
  createTask as apiCreateTask,
  deleteSession as apiDeleteSession,
  cancelTask as apiCancelTask,
  fetchMetrics,
  connectEvents,
} from './api';

export type ConnectionState = 'idle' | 'connecting' | 'connected' | 'error';

interface AppState {
  sessions: Session[];
  selectedSessionId: string | null;
  stream: StreamItem[];
  connection: ConnectionState;
  error?: string;
  sessionStatus: SessionStatus | null;
  progress: number;
  errorCount: number;
  lastError: string | null;
  approvalPending: ApprovalInfo | null;
  terminalBlocks: TerminalBlock[];
  browserView: BrowserView | null;
  changedFiles: ChangedFile[];
  metrics: Metrics | null;
  selectSession: (id: string) => void;
  createSession: (title?: string) => Promise<string>;
  deleteSession: (id: string) => Promise<void>;
  cancelTask: () => Promise<void>;
  sendTask: (description: string) => Promise<void>;
  sendApproval: (decision: string, reason?: string) => void;
  refreshSessions: () => Promise<void>;
}

const AppContext = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [stream, setStream] = useState<StreamItem[]>([]);
  const [connection, setConnection] = useState<ConnectionState>('idle');
  const [error, setError] = useState<string | undefined>();
  const [sessionStatus, setSessionStatus] = useState<SessionStatus | null>(null);
  const [progress, setProgress] = useState(0);
  const [errorCount, setErrorCount] = useState(0);
  const [lastError, setLastError] = useState<string | null>(null);
  const [approvalPending, setApprovalPending] = useState<ApprovalInfo | null>(null);
  const [terminalBlocks, setTerminalBlocks] = useState<TerminalBlock[]>([]);
  const [browserView, setBrowserView] = useState<BrowserView | null>(null);
  const [changedFiles, setChangedFiles] = useState<ChangedFile[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const wsRef = useRef<{ close: () => void; send: (msg: unknown) => void } | null>(null);

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

  // M6.3 — 轮询性能指标
  useEffect(() => {
    let alive = true;
    const tick = () =>
      fetchMetrics()
        .then((m) => alive && setMetrics(m))
        .catch(() => {});
    tick();
    const id = setInterval(tick, 4000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const selectSession = useCallback((id: string) => {
    setSelectedSessionId(id);
  }, []);

  const createSession = useCallback(async (title = '新任务') => {
    const s = await apiCreateSession(title);
    setSessions((prev) => [s, ...prev]);
    setSelectedSessionId(s.id);
    return s.id;
  }, []);

  const deleteSession = useCallback(async (id: string) => {
    await apiDeleteSession(id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
    setSelectedSessionId((prev) => (prev === id ? null : prev));
  }, []);

  const cancelTask = useCallback(async () => {
    if (selectedSessionId) await apiCancelTask(selectedSessionId);
  }, [selectedSessionId]);

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

  const sendApproval = useCallback((decision: string, reason = '') => {
    wsRef.current?.send({ type: 'approval_result', decision, reason });
  }, []);

  useEffect(() => {
    if (!selectedSessionId) {
      setStream([]);
      setConnection('idle');
      setSessionStatus(null);
      setProgress(0);
      setErrorCount(0);
      setLastError(null);
      setApprovalPending(null);
      setTerminalBlocks([]);
      setBrowserView(null);
      setChangedFiles([]);
      return;
    }

    setConnection('connecting');
    setStream([]);
    setError(undefined);
    setSessionStatus(null);
    setProgress(0);
    setErrorCount(0);
    setLastError(null);
    setApprovalPending(null);
    setTerminalBlocks([]);
    setBrowserView(null);
    setChangedFiles([]);

    const appendEvent = (ev: ApiEvent) => {
      // M6.1 — 从事件流派生 ContextPanel 的真实上下文数据
      if (ev.type === 'terminal') {
        setTerminalBlocks((prev) => [
          ...prev,
          { command: ev.payload.command || '', output: ev.payload.output || '', exit: ev.payload.exit_code },
        ]);
      } else if (ev.type === 'browser') {
        setBrowserView({ url: ev.payload.url, title: ev.payload.title, screenshot: ev.payload.screenshot });
      } else if (ev.type === 'file_change') {
        setChangedFiles((prev) => [
          ...prev.filter((f) => f.path !== ev.payload.path),
          { path: ev.payload.path, change: ev.payload.change || 'mod', language: ev.payload.language },
        ]);
      }

      if (ev.type === 'status') {
        const st = ev.payload.status as SessionStatus;
        const pr = (ev.payload.progress as number) ?? 0;
        setSessionStatus(st);
        setProgress(pr);
        setSessions((prev) =>
          prev.map((s) => (s.id === ev.session_id ? { ...s, status: st } : s))
        );
        return;
      }
      if (ev.type === 'error') {
        setErrorCount((c) => c + 1);
        setLastError(ev.payload.message);
      }
      if (ev.type === 'approval_request') {
        setApprovalPending({
          id: ev.id,
          action: ev.payload.action,
          reason: ev.payload.reason,
          risk: ev.payload.risk,
        });
        return;
      }
      if (ev.type === 'approval_result') {
        setApprovalPending(null);
        setStream((prev) => {
          const item = eventToStreamItem(ev);
          return item ? [...prev, item] : prev;
        });
        return;
      }
      if (ev.type === 'tool_result') {
        setStream((prev) => {
          const tool = ev.payload?.tool as string;
          for (let i = prev.length - 1; i >= 0; i--) {
            const item = prev[i];
            if (item.tools && item.tools.some((t) => t.tool === tool && t.status === 'running')) {
              const updated = [...prev];
              updated[i] = {
                ...item,
                tools: item.tools.map((t) =>
                  t.tool === tool
                    ? { ...t, status: ev.payload?.status || 'ok', detail: ev.payload?.summary || t.detail }
                    : t
                ),
              };
              return updated;
            }
          }
          const item = eventToStreamItem(ev);
          return item ? [...prev, item] : prev;
        });
        return;
      }
      if (ev.type === 'file_change' || ev.type === 'terminal' || ev.type === 'browser') {
        setStream((prev) => {
          for (let i = prev.length - 1; i >= 0; i--) {
            const item = prev[i];
            if (item.tools && item.tools.some((t) => t.status === 'running')) {
              const updated = [...prev];
              const toolIndex = item.tools.findIndex((t) => t.status === 'running');
              const tool = item.tools[toolIndex];
              const childText =
                ev.type === 'file_change'
                  ? `文件: ${ev.payload.path} (${ev.payload.change || 'mod'})`
                  : ev.type === 'terminal'
                  ? `$ ${ev.payload.command || ''}\n${ev.payload.output || ''}`
                  : `浏览器: ${ev.payload.url}${ev.payload.title ? ` (${ev.payload.title})` : ''}`;
              const child: ToolChild = { type: ev.type as ToolChild['type'], text: childText };
              const newTool = { ...tool, children: [...(tool.children || []), child] };
              updated[i] = { ...item, tools: item.tools.map((t, idx) => (idx === toolIndex ? newTool : t)) };
              return updated;
            }
          }
          const item = eventToStreamItem(ev);
          return item ? [...prev, item] : prev;
        });
        return;
      }
      setStream((prev) => {
        const item = eventToStreamItem(ev);
        return item ? [...prev, item] : prev;
      });
    };

    const ws = connectEvents(selectedSessionId, {
      onOpen: () => setConnection('connected'),
      onClose: () => setConnection('idle'),
      onError: () => {
        setConnection('error');
        setError('WebSocket 连接失败');
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
        sessionStatus,
        progress,
        errorCount,
        lastError,
        approvalPending,
        terminalBlocks,
        browserView,
        changedFiles,
        metrics,
        selectSession,
        createSession,
        deleteSession,
        cancelTask,
        sendTask,
        sendApproval,
        refreshSessions,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within <AppProvider>');
  return ctx;
}
