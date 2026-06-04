import { useMemo, useState } from "react";

import { executeActions, planActions, rollbackActions, runOrchestrator } from "../api";
import {
  ActionExecutionReport,
  ActionPlan,
  ActionRisk,
  ActionRollbackReport,
  OrchestratorMode,
  OrchestratorRunReport,
} from "../types";
import ProjectSwitcher from "./ProjectSwitcher";

function createRunId(): string {
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

function toSafeIterations(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.max(1, Math.min(5, Math.round(value)));
}

const RISK_WEIGHT: Record<ActionRisk, number> = {
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};

export default function OrchestratorWorkbench(props: ScopeProps) {
  const [intent, setIntent] = useState("");
  const [mode, setMode] = useState<OrchestratorMode>("manual");
  const [maxIterations, setMaxIterations] = useState(1);

  const [dryRun, setDryRun] = useState(false);
  const [runReflection, setRunReflection] = useState(true);
  const [autoLowRisk, setAutoLowRisk] = useState(true);
  const [autoMediumRisk, setAutoMediumRisk] = useState(false);
  const [allowHighRisk, setAllowHighRisk] = useState(false);
  const [blockCriticalRisk, setBlockCriticalRisk] = useState(true);

  const [plan, setPlan] = useState<ActionPlan | null>(null);
  const [execution, setExecution] = useState<ActionExecutionReport | null>(null);
  const [rollback, setRollback] = useState<ActionRollbackReport | null>(null);
  const [orchestratorReport, setOrchestratorReport] = useState<OrchestratorRunReport | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const latestExecutionId = useMemo(() => {
    if (execution?.execution_id) {
      return execution.execution_id;
    }

    if (!orchestratorReport) {
      return "";
    }

    for (let i = orchestratorReport.iterations.length - 1; i >= 0; i -= 1) {
      const iter = orchestratorReport.iterations[i];
      if (iter.execution?.execution_id) {
        return iter.execution.execution_id;
      }
    }

    return "";
  }, [execution, orchestratorReport]);

  const highestPlanRisk = useMemo(() => {
    if (!plan || plan.actions.length === 0) {
      return "-";
    }

    let selected: ActionRisk = "low";
    for (const action of plan.actions) {
      const risk = (action.risk || "medium") as ActionRisk;
      if (RISK_WEIGHT[risk] > RISK_WEIGHT[selected]) {
        selected = risk;
      }
    }

    return selected;
  }, [plan]);

  const validationIssues = execution?.validation.issues || [];
  const resultRows = execution?.results || [];
  const iterationRows = orchestratorReport?.iterations || [];

  async function onPlanActions() {
    if (!intent.trim()) return;

    setLoading(true);
    setError("");
    setStatus("");

    try {
      const result = await planActions({
        workspace_id: props.workspaceId,
        project_id: props.projectId,
        user_id: props.userId,
        prompt: intent,
        max_actions: 12,
        metadata: { source: "app-front-orchestrator", mode },
      });

      setPlan(result);
      setStatus(`Plano gerado com ${result.actions.length} action(s).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function onExecutePlan() {
    if (!plan) {
      setError("Gere um plano antes de executar.");
      return;
    }

    setLoading(true);
    setError("");
    setStatus("");

    try {
      const result = await executeActions({
        workspace_id: props.workspaceId,
        project_id: props.projectId,
        user_id: props.userId,
        plan,
        options: {
          dry_run: dryRun,
          allow_high_risk: allowHighRisk,
          auto_rollback_on_error: true,
          run_feedback_loop: true,
        },
      });

      setExecution(result);
      setStatus(`Execucao finalizada. applied=${result.applied}, failed=${result.failed}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function onRollbackExecution() {
    if (!latestExecutionId) {
      setError("Nenhuma execution_id disponivel para rollback.");
      return;
    }

    setLoading(true);
    setError("");
    setStatus("");

    try {
      const result = await rollbackActions({
        workspace_id: props.workspaceId,
        project_id: props.projectId,
        user_id: props.userId,
        execution_id: latestExecutionId,
      });

      setRollback(result);
      setStatus(
        `Rollback concluido. restored=${result.restored_files}, removed=${result.removed_files}.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function onRunOrchestrator() {
    if (!intent.trim()) return;

    setLoading(true);
    setError("");
    setStatus("");

    try {
      const result = await runOrchestrator({
        run_id: createRunId(),
        workspace_id: props.workspaceId,
        project_id: props.projectId,
        user_id: props.userId,
        intent,
        mode,
        max_iterations: toSafeIterations(maxIterations),
        dry_run: dryRun,
        auto_execute_low_risk: autoLowRisk,
        auto_execute_medium_risk: autoMediumRisk,
        allow_high_risk: allowHighRisk,
        block_critical_risk: blockCriticalRisk,
        run_reflection: runReflection,
        metadata: { source: "app-front-orchestrator" },
      });

      setOrchestratorReport(result);
      setStatus(`Orchestrator finalizou com estado ${result.final_state}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
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
          <div className="section-head">
            <h3>Orchestrator Controls</h3>
            <p>Loop: Intent - Plan - Execute - Ingest - Evaluate - Reflect.</p>
          </div>

          <p className="muted">Project path is inherited automatically from indexed workspace artifacts.</p>

          <label className="field-label">Intent</label>
          <textarea
            value={intent}
            onChange={(event) => setIntent(event.target.value)}
            placeholder="Descreva a mudanca desejada..."
            rows={5}
          />

          <div className="row">
            <label>Modo</label>
            <select value={mode} onChange={(event) => setMode(event.target.value as OrchestratorMode)}>
              <option value="manual">manual</option>
              <option value="autopilot">autopilot</option>
            </select>
          </div>

          <div className="row">
            <label>Max Iter</label>
            <input
              type="number"
              min={1}
              max={5}
              value={maxIterations}
              onChange={(event) => setMaxIterations(toSafeIterations(Number(event.target.value)))}
            />
          </div>

          <div className="toggle-grid">
            <label className="toggle-item">
              <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
              dry_run
            </label>
            <label className="toggle-item">
              <input
                type="checkbox"
                checked={runReflection}
                onChange={(event) => setRunReflection(event.target.checked)}
              />
              run_reflection
            </label>
            <label className="toggle-item">
              <input
                type="checkbox"
                checked={autoLowRisk}
                onChange={(event) => setAutoLowRisk(event.target.checked)}
              />
              auto_execute_low_risk
            </label>
            <label className="toggle-item">
              <input
                type="checkbox"
                checked={autoMediumRisk}
                onChange={(event) => setAutoMediumRisk(event.target.checked)}
              />
              auto_execute_medium_risk
            </label>
            <label className="toggle-item">
              <input
                type="checkbox"
                checked={allowHighRisk}
                onChange={(event) => setAllowHighRisk(event.target.checked)}
              />
              allow_high_risk
            </label>
            <label className="toggle-item">
              <input
                type="checkbox"
                checked={blockCriticalRisk}
                onChange={(event) => setBlockCriticalRisk(event.target.checked)}
              />
              block_critical_risk
            </label>
          </div>

          <div className="actions">
            <button onClick={onPlanActions} disabled={loading || !intent.trim()}>
              Gerar Plano
            </button>
            <button onClick={onExecutePlan} disabled={loading || !plan}>
              Executar Plano
            </button>
            <button onClick={onRunOrchestrator} disabled={loading || !intent.trim()}>
              Rodar Orchestrator
            </button>
            <button onClick={onRollbackExecution} disabled={loading || !latestExecutionId}>
              Rollback
            </button>
          </div>

          {error ? <p className="error">{error}</p> : null}
          {status ? <p className="status">{status}</p> : null}

          <div className="hint-row">
            <span className="hint-pill">auto-agent loop</span>
            <span className="hint-pill">human-in-the-loop</span>
            <span className="hint-pill">policy guardrails</span>
            <span className="hint-pill">post-action feedback loop</span>
          </div>
        </section>
      </section>

      <section className="right">
        <section className="card">
          <div className="section-head">
            <h3>Run KPIs</h3>
            <p>Resumo rapido de plano, execucao e estado final do orchestrator.</p>
          </div>

          <div className="metric-grid metric-grid-4">
            <article className="metric-card">
              <span>plan actions</span>
              <strong>{plan?.actions.length || 0}</strong>
            </article>
            <article className="metric-card">
              <span>highest risk</span>
              <strong>{highestPlanRisk}</strong>
            </article>
            <article className="metric-card">
              <span>applied / failed</span>
              <strong>
                {execution?.applied || 0} / {execution?.failed || 0}
              </strong>
            </article>
            <article className="metric-card">
              <span>final state</span>
              <strong>{orchestratorReport?.final_state || "-"}</strong>
            </article>
          </div>
        </section>

        <section className="card">
          <div className="section-head">
            <h3>Action Plan Explorer</h3>
            <p>Alvos planejados, tipo de mutacao e risco previsto.</p>
          </div>

          {plan && plan.actions.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>target</th>
                    <th>type</th>
                    <th>risk</th>
                    <th>intent</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.actions.map((action) => (
                    <tr key={action.step_id || `${action.target}-${action.type}`}>
                      <td>{action.target}</td>
                      <td>{action.type}</td>
                      <td>{action.risk || "medium"}</td>
                      <td>{action.intent}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">Nenhum plano ainda. Gere um plano para visualizar alvos e riscos.</p>
          )}

          {plan?.warnings?.length ? (
            <ul className="list tight-list">
              {plan.warnings.map((item, index) => (
                <li key={`${item}-${index}`}>{item}</li>
              ))}
            </ul>
          ) : null}
        </section>

        <section className="card">
          <div className="section-head">
            <h3>Execution Inspector</h3>
            <p>Validation issues, step results, rollback and changed files.</p>
          </div>

          <div className="metric-grid metric-grid-4">
            <article className="metric-card">
              <span>execution id</span>
              <strong>{execution?.execution_id || "-"}</strong>
            </article>
            <article className="metric-card">
              <span>changed files</span>
              <strong>{execution?.changed_files.length || 0}</strong>
            </article>
            <article className="metric-card">
              <span>validation ok</span>
              <strong>{execution ? String(execution.validation.ok) : "-"}</strong>
            </article>
            <article className="metric-card">
              <span>rollback restored</span>
              <strong>{rollback?.restored_files || execution?.rollback_restored_files || 0}</strong>
            </article>
          </div>

          <div className="panel-grid">
            <section className="panel-block">
              <h4>Validation Issues</h4>
              <ul className="list tight-list">
                {validationIssues.length === 0 ? <li>none</li> : null}
                {validationIssues.map((issue) => (
                  <li key={`${issue.step_id}-${issue.code}`}>
                    <span className="source">{issue.code}</span>
                    <span className="meta">{issue.severity}</span>
                    <span className="meta">{issue.message}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="panel-block">
              <h4>Step Results</h4>
              <ul className="list tight-list">
                {resultRows.length === 0 ? <li>none</li> : null}
                {resultRows.map((item) => (
                  <li key={`${item.step_id}-${item.target}`}>
                    <span className="source">{item.status}</span>
                    <span className="meta">{item.target}</span>
                    <span className="meta">{item.message}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </section>

        <section className="card">
          <div className="section-head">
            <h3>Orchestrator Iteration Timeline</h3>
            <p>Decisao por iteracao, gates de avaliacao e notas de loop.</p>
          </div>

          <ul className="list tight-list timeline-list">
            {iterationRows.length === 0 ? <li>No iterations yet.</li> : null}
            {iterationRows.map((iteration) => (
              <li key={`iter-${iteration.iteration}`}>
                <div className="timeline-head">
                  <strong>Iteration {iteration.iteration}</strong>
                  <span className="badge">{iteration.decision.state}</span>
                </div>
                <div className="meta">reason: {iteration.decision.reason}</div>
                <div className="meta">highest risk: {iteration.decision.highest_risk}</div>
                <div className="meta">
                  execution: {iteration.execution ? `applied=${iteration.execution.applied}, failed=${iteration.execution.failed}` : "none"}
                </div>
                {iteration.notes.length > 0 ? (
                  <ul className="list tight-list">
                    {iteration.notes.map((item, index) => (
                      <li key={`${item}-${index}`}>{item}</li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        </section>

        <section className="card">
          <div className="section-head">
            <h3>Payload Debug</h3>
            <p>Raw payloads for troubleshooting and deep inspection.</p>
          </div>

          <details>
            <summary>Raw Action Plan</summary>
            <pre className="code compact-code">{JSON.stringify(plan || {}, null, 2)}</pre>
          </details>
          <details>
            <summary>Raw Execution + Rollback</summary>
            <pre className="code compact-code">{JSON.stringify({ execution, rollback }, null, 2)}</pre>
          </details>
          <details>
            <summary>Raw Orchestrator Report</summary>
            <pre className="code compact-code">{JSON.stringify(orchestratorReport || {}, null, 2)}</pre>
          </details>
        </section>
      </section>
    </main>
  );
}
