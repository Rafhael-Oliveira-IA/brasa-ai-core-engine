import { useMemo, useState } from "react";

import ConversationStudio from "./components/ConversationStudio";
import OrchestratorWorkbench from "./components/OrchestratorWorkbench";

type AppView = "chat" | "orchestrator";

export default function App() {
  const [view, setView] = useState<AppView>("chat");
  const [workspaceId, setWorkspaceId] = useState("mmo_workspace");
  const [projectId, setProjectId] = useState("SERVIDOR - ORIGINAL");
  const [userId, setUserId] = useState("cognitive-user");

  const viewLabel = useMemo(() => {
    if (view === "chat") {
      return {
        title: "Cognitive Studio Conversation",
        description:
          "Session-based copilot workflow with command-driven access to all BRASA core systems.",
      };
    }

    return {
      title: "Action + Auto-Agent Runtime",
      description:
        "Plan, validate, execute, rollback and inspect autonomous loop iterations with explicit guardrails.",
    };
  }, [view]);

  return (
    <div className="layout">
      <header className="header-shell">
        <div className="header-brand">
          <p className="eyebrow">BRASA Cognitive Runtime</p>
          <h1>{viewLabel.title}</h1>
          <p className="subhead">{viewLabel.description}</p>
        </div>

        <div className="scope-strip">
          <div className="scope-pill">
            <span>workspace</span>
            <strong>{workspaceId}</strong>
          </div>
          <div className="scope-pill">
            <span>project</span>
            <strong>{projectId}</strong>
          </div>
          <div className="scope-pill">
            <span>user</span>
            <strong>{userId}</strong>
          </div>
        </div>

        <div className="view-switch">
          <button
            className={`view-btn ${view === "chat" ? "active" : ""}`}
            onClick={() => setView("chat")}
          >
            Chat Runtime
          </button>
          <button
            className={`view-btn ${view === "orchestrator" ? "active" : ""}`}
            onClick={() => setView("orchestrator")}
          >
            Action + Auto-Agent
          </button>
        </div>
      </header>

      {view === "chat" ? (
        <ConversationStudio
          workspaceId={workspaceId}
          projectId={projectId}
          userId={userId}
          onWorkspaceIdChange={setWorkspaceId}
          onProjectIdChange={setProjectId}
          onUserIdChange={setUserId}
        />
      ) : (
        <OrchestratorWorkbench
          workspaceId={workspaceId}
          projectId={projectId}
          userId={userId}
          onWorkspaceIdChange={setWorkspaceId}
          onProjectIdChange={setProjectId}
          onUserIdChange={setUserId}
        />
      )}
    </div>
  );
}
