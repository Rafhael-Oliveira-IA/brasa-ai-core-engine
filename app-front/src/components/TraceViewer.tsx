import { ChatResponse, ContextAssembleResponse, DiagnosticsResponse } from "../types";

type Props = {
  chat: ChatResponse | null;
  context: ContextAssembleResponse | null;
  diagnostics: DiagnosticsResponse | null;
  traces: unknown[];
};

export default function TraceViewer({ chat, context, diagnostics, traces }: Props) {
  const topFailures = Object.entries(diagnostics?.failure_counts || {}).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const traceItems = traces
    .map((item) => (typeof item === "object" && item !== null ? (item as Record<string, unknown>) : null))
    .filter((item): item is Record<string, unknown> => item !== null)
    .slice(0, 10);

  return (
    <section className="card">
      <div className="section-head">
        <h3>Observability</h3>
        <p>Route decisions, calibration diagnostics and recent telemetry events.</p>
      </div>

      <div className="panel-grid">
        <section className="panel-block">
          <h4>Route Decision</h4>
          {chat ? (
            <dl className="kv-grid">
              <dt>trace_id</dt>
              <dd>{chat.trace_id}</dd>
              <dt>provider</dt>
              <dd>{chat.route.provider}</dd>
              <dt>model</dt>
              <dd>{chat.route.model_name}</dd>
              <dt>tier</dt>
              <dd>{chat.route.selected_tier}</dd>
              <dt>estimated cost</dt>
              <dd>${chat.route.estimated_cost_usd.toFixed(6)}</dd>
              <dt>reason</dt>
              <dd>{chat.route.reason}</dd>
            </dl>
          ) : (
            <p className="muted">No route data yet.</p>
          )}
        </section>

        <section className="panel-block">
          <h4>Calibration Diagnostics</h4>
          {diagnostics ? (
            <>
              <ul className="list tight-list">
                {topFailures.length === 0 ? <li>no failures</li> : null}
                {topFailures.map(([key, value]) => (
                  <li key={key}>
                    <span className="source">{key}</span>
                    <span className="meta">count {value}</span>
                  </li>
                ))}
              </ul>
              <h5>Recommendations</h5>
              <ul className="list tight-list">
                {diagnostics.recommendations.length === 0 ? <li>none</li> : null}
                {diagnostics.recommendations.slice(0, 5).map((item, index) => (
                  <li key={`${item}-${index}`}>{item}</li>
                ))}
              </ul>
            </>
          ) : (
            <p className="muted">Run diagnostics to inspect failure trends.</p>
          )}
        </section>
      </div>

      <section className="panel-block">
        <h4>Retrieval Packet Snapshot</h4>
        {context ? (
          <pre className="code compact-code">{JSON.stringify(context.retrieval.assembled.context_packet || [], null, 2)}</pre>
        ) : (
          <p className="muted">No retrieval packet yet.</p>
        )}
      </section>

      <section className="panel-block">
        <h4>Recent Trace Events</h4>
        {traceItems.length === 0 ? <p className="muted">No trace events yet.</p> : null}
        <ul className="list tight-list">
          {traceItems.map((item, index) => {
            const eventType = String(item.event_type || "unknown");
            const requestId = String(item.request_id || "-");
            const createdAt = String(item.created_at || "-");
            return (
              <li key={`${eventType}-${requestId}-${index}`}>
                <span className="source">{eventType}</span>
                <span className="meta">{requestId}</span>
                <span className="meta">{createdAt}</span>
              </li>
            );
          })}
        </ul>
      </section>
    </section>
  );
}
