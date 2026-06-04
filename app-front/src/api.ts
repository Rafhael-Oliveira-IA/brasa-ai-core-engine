import {
  ActionExecuteRequest,
  ActionExecutionReport,
  ActionPlan,
  ActionPlanRequest,
  ActionRollbackReport,
  ActionRollbackRequest,
  ChatResponse,
  ContextAssembleResponse,
  CognitiveFeedbackCreateRequest,
  DiagnosticsResponse,
  OrchestratorRunReport,
  OrchestratorRunRequest,
  RequestEnvelope,
} from "./types";

const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.toString().trim() || "http://127.0.0.1:8000";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    ...init,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }

  return (await response.json()) as T;
}

export async function assembleContext(payload: RequestEnvelope): Promise<ContextAssembleResponse> {
  return requestJson<ContextAssembleResponse>("/v1/context/assemble", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function askChat(payload: RequestEnvelope): Promise<ChatResponse> {
  return requestJson<ChatResponse>("/v1/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function sendFeedback(payload: CognitiveFeedbackCreateRequest): Promise<void> {
  await requestJson("/v1/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function runDiagnostics(
  workspaceId: string,
  projectId: string,
  userId: string,
): Promise<DiagnosticsResponse> {
  const params = new URLSearchParams({
    workspace_id: workspaceId,
    project_id: projectId,
    user_id: userId,
  });
  return requestJson<DiagnosticsResponse>(`/v1/calibration/diagnostics?${params.toString()}`, {
    method: "POST",
  });
}

export async function recentTraces(limit = 20): Promise<{ items: unknown[] }> {
  return requestJson<{ items: unknown[] }>(`/v1/traces/recent?limit=${limit}`);
}

export async function planActions(payload: ActionPlanRequest): Promise<ActionPlan> {
  return requestJson<ActionPlan>("/v1/actions/plan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function executeActions(payload: ActionExecuteRequest): Promise<ActionExecutionReport> {
  return requestJson<ActionExecutionReport>("/v1/actions/execute", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function rollbackActions(payload: ActionRollbackRequest): Promise<ActionRollbackReport> {
  return requestJson<ActionRollbackReport>("/v1/actions/rollback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function runOrchestrator(payload: OrchestratorRunRequest): Promise<OrchestratorRunReport> {
  return requestJson<OrchestratorRunReport>("/v1/orchestrator/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
