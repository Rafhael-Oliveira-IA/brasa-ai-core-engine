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

  const [context, setContext] = useState<ContextAssembleResponse | null>(null);
  const [chat, setChat] = useState<ChatResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResponse | null>(null);
  const [traces, setTraces] = useState<unknown[]>([]);

  async function onAsk() {
    if (!prompt.trim()) return;

    setLoading(true);
    setError("");
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
      setError("Feedback enviado.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onRunDiagnostics() {
    try {
      const report = await runDiagnostics(props.workspaceId, props.projectId, props.userId);
      setDiagnostics(report);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

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
          <h3>Chat</h3>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Pergunte algo real do projeto..."
            rows={5}
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

          <h4>Resposta</h4>
          <pre className="answer">{answer || "Sem resposta ainda."}</pre>

          <h4>Feedback</h4>
          <FeedbackBar disabled={loading || !chat} onAction={onFeedback} />
        </section>
      </section>

      <section className="right">
        <ContextView context={context} />
        <TraceViewer chat={chat} context={context} diagnostics={diagnostics} traces={traces} />
      </section>
    </main>
  );
}
