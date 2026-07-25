/**
 * GENERATED FILE — 请勿手改。
 * 来源: http://127.0.0.1:8151/openapi.json
 * 生成: node scripts/gen-api-types.mjs  (M136-B3, 零依赖)
 * 重新生成前需先启动 flipped 后端。
 */

/* eslint-disable */
export interface AssistantTurn {
  "role": string;
  "text"?: string | null;
  "tools"?: Record<string, unknown>[];
  "verdict"?: Record<string, unknown> | null;
  "approval"?: Record<string, unknown> | null;
  "created_at": string;
}

export interface BrowserRenderRequest {
  /** 要渲染的目标 URL（仅 http/https） */
  "url": string;
}

export interface CreateFactoryRequest {
  /** 高层产品目标 */
  "product_goal": string;
  /** 工作目录（默认=活动项目沙盒路径） */
  "cwd"?: string | null;
  /** 最大任务数 */
  "max_tasks"?: number;
}

export interface CreateSessionRequest {
  "title"?: string;
  "mode"?: string;
  "cwd"?: string | null;
  "model_alias"?: string;
}

export interface DecisionResponse {
  "ok": boolean;
  "session_id": string;
  "decision": string;
}

export interface Event {
  "id": string;
  "session_id": string;
  "type": EventType;
  "agent"?: Role | null;
  "payload"?: Record<string, unknown>;
  "parent_id"?: string | null;
  "created_at"?: string;
}

export type EventType = "message" | "tool_call" | "tool_result" | "file_change" | "terminal" | "browser" | "status" | "plan" | "checkpoint" | "approval_request" | "approval_result" | "error" | "rca" | "verifier_verdict";

export interface FactorySummary {
  "factory_id": string;
  "product_goal": string;
  "cwd": string;
  "status": string;
  "total_tasks": number;
  "completed": number;
  "failed": number;
  "current_task_id"?: string | null;
  "iteration_count": number;
  "max_tasks": number;
  "created_at": string;
  "updated_at": string;
}

export interface HTTPValidationError {
  "detail"?: ValidationError[];
}

export interface HealthResponse {
  "ok": boolean;
  "proxy": Record<string, unknown>;
  "error"?: string | null;
}

export interface MessageResponse {
  "task_id": string;
  "session_id": string;
}

export interface MetricsResponse {
  "llm"?: Record<string, unknown>;
  "context"?: Record<string, unknown>;
}

export type Role = "user" | "supervisor" | "worker" | "overseer" | "verify" | "system";

export interface SendMessageRequest {
  "text": string;
  "mode"?: string | null;
  "model"?: string | null;
  "orchestrator"?: Record<string, unknown> | null;
}

export interface Session {
  "id": string;
  "title": string;
  "status": SessionStatus;
  "model"?: string;
  "mode"?: string;
  "project"?: string | null;
  "project_name"?: string | null;
  "goal"?: string | null;
  "verify_cmd"?: string[];
  "cwd"?: string;
  "checkpoint_db_path"?: string | null;
  "created_at"?: string;
  "updated_at"?: string;
}

export type SessionStatus = "idle" | "running" | "paused" | "done" | "review" | "error";

export interface TaskRequest {
  /** 本次任务描述 */
  "description": string;
  /** 额外上下文，透传给执行器 */
  "context"?: Record<string, unknown>;
}

export interface TaskResponse {
  "task_id": string;
  "session_id": string;
  "status": string;
}

export interface ValidationError {
  "loc": (string | number)[];
  "msg": string;
  "type": string;
}

export interface paths {
  "/api/v1/factories": {
    get: {
      params: {
        "status"?: string | null;
        "limit"?: number;
        "include_test"?: boolean;
      };
      requestBody: null;
      responses: {
        200: FactorySummary[];
      };
    };
    post: {
      params?: Record<string, never>;
      requestBody: CreateFactoryRequest;
      responses: {
        200: FactorySummary;
      };
    };
  };
  "/api/v1/factories/{factory_id}": {
    get: {
      params: {
        "factory_id": string;
      };
      requestBody: null;
      responses: {
        200: FactorySummary;
      };
    };
  };
  "/api/v1/factories/{factory_id}/detail": {
    get: {
      params: {
        "factory_id": string;
      };
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/factories/{factory_id}/rca_history": {
    get: {
      params: {
        "factory_id": string;
      };
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/factories/{factory_id}/quality-trend": {
    get: {
      params: {
        "factory_id": string;
      };
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/factories/{factory_id}/resume": {
    post: {
      params: {
        "factory_id": string;
      };
      requestBody: null;
      responses: {
        200: FactorySummary;
      };
    };
  };
  "/api/v1/factories/{factory_id}/pause": {
    post: {
      params: {
        "factory_id": string;
      };
      requestBody: null;
      responses: {
        200: FactorySummary;
      };
    };
  };
  "/api/v1/assistant/sessions": {
    post: {
      params?: Record<string, never>;
      requestBody: CreateSessionRequest;
      responses: {
        200: Session;
      };
    };
  };
  "/api/v1/assistant/sessions/{session_id}/messages": {
    post: {
      params: {
        "session_id": string;
      };
      requestBody: SendMessageRequest;
      responses: {
        200: MessageResponse;
      };
    };
  };
  "/api/v1/assistant/sessions/{session_id}/history": {
    get: {
      params: {
        "session_id": string;
      };
      requestBody: null;
      responses: {
        200: AssistantTurn[];
      };
    };
  };
  "/api/v1/assistant/sessions/{session_id}/approve": {
    post: {
      params: {
        "session_id": string;
      };
      requestBody: null;
      responses: {
        200: DecisionResponse;
      };
    };
  };
  "/api/v1/assistant/sessions/{session_id}/reject": {
    post: {
      params: {
        "session_id": string;
      };
      requestBody: null;
      responses: {
        200: DecisionResponse;
      };
    };
  };
  "/api/v1/health": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: HealthResponse;
      };
    };
  };
  "/api/v1/metrics": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: MetricsResponse;
      };
    };
  };
  "/api/v1/rca/failure_counter": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/mcp/servers": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: Record<string, unknown>[];
      };
    };
  };
  "/api/v1/mcp/servers/{name}/toggle": {
    post: {
      params: {
        "name": string;
        "enabled": boolean;
      };
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/project/context": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/projects": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
    post: {
      params?: Record<string, never>;
      requestBody: Record<string, unknown>;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/project/open": {
    post: {
      params?: Record<string, never>;
      requestBody: Record<string, unknown>;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/project/files": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/project/reveal": {
    post: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/project/diff": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/project/verify": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/project/file": {
    get: {
      params: {
        "path": string;
      };
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/browser/render": {
    post: {
      params?: Record<string, never>;
      requestBody: BrowserRenderRequest;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/sessions": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: Session[];
      };
    };
    post: {
      params: {
        "title"?: string;
        "mode"?: string;
      };
      requestBody: null;
      responses: {
        200: Session;
      };
    };
  };
  "/api/v1/sessions/{session_id}": {
    get: {
      params: {
        "session_id": string;
      };
      requestBody: null;
      responses: {
        200: Session;
      };
    };
    delete: {
      params: {
        "session_id": string;
      };
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/sessions/{session_id}/events": {
    get: {
      params: {
        "session_id": string;
        "after_id"?: string | null;
      };
      requestBody: null;
      responses: {
        200: Event[];
      };
    };
  };
  "/api/v1/sessions/{session_id}/cancel": {
    post: {
      params: {
        "session_id": string;
      };
      requestBody: null;
      responses: {
        200: Session;
      };
    };
  };
  "/api/v1/sessions/{session_id}/tasks": {
    post: {
      params: {
        "session_id": string;
      };
      requestBody: TaskRequest;
      responses: {
        200: TaskResponse;
      };
    };
  };
  "/api/v1/sessions/{session_id}/resume": {
    post: {
      params: {
        "session_id": string;
      };
      requestBody: null;
      responses: {
        200: Session;
      };
    };
  };
}
