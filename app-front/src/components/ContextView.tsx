import { ContextAssembleResponse } from "../types";

type Props = {
  context: ContextAssembleResponse | null;
};

export default function ContextView({ context }: Props) {
  if (!context) {
    return (
      <section className="card">
        <div className="section-head">
          <h3>Context Intelligence</h3>
          <p>Aguardando uma consulta para montar pacote contextual.</p>
        </div>
      </section>
    );
  }

  const assembled = context.retrieval.assembled;
  const snippets = context.packet.snippets;
  const compression = assembled.compression;
  const selectedCount = compression?.selected_count ?? snippets.length;
  const droppedCount = compression?.dropped_count ?? 0;
  const usedChars = compression?.used_chars ?? 0;
  const maxChars = compression?.max_chars ?? 0;
  const systems = assembled.relevant_systems || [];
  const dependencies = assembled.dependencies || [];
  const risks = assembled.risks || [];
  const autoReingest = assembled.auto_reingest;
  const autoReingestSync = autoReingest?.sync;
  const autoReingestStatus = autoReingestSync?.status || "idle";
  const artifactEvidence = snippets.filter((item) => item.source.startsWith("artifact:file:")).length;

  return (
    <section className="card">
      <div className="section-head">
        <h3>Context Intelligence</h3>
        <p>Pacote selecionado para raciocinio, com ranking e compressao.</p>
      </div>

      <div className="metric-grid metric-grid-4">
        <article className="metric-card">
          <span>snippets</span>
          <strong>{snippets.length}</strong>
        </article>
        <article className="metric-card">
          <span>retrieval ms</span>
          <strong>{context.retrieval.took_ms}</strong>
        </article>
        <article className="metric-card">
          <span>selected / dropped</span>
          <strong>
            {selectedCount} / {droppedCount}
          </strong>
        </article>
        <article className="metric-card">
          <span>chars budget</span>
          <strong>
            {usedChars}/{maxChars}
          </strong>
        </article>
        <article className="metric-card">
          <span>artifact evidence</span>
          <strong>{artifactEvidence}</strong>
        </article>
        <article className="metric-card">
          <span>auto reingest</span>
          <strong>{autoReingestStatus}</strong>
        </article>
      </div>

      <div className="panel-grid">
        <section className="panel-block">
          <h4>Top Context Sources</h4>
          <ul className="list tight-list">
            {snippets.slice(0, 12).map((item) => (
              <li key={item.source}>
                <div className="source">{item.source}</div>
                <div className="meta">score {item.score.toFixed(4)}</div>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel-block">
          <h4>Systems + Dependencies</h4>
          <div className="pill-list">
            {systems.slice(0, 14).map((item) => (
              <span className="pill" key={item}>
                {item}
              </span>
            ))}
            {systems.length === 0 ? <span className="pill pill-empty">none</span> : null}
          </div>
          <div className="pill-list">
            {dependencies.slice(0, 14).map((item) => (
              <span className="pill pill-secondary" key={item}>
                {item}
              </span>
            ))}
            {dependencies.length === 0 ? <span className="pill pill-empty">no dependencies</span> : null}
          </div>
        </section>
      </div>

      <section className="panel-block">
        <h4>Risk Signals</h4>
        <ul className="list tight-list">
          {risks.length === 0 ? <li>none</li> : null}
          {risks.map((risk, index) => (
            <li key={`${risk}-${index}`}>{risk}</li>
          ))}
        </ul>
      </section>

      <section className="panel-block">
        <h4>Auto Reingest</h4>
        {!autoReingest ? <p className="muted">No auto-reingest diagnostics.</p> : null}
        {autoReingest ? (
          <dl className="kv-grid">
            <dt>triggered</dt>
            <dd>{String(Boolean(autoReingest.triggered))}</dd>
            <dt>reason</dt>
            <dd>{autoReingest.reason || "-"}</dd>
            <dt>context reasons</dt>
            <dd>{(autoReingest.context_reasons || []).join(", ") || "-"}</dd>
            <dt>sync status</dt>
            <dd>{autoReingestSync?.status || "-"}</dd>
            <dt>sync files</dt>
            <dd>{autoReingestSync?.scanned_files ?? 0}</dd>
            <dt>changed nodes</dt>
            <dd>{autoReingestSync?.changed_nodes ?? 0}</dd>
          </dl>
        ) : null}
      </section>
    </section>
  );
}
