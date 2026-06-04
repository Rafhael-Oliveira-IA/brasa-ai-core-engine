import { useMemo, useState } from "react";

import { executeActions, planActions, rollbackActions, runOrchestrator } from "../api";
import {
  ActionExecutionReport,
  ActionPlan,
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
          <h3>Cognitive Orchestrator</h3>
          <p className="muted">Loop: Intent → Plan → Execute → Ingest → Evaluate → Reflect.</p>
          <p className="muted">
            O projeto ativo do Project Switcher e herdado automaticamente para reindexacao.
          </p>

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
        </section>
      </section>

      <section className="right">
        <section className="card">
          <h3>Action Plan</h3>
          <pre className="code">{JSON.stringify(plan || {}, null, 2)}</pre>
        </section>

        <section className="card">
          <h3>Execution Report</h3>
          <pre className="code">{JSON.stringify(execution || {}, null, 2)}</pre>
          <h4>Rollback Report</h4>
          <pre className="code">{JSON.stringify(rollback || {}, null, 2)}</pre>
        </section>

        <section className="card">
          <h3>Orchestrator Loop Report</h3>
          <pre className="code">{JSON.stringify(orchestratorReport || {}, null, 2)}</pre>
        </section>
      </section>
    </main>
  );
}
