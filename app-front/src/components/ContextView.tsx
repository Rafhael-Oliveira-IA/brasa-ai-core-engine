import { ContextAssembleResponse } from "../types";

type Props = {
  context: ContextAssembleResponse | null;
};

export default function ContextView({ context }: Props) {
  if (!context) {
    return (
      <section className="card">
        <h3>Context View</h3>
        <p>No context assembled yet.</p>
      </section>
    );
  }

  const assembled = context.retrieval.assembled;

  return (
    <section className="card">
      <h3>Context View</h3>
      <p>
        snippets: {context.packet.snippets.length} | took: {context.retrieval.took_ms}ms
      </p>

      <div className="pill-list">
        {(assembled.relevant_systems || []).slice(0, 12).map((item) => (
          <span className="pill" key={item}>
            {item}
          </span>
        ))}
      </div>

      <h4>Top Context Sources</h4>
      <ul className="list">
        {context.packet.snippets.slice(0, 12).map((item) => (
          <li key={item.source}>
            <div className="source">{item.source}</div>
            <div className="meta">score: {item.score.toFixed(4)}</div>
          </li>
        ))}
      </ul>

      <h4>Risks</h4>
      <ul className="list">
        {(assembled.risks || []).length === 0 ? <li>none</li> : null}
        {(assembled.risks || []).map((risk, index) => (
          <li key={`${risk}-${index}`}>{risk}</li>
        ))}
      </ul>

      <h4>Compression</h4>
      <pre className="code">{JSON.stringify(assembled.compression || {}, null, 2)}</pre>
    </section>
  );
}
