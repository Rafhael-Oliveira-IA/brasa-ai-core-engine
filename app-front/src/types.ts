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
