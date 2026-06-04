import { useState } from "react";

import { askChat, assembleContext, recentTraces, runDiagnostics, sendFeedback } from "../api";
import {
  ChatResponse,
  ContextAssembleResponse,
  DiagnosticsResponse,
  FeedbackIssue,
  FeedbackVerdict,
  RequestEnvelope,
} from "../types";
import ContextView from "./ContextView";
import FeedbackBar from "./FeedbackBar";
import ProjectSwitcher from "./ProjectSwitcher";
import TraceViewer from "./TraceViewer";

function createRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

type ScopeProps = {
  workspaceId: string;
  projectId: string;
  userId: string;
  onWorkspaceIdChange: (value: string) => void;
  onProjectIdChange: (value: string) => void;
  onUserIdChange: (value: string) => void;
};

type FeedbackAction = {
  verdict: FeedbackVerdict;
  issues: FeedbackIssue[];
};

export default function ChatWorkbench(props: ScopeProps) {
  const [prompt, setPrompt] = useState("");
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [context, setContext] = useState<ContextAssembleResponse | null>(null);
  const [chat, setChat] = useState<ChatResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResponse | null>(null);
  const [traces, setTraces] = useState<unknown[]>([]);

  async function onAsk() {
    if (!prompt.trim()) return;

    setLoading(true);
    setError("");
    setNotice("");
    setAnswer("");

    const requestId = createRequestId();
    const payload: RequestEnvelope = {
      request_id: requestId,
      workspace_id: props.workspaceId,
      project_id: props.projectId,
      user_id: props.userId,
      prompt,
      metadata: { source: "app-front" },
    };

    try {
      const assembled = await assembleContext(payload);
      setContext(assembled);

      const chatResponse = await askChat(payload);
      setChat(chatResponse);
      setAnswer(chatResponse.answer);

      const tracesResponse = await recentTraces(20);
      setTraces(tracesResponse.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function onFeedback(action: FeedbackAction) {
    if (!prompt.trim()) return;

    try {
      await sendFeedback({
        workspace_id: props.workspaceId,
        project_id: props.projectId,
        user_id: props.userId,
        query: prompt,
        request_id: chat?.request_id,
        verdict: action.verdict,
        issues: action.issues,
      });
      setNotice("Feedback enviado com sucesso.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onRunDiagnostics() {
    try {
      const report = await runDiagnostics(props.workspaceId, props.projectId, props.userId);
      setDiagnostics(report);
      setNotice("Diagnostics atualizado.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const contextCount = context?.packet.snippets.length || 0;
  const riskCount = context?.retrieval.assembled.risks?.length || 0;
  const droppedByBudget = context?.retrieval.assembled.compression?.dropped_count || 0;
  const usedChars = context?.retrieval.assembled.compression?.used_chars || 0;
  const maxChars = context?.retrieval.assembled.compression?.max_chars || 0;
  const autoReingestStatus = context?.retrieval.assembled.auto_reingest?.sync?.status || "idle";
  const autoReingestReason = context?.retrieval.assembled.auto_reingest?.reason || "not_available";
  const artifactEvidenceCount =
    context?.packet.snippets.filter((item) => item.source.startsWith("artifact:file:")).length || 0;

  const topFailures = Object.entries(diagnostics?.failure_counts || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  return (
    <main className="grid">
      <section className="left">
        <ProjectSwitcher
          workspaceId={props.workspaceId}
          projectId={props.projectId}
          userId={props.userId}
          onWorkspaceIdChange={props.onWorkspaceIdChange}
          onProjectIdChange={props.onProjectIdChange}
          onUserIdChange={props.onUserIdChange}
        />

        <section className="card">
          <div className="section-head">
            <h3>Ask Runtime</h3>
            <p>Consulta com context assembly, routing e telemetry.</p>
          </div>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Ex: explique o fluxo de actions.xml x revscripts e mostre riscos arquiteturais"
            rows={6}
          />
          <div className="actions">
            <button onClick={onAsk} disabled={loading}>
              {loading ? "Processando..." : "Perguntar"}
            </button>
            <button onClick={onRunDiagnostics} disabled={loading}>
              Rodar Diagnostics
            </button>
          </div>

          {error ? <p className="error">{error}</p> : null}
          {notice ? <p className="status">{notice}</p> : null}

          <div className="hint-row">
            <span className="hint-pill">chat + retrieval</span>
            <span className="hint-pill">grounded evidence</span>
            <span className="hint-pill">auto-reingest</span>
            <span className="hint-pill">diagnostics</span>
            <span className="hint-pill">trace timeline</span>
          </div>
        </section>

        <section className="card">
          <div className="section-head">
            <h3>Model Answer + Feedback</h3>
            <p>Resposta final com score de confianca e ciclo de feedback rapido.</p>
          </div>

          <pre className="answer">{answer || "Sem resposta ainda."}</pre>

          <FeedbackBar disabled={loading || !chat} onAction={onFeedback} />
        </section>
      </section>

      <section className="right">
        <section className="card">
          <div className="section-head">
            <h3>Runtime Snapshot</h3>
            <p>Visao de alto nivel da execucao atual.</p>
          </div>

          <div className="metric-grid metric-grid-4">
            <article className="metric-card">
              <span>provider</span>
              <strong>{chat?.route.provider || "-"}</strong>
            </article>
            <article className="metric-card">
              <span>tier</span>
              <strong>{chat?.route.selected_tier || "-"}</strong>
            </article>
            <article className="metric-card">
              <span>confidence</span>
              <strong>{chat ? chat.confidence.toFixed(2) : "-"}</strong>
            </article>
            <article className="metric-card">
              <span>cost usd</span>
              <strong>{chat ? chat.route.estimated_cost_usd.toFixed(6) : "-"}</strong>
            </article>
            <article className="metric-card">
              <span>context snippets</span>
              <strong>{contextCount}</strong>
            </article>
            <article className="metric-card">
              <span>risk signals</span>
              <strong>{riskCount}</strong>
            </article>
            <article className="metric-card">
              <span>dropped by budget</span>
              <strong>{droppedByBudget}</strong>
            </article>
            <article className="metric-card">
              <span>chars used</span>
              <strong>
                {usedChars}/{maxChars}
              </strong>
            </article>
            <article className="metric-card">
              <span>artifact evidence</span>
              <strong>{artifactEvidenceCount}</strong>
            </article>
            <article className="metric-card">
              <span>auto reingest</span>
              <strong>{autoReingestStatus}</strong>
            </article>
          </div>

          <div className="panel-grid">
            <section className="panel-block">
              <h4>Diagnostics Top Failures</h4>
              <ul className="list tight-list">
                {topFailures.length === 0 ? <li>none</li> : null}
                {topFailures.map(([key, value]) => (
                  <li key={key}>
                    <span className="source">{key}</span>
                    <span className="meta">{value}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="panel-block">
              <h4>Trace Throughput</h4>
              <p className="meta">events in memory: {traces.length}</p>
              <p className="meta">trace id: {chat?.trace_id || "-"}</p>
              <p className="meta">reingest reason: {autoReingestReason}</p>
            </section>
          </div>
        </section>

        <ContextView context={context} />
        <TraceViewer chat={chat} context={context} diagnostics={diagnostics} traces={traces} />
      </section>
    </main>
  );
}
