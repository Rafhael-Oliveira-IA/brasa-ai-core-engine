import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  createConversationSession,
  getProjectArtifactFile,
  getProjectArtifactsTree,
  listConversationMessages,
  listConversationSessions,
  runProjectIngestion,
  sendConversationMessage,
} from "../api";
import {
  ConversationMessage,
  ConversationSendResponse,
  ConversationSession,
  ProjectArtifactFileContentResponse,
  ProjectArtifactsTreeResponse,
} from "../types";

type ScopeProps = {
  workspaceId: string;
  projectId: string;
  userId: string;
  onWorkspaceIdChange: (value: string) => void;
  onProjectIdChange: (value: string) => void;
  onUserIdChange: (value: string) => void;
};

type CommandDef = {
  id: string;
  label: string;
  hint: string;
  optionsHint: string;
};

type ExplorerNode = {
  name: string;
  path: string;
  kind: "file" | "folder";
  children: ExplorerNode[];
};

const COMMANDS: CommandDef[] = [
  { id: "chat", label: "chat", hint: "Conversa com retrieval e roteamento completo.", optionsHint: "{}" },
  {
    id: "task",
    label: "task",
    hint: "Task engine com task_type em options.",
    optionsHint: '{"task_type":"planning"}',
  },
  {
    id: "action_plan",
    label: "action_plan",
    hint: "Planejamento estruturado de alteracoes.",
    optionsHint: '{"max_actions":12}',
  },
  {
    id: "action_execute",
    label: "action_execute",
    hint: "Executa plano informado em options.plan.",
    optionsHint:
      '{"plan":{"plan_id":"...","project_id":"...","user_id":"...","prompt":"...","actions":[{"type":"update_file","target":"app/router.py","intent":"update"}]},"execution_options":{"dry_run":true,"allow_high_risk":false,"auto_rollback_on_error":true,"run_feedback_loop":true}}',
  },
  {
    id: "action_rollback",
    label: "action_rollback",
    hint: "Rollback por execution_id.",
    optionsHint: '{"execution_id":"<execution-id>"}',
  },
  {
    id: "orchestrator",
    label: "orchestrator",
    hint: "Loop autonomo controlado por politica.",
    optionsHint:
      '{"mode":"manual","max_iterations":1,"dry_run":false,"auto_execute_low_risk":true,"auto_execute_medium_risk":false,"allow_high_risk":false,"block_critical_risk":true,"run_reflection":true}',
  },
  { id: "context_assemble", label: "context_assemble", hint: "Somente montagem de contexto.", optionsHint: "{}" },
  {
    id: "knowledge_sync",
    label: "knowledge_sync",
    hint: "Sincroniza arvore de conhecimento.",
    optionsHint: '{"force":false}',
  },
  {
    id: "ingestion_run",
    label: "ingestion_run",
    hint: "Ingestao completa para project_path.",
    optionsHint: '{"project_path":"F:/Projeto","force":false}',
  },
  {
    id: "watcher_check",
    label: "watcher_check",
    hint: "Detecta delta de arquivos e rebuild.",
    optionsHint: '{"project_path":"F:/Projeto","auto_rebuild":true}',
  },
  {
    id: "evaluation_run",
    label: "evaluation_run",
    hint: "Metricas de qualidade operacional.",
    optionsHint: '{"limit":300}',
  },
  { id: "reflection_run", label: "reflection_run", hint: "Passo reflexivo.", optionsHint: "{}" },
  { id: "diagnostics", label: "diagnostics", hint: "Diagnostico de calibracao.", optionsHint: "{}" },
];

function shortTitle(prompt: string): string {
  const raw = prompt.trim();
  if (!raw) return "New Conversation";
  return raw.length <= 56 ? raw : `${raw.slice(0, 56)}...`;
}

function normalizePath(value: string): string {
  return value.replace(/\\/g, "/").replace(/^\/+/, "").trim();
}

function sourceToPath(source: string): string {
  const normalized = normalizePath(source);
  if (normalized.startsWith("artifact:file:")) {
    return normalizePath(normalized.slice("artifact:file:".length));
  }
  if (normalized.startsWith("artifact:folder:")) {
    return normalizePath(normalized.slice("artifact:folder:".length));
  }
  if (normalized.startsWith("artifact:module:")) {
    return normalizePath(normalized.slice("artifact:module:".length));
  }
  return normalized;
}

function toRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function parseOptions(raw: string): { value: Record<string, unknown>; error: string } {
  const trimmed = raw.trim();
  if (!trimmed) {
    return { value: {}, error: "" };
  }

  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return { value: parsed as Record<string, unknown>, error: "" };
    }
    return { value: {}, error: "Options precisa ser um objeto JSON." };
  } catch (err) {
    return {
      value: {},
      error: err instanceof Error ? `JSON invalido: ${err.message}` : "JSON invalido.",
    };
  }
}

function mergeMessages(current: ConversationMessage[], incoming: ConversationMessage[]): ConversationMessage[] {
  const map = new Map<string, ConversationMessage>();
  [...current, ...incoming].forEach((item) => {
    map.set(item.message_id, item);
  });
  return Array.from(map.values()).sort((a, b) => a.created_at.localeCompare(b.created_at));
}

function extractPathsFromMessages(messages: ConversationMessage[]): string[] {
  const paths: string[] = [];
  for (const message of messages) {
    for (const source of message.context_sources || []) {
      const path = sourceToPath(source);
      if (path.includes("/") || /\.[a-z0-9]+$/i.test(path)) {
        paths.push(path);
      }
    }
  }
  return paths;
}

type RawExplorerNode = {
  name: string;
  path: string;
  kind: "file" | "folder";
  children: Map<string, RawExplorerNode>;
};

function buildExplorerTree(paths: string[]): ExplorerNode[] {
  const root = new Map<string, RawExplorerNode>();

  for (const value of paths) {
    const normalized = normalizePath(value);
    if (!normalized) continue;

    const parts = normalized.split("/").filter(Boolean);
    if (!parts.length) continue;

    let current = root;
    let builtPath = "";

    parts.forEach((part, index) => {
      builtPath = builtPath ? `${builtPath}/${part}` : part;
      const isLeaf = index === parts.length - 1;
      const isFile = isLeaf && /\.[a-z0-9]+$/i.test(part);

      let node = current.get(part);
      if (!node) {
        node = {
          name: part,
          path: builtPath,
          kind: isFile ? "file" : "folder",
          children: new Map<string, RawExplorerNode>(),
        };
        current.set(part, node);
      }

      if (!isLeaf) {
        node.kind = "folder";
        current = node.children;
      }
    });
  }

  function toNodes(map: Map<string, RawExplorerNode>): ExplorerNode[] {
    const items = Array.from(map.values()).map((node) => ({
      name: node.name,
      path: node.path,
      kind: node.kind,
      children: toNodes(node.children),
    }));

    return items.sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === "folder" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }

  return toNodes(root);
}

function firstFilePath(nodes: ExplorerNode[]): string {
  for (const node of nodes) {
    if (node.kind === "file") return node.path;
    const nested = firstFilePath(node.children);
    if (nested) return nested;
  }
  return "";
}

function hasPath(nodes: ExplorerNode[], targetPath: string): boolean {
  for (const node of nodes) {
    if (node.path === targetPath) return true;
    if (hasPath(node.children, targetPath)) return true;
  }
  return false;
}

function findSnippetByPath(operation: ConversationSendResponse | null, filePath: string): string {
  if (!operation) return "";

  const operationResult = toRecord(operation.operation_result);
  const packet = toRecord(operationResult.packet);
  const snippets = Array.isArray(packet.snippets) ? packet.snippets : [];

  for (const snippet of snippets) {
    const raw = toRecord(snippet);
    const source = sourceToPath(String(raw.source || ""));
    if (source === filePath && typeof raw.content === "string" && raw.content.trim()) {
      return raw.content;
    }
  }

  return "";
}

function formatWhen(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function ExplorerTree(props: {
  nodes: ExplorerNode[];
  selectedFilePath: string;
  onSelectFile: (path: string) => void;
  depth?: number;
}) {
  const depth = props.depth || 0;

  return (
    <ul className={depth === 0 ? "explorer-tree-root" : "explorer-tree-child"}>
      {props.nodes.map((node) => {
        const isActive = node.kind === "file" && node.path === props.selectedFilePath;
        const indent = depth * 14 + 10;

        return (
          <li key={node.path}>
            <button
              type="button"
              className={`explorer-node-btn ${node.kind} ${isActive ? "active" : ""}`}
              style={{ paddingLeft: `${indent}px` }}
              onClick={() => {
                if (node.kind === "file") props.onSelectFile(node.path);
              }}
            >
              <span className="explorer-node-icon">{node.kind === "folder" ? "▾" : "•"}</span>
              <span className="explorer-node-label">{node.name}</span>
            </button>
            {node.children.length > 0 ? (
              <ExplorerTree
                nodes={node.children}
                selectedFilePath={props.selectedFilePath}
                onSelectFile={props.onSelectFile}
                depth={depth + 1}
              />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export default function ConversationStudio(props: ScopeProps) {
  const [sessions, setSessions] = useState<ConversationSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [activeMessageId, setActiveMessageId] = useState<string>("");

  const [artifactsTree, setArtifactsTree] = useState<ProjectArtifactsTreeResponse | null>(null);
  const [selectedFilePath, setSelectedFilePath] = useState<string>("");
  const [fileContent, setFileContent] = useState<ProjectArtifactFileContentResponse | null>(null);
  const [fileContentError, setFileContentError] = useState("");

  const [prompt, setPrompt] = useState("");
  const [command, setCommand] = useState<string>("chat");
  const [optionsText, setOptionsText] = useState<string>("");

  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingKnowledge, setLoadingKnowledge] = useState(false);
  const [loadingFileContent, setLoadingFileContent] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [sending, setSending] = useState(false);

  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [lastOperation, setLastOperation] = useState<ConversationSendResponse | null>(null);
  const [projectPathInput, setProjectPathInput] = useState("");
  const [autoIngestEnabled, setAutoIngestEnabled] = useState(true);

  const threadEndRef = useRef<HTMLDivElement | null>(null);
  const lastAutoIngestKeyRef = useRef("");

  const commandDef = useMemo(() => {
    return COMMANDS.find((item) => item.id === command) || COMMANDS[0];
  }, [command]);

  const selectedMessage = useMemo(() => {
    if (!messages.length) return null;
    const direct = messages.find((item) => item.message_id === activeMessageId);
    return direct || messages[messages.length - 1] || null;
  }, [messages, activeMessageId]);

  const explorerTree = useMemo(() => {
    const fromArtifacts = (artifactsTree?.files || []).map((item) => normalizePath(item));
    const fromMessages = extractPathsFromMessages(messages);
    const unique = Array.from(new Set([...fromArtifacts, ...fromMessages]));
    return buildExplorerTree(unique);
  }, [artifactsTree, messages]);

  const selectedSnippet = useMemo(() => {
    if (!selectedFilePath) return "";

    const byLastOperation = findSnippetByPath(lastOperation, selectedFilePath);
    if (byLastOperation) return byLastOperation;

    const selectedMetadata = toRecord(selectedMessage?.metadata);
    const opPayload = selectedMetadata.operation_result;
    if (opPayload) {
      const fallbackOperation: ConversationSendResponse = {
        session: sessions.find((item) => item.session_id === activeSessionId) || {
          session_id: "",
          workspace_id: props.workspaceId,
          project_id: props.projectId,
          user_id: props.userId,
          title: "",
          metadata: {},
          archived: false,
          created_at: "",
          updated_at: "",
        },
        user_message: selectedMessage || {
          message_id: "",
          session_id: "",
          workspace_id: props.workspaceId,
          project_id: props.projectId,
          user_id: props.userId,
          role: "assistant",
          content: "",
          context_sources: [],
          metadata: {},
          created_at: "",
        },
        assistant_message: selectedMessage || {
          message_id: "",
          session_id: "",
          workspace_id: props.workspaceId,
          project_id: props.projectId,
          user_id: props.userId,
          role: "assistant",
          content: "",
          context_sources: [],
          metadata: {},
          created_at: "",
        },
        task: null,
        operation: "chat",
        operation_result: toRecord(opPayload),
      };
      return findSnippetByPath(fallbackOperation, selectedFilePath);
    }

    return "";
  }, [selectedFilePath, lastOperation, selectedMessage, sessions, activeSessionId, props.workspaceId, props.projectId, props.userId]);

  const selectedFileContextSources = useMemo(() => {
    if (!selectedFilePath) return [] as string[];

    const list: string[] = [];
    for (const message of messages) {
      for (const source of message.context_sources || []) {
        if (sourceToPath(source) === selectedFilePath) {
          list.push(`${message.role}: ${source}`);
        }
      }
    }
    return list;
  }, [messages, selectedFilePath]);

  useEffect(() => {
    const storageKey = `brasa.projectPath.${props.workspaceId}::${props.projectId}`;
    const stored = typeof window !== "undefined" ? window.localStorage.getItem(storageKey) : null;
    setProjectPathInput(stored || "");
    lastAutoIngestKeyRef.current = "";
  }, [props.workspaceId, props.projectId]);

  useEffect(() => {
    if (!artifactsTree?.source_project_path) return;
    if (projectPathInput.trim()) return;
    setProjectPathInput(artifactsTree.source_project_path);
  }, [artifactsTree?.source_project_path, projectPathInput]);

  useEffect(() => {
    void refreshSessions();
    void refreshProjectArtifacts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.workspaceId, props.projectId, props.userId]);

  useEffect(() => {
    if (!autoIngestEnabled) return;
    if (!projectPathInput.trim()) return;
    if (!artifactsTree) return;
    if (artifactsTree.ingested) return;
    if (ingesting) return;

    const key = `${props.workspaceId}::${props.projectId}::${projectPathInput.trim()}`;
    if (lastAutoIngestKeyRef.current === key) return;

    lastAutoIngestKeyRef.current = key;
    void runIngestion("auto");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoIngestEnabled, projectPathInput, artifactsTree, ingesting, props.workspaceId, props.projectId]);

  useEffect(() => {
    if (!activeSessionId) {
      setMessages([]);
      return;
    }

    void loadMessages(activeSessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId]);

  useEffect(() => {
    if (!messages.length) {
      setActiveMessageId("");
      return;
    }

    const exists = messages.some((item) => item.message_id === activeMessageId);
    if (!exists) {
      setActiveMessageId(messages[messages.length - 1].message_id);
    }
  }, [messages, activeMessageId]);

  useEffect(() => {
    if (!explorerTree.length) {
      setSelectedFilePath("");
      return;
    }

    if (!selectedFilePath || !hasPath(explorerTree, selectedFilePath)) {
      setSelectedFilePath(firstFilePath(explorerTree));
    }
  }, [explorerTree, selectedFilePath]);

  useEffect(() => {
    if (!selectedFilePath) {
      setFileContent(null);
      setFileContentError("");
      return;
    }

    let cancelled = false;

    async function loadFile() {
      setLoadingFileContent(true);
      setFileContentError("");

      try {
        const response = await getProjectArtifactFile(
          props.workspaceId,
          props.projectId,
          selectedFilePath,
          50000,
        );
        if (cancelled) return;
        setFileContent(response);
      } catch (err) {
        if (cancelled) return;
        setFileContent(null);
        setFileContentError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) {
          setLoadingFileContent(false);
        }
      }
    }

    void loadFile();

    return () => {
      cancelled = true;
    };
  }, [selectedFilePath, props.workspaceId, props.projectId]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, sending]);

  async function refreshSessions(preferredSessionId?: string) {
    setLoadingSessions(true);
    setError("");

    try {
      const response = await listConversationSessions(
        props.workspaceId,
        props.projectId,
        props.userId,
        80,
      );
      const items = response.items || [];
      setSessions(items);

      if (!items.length) {
        setActiveSessionId("");
        setMessages([]);
        return;
      }

      const selectedId =
        preferredSessionId && items.some((item) => item.session_id === preferredSessionId)
          ? preferredSessionId
          : activeSessionId && items.some((item) => item.session_id === activeSessionId)
            ? activeSessionId
            : items[0].session_id;

      setActiveSessionId(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingSessions(false);
    }
  }

  async function refreshProjectArtifacts() {
    setLoadingKnowledge(true);

    try {
      const response = await getProjectArtifactsTree(
        props.workspaceId,
        props.projectId,
        12000,
      );
      setArtifactsTree(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingKnowledge(false);
    }
  }

  async function loadMessages(sessionId: string) {
    setLoadingMessages(true);
    setError("");

    try {
      const response = await listConversationMessages(
        sessionId,
        props.workspaceId,
        props.projectId,
        props.userId,
        500,
      );
      setMessages(response.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingMessages(false);
    }
  }

  async function createSessionFromPrompt(seedPrompt?: string): Promise<ConversationSession> {
    const session = await createConversationSession({
      workspace_id: props.workspaceId,
      project_id: props.projectId,
      user_id: props.userId,
      title: shortTitle(seedPrompt || "New Conversation"),
      metadata: {
        source: "conversation-studio-ui",
        ui_variant: "vscode-layout",
      },
    });

    setSessions((prev) => [session, ...prev.filter((item) => item.session_id !== session.session_id)]);
    setActiveSessionId(session.session_id);
    setMessages([]);
    return session;
  }

  async function onCreateSession() {
    setError("");
    setStatus("");

    try {
      await createSessionFromPrompt(prompt || "New Conversation");
      setStatus("Nova sessao criada.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function runIngestion(origin: "manual" | "auto") {
    const path = projectPathInput.trim();
    if (!path) {
      setError("Defina o project_path para ingestao.");
      return;
    }

    setIngesting(true);
    setError("");

    try {
      const report = await runProjectIngestion({
        workspace_id: props.workspaceId,
        project_path: path,
        force: false,
      });

      const storageKey = `brasa.projectPath.${props.workspaceId}::${props.projectId}`;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(storageKey, path);
      }

      setStatus(
        `${origin === "auto" ? "Auto" : "Manual"} ingest ok: scanned=${report.scanned_files}, changed=${report.changed_files}.`,
      );
      await refreshProjectArtifacts();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIngesting(false);
    }
  }

  async function onSend(event?: FormEvent) {
    event?.preventDefault();
    if (!prompt.trim()) return;

    setSending(true);
    setError("");
    setStatus("");

    const options = parseOptions(optionsText);
    if (options.error) {
      setSending(false);
      setError(options.error);
      return;
    }

    try {
      const activeSession = activeSessionId
        ? sessions.find((item) => item.session_id === activeSessionId) || null
        : null;
      const session = activeSession || (await createSessionFromPrompt(prompt));

      const response = await sendConversationMessage(session.session_id, {
        workspace_id: props.workspaceId,
        project_id: props.projectId,
        user_id: props.userId,
        prompt,
        command,
        options: options.value,
        metadata: {
          source: "conversation-studio-ui",
          ui_variant: "vscode-layout",
        },
      });

      setMessages((prev) => mergeMessages(prev, [response.user_message, response.assistant_message]));
      setActiveMessageId(response.assistant_message.message_id);
      setLastOperation(response);
      setPrompt("");
      setStatus(`Operacao '${response.operation}' concluida.`);
      await refreshSessions(session.session_id);
      await refreshProjectArtifacts();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  const activeSession = sessions.find((item) => item.session_id === activeSessionId) || null;
  const selectedMessageMetadata = toRecord(selectedMessage?.metadata);
  const selectedOperationResult = toRecord(selectedMessageMetadata.operation_result);

  return (
    <main className="studio-ide-shell">
      <aside className="ide-explorer card">
        <div className="ide-panel-head">
          <p className="eyebrow">Explorer</p>
          <h3>Workspace</h3>
        </div>

        <div className="ide-scope-grid">
          <label className="ide-field">
            <span>workspace</span>
            <input
              value={props.workspaceId}
              onChange={(event) => props.onWorkspaceIdChange(event.target.value)}
            />
          </label>
          <label className="ide-field">
            <span>project</span>
            <input
              value={props.projectId}
              onChange={(event) => props.onProjectIdChange(event.target.value)}
            />
          </label>
          <label className="ide-field">
            <span>user</span>
            <input value={props.userId} onChange={(event) => props.onUserIdChange(event.target.value)} />
          </label>
        </div>

        <div className="explorer-block">
          <div className="explorer-block-head">
            <h4>Conversations</h4>
            <div className="studio-sidebar-actions">
              <button type="button" onClick={onCreateSession} disabled={sending || loadingSessions}>
                New
              </button>
              <button
                type="button"
                className="ghost-btn"
                onClick={() => void refreshSessions()}
                disabled={sending || loadingSessions}
              >
                Refresh
              </button>
            </div>
          </div>

          <div className="session-list compact">
            {loadingSessions ? <p className="muted">Carregando sessoes...</p> : null}
            {!loadingSessions && sessions.length === 0 ? (
              <p className="muted">Nenhuma sessao criada.</p>
            ) : null}
            {sessions.map((session) => (
              <button
                key={session.session_id}
                type="button"
                className={`session-item ${session.session_id === activeSessionId ? "active" : ""}`}
                onClick={() => setActiveSessionId(session.session_id)}
              >
                <strong>{session.title || "Untitled"}</strong>
                <span className="session-meta">{formatWhen(session.last_message_at || session.updated_at)}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="explorer-block">
          <div className="explorer-block-head">
            <h4>Project Files</h4>
            <div className="studio-sidebar-actions">
              <button
                type="button"
                className="ghost-btn"
                onClick={() => void refreshProjectArtifacts()}
                disabled={loadingKnowledge || ingesting}
              >
                {loadingKnowledge ? "Sync..." : "Sync"}
              </button>
              <button
                type="button"
                onClick={() => void runIngestion("manual")}
                disabled={ingesting || !projectPathInput.trim()}
              >
                {ingesting ? "Ingest..." : "One-click Ingest"}
              </button>
            </div>
          </div>

          <label className="ide-field">
            <span>project_path</span>
            <input
              value={projectPathInput}
              onChange={(event) => setProjectPathInput(event.target.value)}
              placeholder="F:/POKECONTEST/SERVIDOR - ORIGINAL"
            />
          </label>

          <label className="toggle-item">
            <input
              type="checkbox"
              checked={autoIngestEnabled}
              onChange={(event) => setAutoIngestEnabled(event.target.checked)}
            />
            auto-ingest ao trocar workspace/project (com project_path salvo)
          </label>

          <p className="muted">files: {artifactsTree?.file_count || 0}</p>
          {artifactsTree?.ingested === false ? (
            <p className="error">
              Projeto ainda nao ingerido para este workspace/project. Rode o comando
              ingestion_run com options.project_path do seu MMO.
            </p>
          ) : null}
          {artifactsTree?.source_project_path ? (
            <p className="meta">source: {artifactsTree.source_project_path}</p>
          ) : null}
          {artifactsTree?.notes?.length ? (
            <ul className="list tight-list">
              {artifactsTree.notes.map((item, index) => (
                <li key={`${item}-${index}`}>{item}</li>
              ))}
            </ul>
          ) : null}

          <div className="explorer-tree-wrap">
            {!explorerTree.length ? <p className="muted">Sem arquivos no explorer ainda.</p> : null}
            {explorerTree.length > 0 ? (
              <ExplorerTree
                nodes={explorerTree}
                selectedFilePath={selectedFilePath}
                onSelectFile={setSelectedFilePath}
              />
            ) : null}
          </div>
        </div>
      </aside>

      <section className="ide-editor card">
        <div className="editor-tabs">
          <button type="button" className={`editor-tab ${!selectedFilePath ? "active" : ""}`}>
            workspace.overview
          </button>
          {selectedFilePath ? (
            <button type="button" className="editor-tab active">
              {selectedFilePath.split("/").slice(-1)[0]}
            </button>
          ) : null}
        </div>

        <div className="editor-body">
          <div className="editor-summary">
            <article className="metric-card">
              <span>active session</span>
              <strong>{activeSession?.title || "-"}</strong>
            </article>
            <article className="metric-card">
              <span>active command</span>
              <strong>{command}</strong>
            </article>
            <article className="metric-card">
              <span>selected file</span>
              <strong>{selectedFilePath || "-"}</strong>
            </article>
          </div>

          <div className="editor-canvas">
            {!selectedFilePath ? (
              <p className="editor-empty">
                Selecione um arquivo no Explorer para focar o raciocinio da conversa naquele contexto.
              </p>
            ) : (
              <>
                <p className="editor-path">{selectedFilePath}</p>

                <section className="panel-block">
                  <h4>Workspace File Content</h4>
                  {loadingFileContent ? <p className="muted">Carregando arquivo...</p> : null}
                  {!loadingFileContent && fileContent ? (
                    <>
                      <p className="meta">
                        size: {fileContent.size_bytes} bytes {fileContent.truncated ? "(truncated)" : ""}
                      </p>
                      <pre className="code editor-source">{fileContent.content}</pre>
                    </>
                  ) : null}
                  {!loadingFileContent && !fileContent ? (
                    <pre className="code editor-source">
                      {fileContentError ||
                        "Nao foi possivel carregar conteudo bruto deste arquivo no workspace."}
                    </pre>
                  ) : null}
                </section>

                <section className="panel-block">
                  <h4>Retrieval Snippet Evidence</h4>
                  {selectedSnippet ? (
                    <pre className="code editor-snippet">{selectedSnippet}</pre>
                  ) : (
                    <pre className="code editor-snippet">
                      Nenhum snippet bruto disponivel para este arquivo ainda. Rode um comando como
                      context_assemble/chat para puxar evidencia.
                    </pre>
                  )}
                </section>

                <div className="panel-grid">
                  <section className="panel-block">
                    <h4>Conversation References</h4>
                    <ul className="list tight-list">
                      {selectedFileContextSources.length === 0 ? <li>no references yet</li> : null}
                      {selectedFileContextSources.map((item, index) => (
                        <li key={`${item}-${index}`}>{item}</li>
                      ))}
                    </ul>
                  </section>

                  <section className="panel-block">
                    <h4>Selected Message</h4>
                    <p className="meta">role: {selectedMessage?.role || "-"}</p>
                    <p className="meta">created_at: {formatWhen(selectedMessage?.created_at)}</p>
                    <p className="meta">trace: {selectedMessage?.trace_id || "-"}</p>
                  </section>
                </div>

                <details open>
                  <summary>Operation Result (selected message)</summary>
                  <pre className="code compact-code">
                    {JSON.stringify(selectedOperationResult, null, 2)}
                  </pre>
                </details>
              </>
            )}
          </div>
        </div>
      </section>

      <aside className="ide-chat card">
        <div className="ide-panel-head">
          <p className="eyebrow">Copilot Thread</p>
          <h3>{activeSession?.title || "No Active Session"}</h3>
          <p className="subhead">Raciocinio persistente e especifico desta conversa.</p>
        </div>

        <div className="ide-chat-thread">
          {loadingMessages ? <p className="muted">Carregando mensagens...</p> : null}
          {!loadingMessages && messages.length === 0 ? (
            <p className="muted">Thread vazia. Envie um prompt para iniciar o ciclo.</p>
          ) : null}

          {messages.map((message) => {
            const metadata = toRecord(message.metadata);
            const operation = String(metadata.operation || metadata.command || "chat");
            const isActive = message.message_id === activeMessageId;

            return (
              <article
                key={message.message_id}
                className={`chat-msg ${message.role} ${isActive ? "active" : ""}`}
                onClick={() => setActiveMessageId(message.message_id)}
              >
                <div className="chat-msg-head">
                  <span>{message.role}</span>
                  <span>{operation}</span>
                </div>
                <pre className="chat-msg-content">{message.content}</pre>
                <p className="chat-msg-time">{formatWhen(message.created_at)}</p>
              </article>
            );
          })}

          <div ref={threadEndRef} />
        </div>

        <form className="studio-composer" onSubmit={(event) => void onSend(event)}>
          <div className="composer-row">
            <label>command</label>
            <select value={command} onChange={(event) => setCommand(event.target.value)}>
              {COMMANDS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="ghost-btn"
              onClick={() => setOptionsText(commandDef.optionsHint)}
            >
              template
            </button>
          </div>

          <p className="muted">{commandDef.hint}</p>

          <textarea
            rows={4}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Descreva exatamente o que o agente deve fazer nesta thread..."
          />

          <textarea
            rows={3}
            value={optionsText}
            onChange={(event) => setOptionsText(event.target.value)}
            placeholder={`options JSON (${commandDef.optionsHint})`}
          />

          <div className="actions">
            <button type="submit" disabled={sending || !prompt.trim()}>
              {sending ? "Executando..." : "Send"}
            </button>
            <button
              type="button"
              className="ghost-btn"
              onClick={() => {
                setPrompt("");
                setOptionsText("");
              }}
              disabled={sending}
            >
              clear
            </button>
          </div>

          {error ? <p className="error">{error}</p> : null}
          {status ? <p className="status">{status}</p> : null}
        </form>
      </aside>
    </main>
  );
}
