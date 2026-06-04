export type ModelTier = "local" | "flash" | "plus" | "max";

export interface RequestEnvelope {
  request_id?: string;
  workspace_id: string;
  project_id: string;
  user_id: string;
  prompt: string;
  metadata?: Record<string, unknown>;
}

export interface ContextSnippet {
  source: string;
  content: string;
  score: number;
  scores?: Record<string, number>;
}

export interface RetrievalAssembled {
  query?: string;
  relevant_systems?: string[];
  dependencies?: string[];
  architecture_notes?: string[];
  risks?: string[];
  compression?: {
    selected_count: number;
    dropped_count: number;
    max_chars: number;
    used_chars: number;
  };
  context_packet?: Array<{
    source: string;
    type: string;
    score: number;
    hot?: boolean;
    dependencies?: string[];
  }>;
}

export interface ContextAssembleResponse {
  packet: {
    snippets: ContextSnippet[];
    provenance: string[];
  };
  retrieval: {
    query: string;
    took_ms: number;
    assembled: RetrievalAssembled;
  };
}

export interface ChatResponse {
  request_id: string;
  answer: string;
  confidence: number;
  trace_id: string;
  route: {
    provider: string;
    model_name: string;
    reason: string;
    selected_tier: ModelTier;
    estimated_cost_usd: number;
  };
  context_sources: string[];
}

export type FeedbackVerdict = "correct" | "partial" | "incorrect";

export type FeedbackIssue =
  | "context_bad"
  | "xml_missing"
  | "hallucination"
  | "retrieval_incorrect"
  | "compression_bad"
  | "architectural_loss";

export interface CognitiveFeedbackCreateRequest {
  workspace_id: string;
  project_id: string;
  user_id: string;
  query: string;
  request_id?: string;
  verdict: FeedbackVerdict;
  issues: FeedbackIssue[];
  notes?: string;
}

export interface DiagnosticsResponse {
  failure_counts: Record<string, number>;
  recommendations: string[];
  report_file?: string;
}

export type ActionType = "create_file" | "update_file" | "patch_file" | "delete_file";
export type ActionRisk = "low" | "medium" | "high" | "critical";
export type ValidationSeverity = "warning" | "error";
export type ActionStepStatus = "planned" | "applied" | "skipped" | "failed" | "rolled_back";

export interface ActionPatchOperation {
  find: string;
  replace: string;
  replace_all: boolean;
  use_regex?: boolean;
}

export interface ActionStep {
  step_id?: string;
  type: ActionType;
  target: string;
  intent: string;
  risk?: ActionRisk;
  rationale?: string;
  patches?: ActionPatchOperation[];
  content?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ActionPlanRequest {
  plan_id?: string;
  workspace_id: string;
  project_id: string;
  user_id: string;
  prompt: string;
  metadata?: Record<string, unknown>;
  max_actions?: number;
}

export interface ActionPlan {
  plan_id: string;
  workspace_id: string;
  project_id: string;
  user_id: string;
  prompt: string;
  summary: string;
  actions: ActionStep[];
  warnings: string[];
  retrieval: Record<string, unknown>;
  generated_at: string;
}

export interface ActionValidationIssue {
  step_id: string;
  severity: ValidationSeverity;
  code: string;
  message: string;
}

export interface ActionValidationReport {
  ok: boolean;
  issues: ActionValidationIssue[];
  blocked_steps: string[];
}

export interface ActionExecutionOptions {
  dry_run: boolean;
  allow_high_risk: boolean;
  auto_rollback_on_error: boolean;
  run_feedback_loop: boolean;
}

export interface ActionExecuteRequest {
  workspace_id: string;
  project_id: string;
  user_id: string;
  plan: ActionPlan;
  options: ActionExecutionOptions;
}

export interface ActionStepResult {
  step_id: string;
  target: string;
  status: ActionStepStatus;
  message: string;
  backup_path?: string | null;
  bytes_written: number;
}

export interface ActionExecutionReport {
  execution_id: string;
  plan_id: string;
  dry_run: boolean;
  applied: number;
  skipped: number;
  failed: number;
  changed_files: string[];
  validation: ActionValidationReport;
  results: ActionStepResult[];
  feedback_notes: string[];
  rollback_performed: boolean;
  rollback_restored_files: number;
  created_at: string;
}

export interface ActionRollbackRequest {
  workspace_id: string;
  project_id: string;
  user_id: string;
  execution_id: string;
}

export interface ActionRollbackReport {
  execution_id: string;
  restored_files: number;
  removed_files: number;
  skipped_files: number;
  notes: string[];
}

export type OrchestratorMode = "manual" | "autopilot";
export type OrchestratorDecisionState = "auto_execute" | "requires_approval" | "blocked";

export interface OrchestratorDecision {
  state: OrchestratorDecisionState;
  highest_risk: ActionRisk;
  execute_now: boolean;
  reason: string;
}

export interface OrchestratorRunRequest {
  run_id?: string;
  workspace_id: string;
  project_id: string;
  user_id: string;
  intent: string;
  mode: OrchestratorMode;
  max_iterations: number;
  project_path?: string;
  dry_run: boolean;
  auto_execute_low_risk: boolean;
  auto_execute_medium_risk: boolean;
  allow_high_risk: boolean;
  block_critical_risk: boolean;
  evaluation_limit?: number;
  run_reflection: boolean;
  metadata?: Record<string, unknown>;
}

export interface OrchestratorIterationReport {
  iteration: number;
  plan: ActionPlan;
  decision: OrchestratorDecision;
  execution?: ActionExecutionReport | null;
  ingestion: Record<string, unknown>;
  context_refresh: Record<string, unknown>;
  evaluation: Record<string, unknown>;
  reflection: Record<string, unknown>;
  notes: string[];
}

export interface OrchestratorRunReport {
  run_id: string;
  workspace_id: string;
  project_id: string;
  user_id: string;
  mode: OrchestratorMode;
  final_state: OrchestratorDecisionState;
  iterations: OrchestratorIterationReport[];
  notes: string[];
  created_at: string;
  finished_at: string;
}
