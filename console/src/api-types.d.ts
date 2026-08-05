/**
 * GENERATED FILE — 请勿手改。
 * 来源: http://127.0.0.1:8194/openapi.json
 * 生成: node scripts/gen-api-types.mjs  (M136-B3, 零依赖)
 * 重新生成前需先启动 flipped 后端。
 */

/* eslint-disable */
export interface AssistantTurn {
  "role": string;
  "event_id"?: string | null;
  "refs"?: Record<string, unknown>[] | null;
  "attachments"?: Record<string, unknown>[] | null;
  "text"?: string | null;
  "tools"?: Record<string, unknown>[];
  "verdict"?: Record<string, unknown> | null;
  "approval"?: Record<string, unknown> | null;
  "usage"?: Record<string, number> | null;
  "goal"?: Record<string, unknown> | null;
  "created_at": string;
}

export interface BotChannelStatusEntry {
  "platform": string;
  "enabled": boolean;
  "configured": boolean;
  "inbound_count": number;
  "outbound_count": number;
  "error_count": number;
  "last_inbound_at": number | null;
  "last_outbound_at": number | null;
  "last_error": string;
}

export interface BotChannelsResponse {
  "channels": BotChannelStatusEntry[];
}

export interface BotTestRequest {
  "text": string;
}

export interface BotTestResponse {
  "ok": boolean;
  "error"?: string;
}

export interface BotWebhookResponse {
  "ok": boolean;
  "handled": boolean;
}

export interface BrowserRenderRequest {
  /** 要渲染的目标 URL（仅 http/https） */
  "url": string;
}

export interface CallToolRequest {
  "arguments"?: Record<string, unknown>;
  "session_id"?: string | null;
}

export interface CallToolResponse {
  "ok": boolean;
  "tool": string;
  "accepted"?: boolean;
  "session_id"?: string | null;
  "result"?: Record<string, unknown> | null;
  "error"?: string | null;
}

export interface CommitMessageResponse {
  "message": string;
  "model": string;
  "files_count": number;
  "note"?: string | null;
}

export interface CompactResponse {
  "ok": boolean;
  "session_id": string;
  "summary": string;
}

export interface CreateFactoryRequest {
  /** 高层产品目标 */
  "product_goal": string;
  /** 工作目录（默认=活动项目沙盒路径） */
  "cwd"?: string | null;
  /** 最大任务数 */
  "max_tasks"?: number;
}

export interface CreateGoalRequest {
  "objective": string;
  "mode"?: string | null;
  "model"?: string | null;
  "max_iterations"?: number | null;
  "verify_cmd"?: string[] | null;
}

export interface CreateGoalResponse {
  "task_id": string;
  "session_id": string;
  "objective": string;
  "max_iterations": number;
}

export interface CreateSessionRequest {
  "title"?: string;
  "mode"?: string;
  "cwd"?: string | null;
  "model_alias"?: string;
}

export interface DecisionRequest {
  "scope"?: "once" | "always";
}

export interface DecisionResponse {
  "ok": boolean;
  "session_id": string;
  "decision": string;
}

export interface EditMessageRequest {
  "text": string;
  "restore_files"?: boolean;
  "mode"?: string | null;
}

export interface EditMessageResponse {
  "ok": boolean;
  "session_id": string;
  "task_id": string;
  "truncated": number;
  "restored"?: boolean;
  "deleted"?: string[];
}

export interface EditUndoResponse {
  "ok": boolean;
  "session_id": string;
  "restored": number;
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

export type EventType = "message" | "tool_call" | "tool_result" | "file_change" | "terminal" | "browser" | "status" | "plan" | "checkpoint" | "snapshot" | "usage" | "approval_request" | "approval_result" | "error" | "rca" | "verifier_verdict" | "token" | "goal";

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

export interface GoalInfoResponse {
  "status"?: string | null;
  "objective"?: string | null;
  "iteration"?: number | null;
  "max_iterations"?: number | null;
}

export interface HTTPValidationError {
  "detail"?: ValidationError[];
}

export interface HealthResponse {
  "ok": boolean;
  "proxy": Record<string, unknown>;
  "error"?: string | null;
}

export interface ImageAttachmentIn {
  "name": string;
  "media_type": string;
  "data_base64": string;
}

export interface MessageResponse {
  "task_id": string;
  "session_id": string;
}

export interface MetricsResponse {
  "llm"?: Record<string, unknown>;
  "context"?: Record<string, unknown>;
}

export interface ProjectMapInfo {
  "markdown": string;
  "generated_at": string;
  "stale": boolean;
  "from_cache": boolean;
  "stack"?: string[];
}

export interface ProjectMapResponse {
  "map"?: ProjectMapInfo | null;
  "needs_project"?: boolean;
}

export interface RemoteDecisionRequest {
  "decision": "approve" | "reject";
}

export interface RemoteIssueRequest {
  "session_id"?: string | null;
}

export interface RemoteIssueResponse {
  "token": string;
  "url": string;
  "qr_url": string;
  "session_id": string;
  "session_title": string;
  "expires_at": number;
  "host_note": string;
}

export interface RemoteMessageRequest {
  "text": string;
}

export interface RemoteRevokeResponse {
  "ok": boolean;
}

export interface RemoteStateResponse {
  "session_id": string;
  "title": string;
  "mode": string;
  "status": string;
  "pending_approval": Record<string, string> | null;
  "turns": Record<string, string>[];
}

export interface RevertHunkRequest {
  "path": string;
  "hunk_index": number;
}

export interface RevertHunkResponse {
  "ok": boolean;
  "path": string;
  "hunk_index": number;
  "action": string;
}

export interface RevertRequest {
  "path": string;
}

export interface RevertResponse {
  "ok": boolean;
  "path": string;
  "action": string;
}

export interface ReviewFinding {
  "path": string;
  "line"?: number | null;
  "severity": string;
  "message": string;
  "suggestion"?: string | null;
}

export interface ReviewHistoryEntry {
  "id": string;
  "ts": string;
  "project": string;
  "model": string;
  "files_reviewed": number;
  "findings_count": number;
}

export interface ReviewRecord {
  "id": string;
  "ts": string;
  "project": string;
  "model": string;
  "files_reviewed": number;
  "findings_count": number;
  "findings": ReviewFinding[];
}

export interface ReviewRequest {
  "model"?: string | null;
}

export interface ReviewResponse {
  "findings": ReviewFinding[];
  "files_reviewed": number;
  "model": string;
  "note"?: string | null;
  "review_id"?: string | null;
}

export interface ReviewsHistoryResponse {
  "reviews": ReviewHistoryEntry[];
}

export type Role = "user" | "supervisor" | "worker" | "overseer" | "verify" | "system";

export interface RulesPutRequest {
  "content": string;
}

export interface RulesResponse {
  "files": string[];
  "markdown": string;
  "total_chars": number;
  "rules_content": string;
  "needs_project"?: boolean;
}

export interface ScheduledTaskResponse {
  "id": string;
  "title": string;
  "prompt": string;
  "mode": string;
  "model": string;
  "kind": string;
  "run_at"?: string | null;
  "every_minutes"?: number | null;
  "cron"?: string | null;
  "enabled": boolean;
  "next_run_at"?: string | null;
  "last_run_at"?: string | null;
  "last_status"?: string | null;
  "last_session_id"?: string | null;
  "run_count": number;
  "created_at": string;
}

export interface SendMessageRequest {
  "text": string;
  "mode"?: string | null;
  "model"?: string | null;
  "orchestrator"?: Record<string, unknown> | null;
  "images"?: ImageAttachmentIn[] | null;
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

export interface TaskCreateRequest {
  "title": string;
  "prompt": string;
  "mode"?: string;
  "model"?: string;
  "kind"?: "once" | "interval" | "cron";
  "run_at"?: string | null;
  "every_minutes"?: number | null;
  "cron"?: string | null;
}

export interface TaskDeleteResponse {
  "ok": boolean;
  "id": string;
}

export interface TaskPatchRequest {
  "title"?: string | null;
  "prompt"?: string | null;
  "mode"?: string | null;
  "model"?: string | null;
  "kind"?: "once" | "interval" | "cron" | null;
  "run_at"?: string | null;
  "every_minutes"?: number | null;
  "cron"?: string | null;
}

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

export interface ToolListResponse {
  "tools": ToolSpec[];
}

export interface ToolSpec {
  "name": string;
  "description": string;
  "inputSchema": Record<string, unknown>;
}

export interface UndoResponse {
  "ok": boolean;
  "session_id": string;
  "restored": boolean;
  "deleted"?: string[];
}

export interface ValidationError {
  "loc": (string | number)[];
  "msg": string;
  "type": string;
}

export interface WorkerRule {
  "id": string;
  "text": string;
  "scope"?: "worker" | "all";
  "source"?: "manual" | "auto";
  "enabled"?: boolean;
  "priority"?: number;
  "created_at"?: number;
}

export interface WorkerRuleAutoGenRequest {
  "failure_texts"?: string[] | null;
}

export interface WorkerRuleAutoGenResponse {
  "added": WorkerRule[];
  "candidates": number;
  "llm_used"?: boolean;
}

export interface WorkerRuleCreateRequest {
  "text": string;
  "scope"?: "worker" | "all";
  "priority"?: number | null;
}

export interface WorkerRuleDeleteResponse {
  "ok": boolean;
}

export interface WorkerRuleRollbackRequest {
  "version": number;
}

export interface WorkerRuleRollbackResponse {
  "ok": boolean;
  "version": number;
}

export interface WorkerRuleStatEntry {
  "applied": number;
  "success": number;
  "failure": number;
  "success_rate"?: number | null;
}

export interface WorkerRuleStatsResponse {
  "stats": Record<string, WorkerRuleStatEntry>;
  "total_runs": number;
  "semantics"?: string;
}

export interface WorkerRuleToggleRequest {
  "enabled": boolean;
}

export interface WorkerRuleUpdateRequest {
  "text"?: string | null;
  "priority"?: number | null;
  "scope"?: "worker" | "all" | null;
}

export interface WorkerRuleVersionEntry {
  "version": number;
  "ts": number;
  "action": string;
  "detail": string;
  "rule_count": number;
}

export interface WorkerRuleVersionsResponse {
  "versions": WorkerRuleVersionEntry[];
}

export interface WorkerRulesResponse {
  "version": number;
  "rules": WorkerRule[];
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
  "/api/v1/assistant/attachments/{session_id}/{filename}": {
    get: {
      params: {
        "session_id": string;
        "filename": string;
      };
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/assistant/sessions/{session_id}/approve": {
    post: {
      params: {
        "session_id": string;
      };
      requestBody: DecisionRequest | null;
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
      requestBody: DecisionRequest | null;
      responses: {
        200: DecisionResponse;
      };
    };
  };
  "/api/v1/assistant/sessions/{session_id}/compact": {
    post: {
      params: {
        "session_id": string;
      };
      requestBody: null;
      responses: {
        200: CompactResponse;
      };
    };
  };
  "/api/v1/assistant/sessions/{session_id}/undo": {
    post: {
      params: {
        "session_id": string;
      };
      requestBody: null;
      responses: {
        200: UndoResponse;
      };
    };
  };
  "/api/v1/assistant/sessions/{session_id}/messages/{event_id}/edit": {
    post: {
      params: {
        "session_id": string;
        "event_id": string;
      };
      requestBody: EditMessageRequest;
      responses: {
        200: EditMessageResponse;
      };
    };
  };
  "/api/v1/assistant/sessions/{session_id}/edit/undo": {
    post: {
      params: {
        "session_id": string;
      };
      requestBody: null;
      responses: {
        200: EditUndoResponse;
      };
    };
  };
  "/api/v1/assistant/sessions/{session_id}/goal": {
    get: {
      params: {
        "session_id": string;
      };
      requestBody: null;
      responses: {
        200: GoalInfoResponse;
      };
    };
    post: {
      params: {
        "session_id": string;
      };
      requestBody: CreateGoalRequest;
      responses: {
        200: CreateGoalResponse;
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
  "/api/v1/mcp/tools": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: ToolListResponse;
      };
    };
  };
  "/api/v1/mcp/tools/{name}/call": {
    post: {
      params: {
        "name": string;
      };
      requestBody: CallToolRequest;
      responses: {
        200: CallToolResponse;
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
  "/api/v1/project/revert": {
    post: {
      params?: Record<string, never>;
      requestBody: RevertRequest;
      responses: {
        200: RevertResponse;
      };
    };
  };
  "/api/v1/project/revert-hunk": {
    post: {
      params?: Record<string, never>;
      requestBody: RevertHunkRequest;
      responses: {
        200: RevertHunkResponse;
      };
    };
  };
  "/api/v1/project/review": {
    post: {
      params?: Record<string, never>;
      requestBody: ReviewRequest;
      responses: {
        200: ReviewResponse;
      };
    };
  };
  "/api/v1/project/reviews": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: ReviewsHistoryResponse;
      };
    };
  };
  "/api/v1/project/reviews/{review_id}": {
    get: {
      params: {
        "review_id": string;
      };
      requestBody: null;
      responses: {
        200: ReviewRecord;
      };
    };
  };
  "/api/v1/project/commit_message": {
    post: {
      params?: Record<string, never>;
      requestBody: ReviewRequest;
      responses: {
        200: CommitMessageResponse;
      };
    };
  };
  "/api/v1/project/rules": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: RulesResponse;
      };
    };
    put: {
      params?: Record<string, never>;
      requestBody: RulesPutRequest;
      responses: {
        200: RulesResponse;
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
  "/api/v1/project/map": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: ProjectMapResponse;
      };
    };
  };
  "/api/v1/project/map/regenerate": {
    post: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: ProjectMapResponse;
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
  "/api/v1/tasks": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: ScheduledTaskResponse[];
      };
    };
    post: {
      params?: Record<string, never>;
      requestBody: TaskCreateRequest;
      responses: {
        201: ScheduledTaskResponse;
      };
    };
  };
  "/api/v1/tasks/{task_id}": {
    delete: {
      params: {
        "task_id": string;
      };
      requestBody: null;
      responses: {
        200: TaskDeleteResponse;
      };
    };
    patch: {
      params: {
        "task_id": string;
      };
      requestBody: TaskPatchRequest;
      responses: {
        200: ScheduledTaskResponse;
      };
    };
  };
  "/api/v1/tasks/{task_id}/toggle": {
    post: {
      params: {
        "task_id": string;
        "enabled": boolean;
      };
      requestBody: null;
      responses: {
        200: ScheduledTaskResponse;
      };
    };
  };
  "/api/v1/remote/sessions": {
    post: {
      params?: Record<string, never>;
      requestBody: RemoteIssueRequest;
      responses: {
        200: RemoteIssueResponse;
      };
    };
  };
  "/api/v1/remote/{token}/state": {
    get: {
      params: {
        "token": string;
      };
      requestBody: null;
      responses: {
        200: RemoteStateResponse;
      };
    };
  };
  "/api/v1/remote/{token}/message": {
    post: {
      params: {
        "token": string;
      };
      requestBody: RemoteMessageRequest;
      responses: {
        200: MessageResponse;
      };
    };
  };
  "/api/v1/remote/{token}/decision": {
    post: {
      params: {
        "token": string;
      };
      requestBody: RemoteDecisionRequest;
      responses: {
        200: DecisionResponse;
      };
    };
  };
  "/remote/{token}": {
    get: {
      params: {
        "token": string;
      };
      requestBody: null;
      responses: {
        200: string;
      };
    };
  };
  "/api/v1/remote/{token}/qr.svg": {
    get: {
      params: {
        "token": string;
      };
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/remote/{token}": {
    delete: {
      params: {
        "token": string;
      };
      requestBody: null;
      responses: {
        200: RemoteRevokeResponse;
      };
    };
  };
  "/api/v1/bot/telegram/webhook": {
    post: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: BotWebhookResponse;
      };
    };
  };
  "/api/v1/bot/wecom/callback": {
    get: {
      params: {
        "msg_signature": string;
        "timestamp": string;
        "nonce": string;
        "echostr": string;
      };
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
    post: {
      params: {
        "msg_signature": string;
        "timestamp": string;
        "nonce": string;
      };
      requestBody: null;
      responses: {
        200: Record<string, unknown>;
      };
    };
  };
  "/api/v1/bot/channels": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: BotChannelsResponse;
      };
    };
  };
  "/api/v1/bot/channels/{platform}/test": {
    post: {
      params: {
        "platform": string;
      };
      requestBody: BotTestRequest;
      responses: {
        200: BotTestResponse;
      };
    };
  };
  "/api/v1/worker/rules": {
    get: {
      params: {
        "enabled"?: boolean | null;
        "sort"?: "insertion" | "priority";
      };
      requestBody: null;
      responses: {
        200: WorkerRulesResponse;
      };
    };
    post: {
      params?: Record<string, never>;
      requestBody: WorkerRuleCreateRequest;
      responses: {
        201: WorkerRule;
      };
    };
  };
  "/api/v1/worker/rules/{rule_id}": {
    put: {
      params: {
        "rule_id": string;
      };
      requestBody: WorkerRuleUpdateRequest;
      responses: {
        200: WorkerRule;
      };
    };
    delete: {
      params: {
        "rule_id": string;
      };
      requestBody: null;
      responses: {
        200: WorkerRuleDeleteResponse;
      };
    };
  };
  "/api/v1/worker/rules/{rule_id}/toggle": {
    post: {
      params: {
        "rule_id": string;
      };
      requestBody: WorkerRuleToggleRequest;
      responses: {
        200: WorkerRule;
      };
    };
  };
  "/api/v1/worker/rules/versions": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: WorkerRuleVersionsResponse;
      };
    };
  };
  "/api/v1/worker/rules/rollback": {
    post: {
      params?: Record<string, never>;
      requestBody: WorkerRuleRollbackRequest;
      responses: {
        200: WorkerRuleRollbackResponse;
      };
    };
  };
  "/api/v1/worker/rules/auto-generate": {
    post: {
      params?: Record<string, never>;
      requestBody: WorkerRuleAutoGenRequest | null;
      responses: {
        200: WorkerRuleAutoGenResponse;
      };
    };
  };
  "/api/v1/worker/rules/stats": {
    get: {
      params?: Record<string, never>;
      requestBody: null;
      responses: {
        200: WorkerRuleStatsResponse;
      };
    };
  };
}
