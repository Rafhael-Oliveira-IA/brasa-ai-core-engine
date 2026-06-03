import { ChatResponse, ContextAssembleResponse, DiagnosticsResponse } from "../types";

type Props = {
  chat: ChatResponse | null;
  context: ContextAssembleResponse | null;
  diagnostics: DiagnosticsResponse | null;
  traces: unknown[];
};

export default function TraceViewer({ chat, context, diagnostics, traces }: Props) {
  return (
    <section className="card">
      <h3>Trace Viewer</h3>

      <h4>Route</h4>
      {chat ? (
        <pre className="code">
{JSON.stringify(
  {
    trace_id: chat.trace_id,
    provider: chat.route.provider,
    model_name: chat.route.model_name,
    selected_tier: chat.route.selected_tier,
    reason: chat.route.reason,
    estimated_cost_usd: chat.route.estimated_cost_usd,
  },
  null,
  2,
)}
        </pre>
      ) : (
        <p>No route data yet.</p>
      )}

      <h4>Retrieval Packet</h4>
      {context ? <pre className="code">{JSON.stringify(context.retrieval.assembled.context_packet || [], null, 2)}</pre> : <p>No retrieval packet yet.</p>}

      <h4>Calibration Diagnostics</h4>
      {diagnostics ? <pre className="code">{JSON.stringify(diagnostics, null, 2)}</pre> : <p>Run diagnostics to inspect failures and recommendations.</p>}

      <h4>Recent Trace Events</h4>
      <pre className="code">{JSON.stringify(traces.slice(0, 8), null, 2)}</pre>
    </section>
  );
}
