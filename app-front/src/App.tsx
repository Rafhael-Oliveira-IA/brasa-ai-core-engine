import { useState } from "react";

import ChatWorkbench from "./components/ChatWorkbench";
import OrchestratorWorkbench from "./components/OrchestratorWorkbench";

type AppView = "chat" | "orchestrator";

export default function App() {
  const [view, setView] = useState<AppView>("chat");
  const [workspaceId, setWorkspaceId] = useState("mmo_workspace");
  const [projectId, setProjectId] = useState("SERVIDOR - ORIGINAL");
  const [userId, setUserId] = useState("cognitive-user");

  return (
    <div className="layout">
      <header className="header">
        <h1>BRASA Cognitive Workbench</h1>
        <p>Chat operacional preservado + pagina separada para Action System e Orchestrator.</p>

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
            Action + Orchestrator
          </button>
        </div>
      </header>

      {view === "chat" ? (
        <ChatWorkbench
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
