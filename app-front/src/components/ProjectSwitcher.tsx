import { useMemo } from "react";

type Props = {
  workspaceId: string;
  projectId: string;
  userId: string;
  onWorkspaceIdChange: (value: string) => void;
  onProjectIdChange: (value: string) => void;
  onUserIdChange: (value: string) => void;
};

const presets = [
  { label: "MMO - Servidor", workspaceId: "mmo_workspace", projectId: "SERVIDOR - ORIGINAL" },
  { label: "Unity - GreenFall", workspaceId: "unity_workspace", projectId: "BRP_GreenFall_v4" },
  { label: "Custom", workspaceId: "", projectId: "" },
];

export default function ProjectSwitcher(props: Props) {
  const selected = useMemo(() => {
    return (
      presets.find((item) => item.workspaceId === props.workspaceId && item.projectId === props.projectId)?.label ||
      "Custom"
    );
  }, [props.workspaceId, props.projectId]);

  return (
    <section className="card">
      <h3>Project Switcher</h3>
      <div className="row">
        <label>Preset</label>
        <select
          value={selected}
          onChange={(event) => {
            const preset = presets.find((item) => item.label === event.target.value);
            if (!preset) return;
            if (preset.label === "Custom") return;
            props.onWorkspaceIdChange(preset.workspaceId);
            props.onProjectIdChange(preset.projectId);
          }}
        >
          {presets.map((item) => (
            <option key={item.label} value={item.label}>
              {item.label}
            </option>
          ))}
        </select>
      </div>

      <div className="row">
        <label>Workspace</label>
        <input value={props.workspaceId} onChange={(event) => props.onWorkspaceIdChange(event.target.value)} />
      </div>

      <div className="row">
        <label>Project</label>
        <input value={props.projectId} onChange={(event) => props.onProjectIdChange(event.target.value)} />
      </div>

      <div className="row">
        <label>User</label>
        <input value={props.userId} onChange={(event) => props.onUserIdChange(event.target.value)} />
      </div>
    </section>
  );
}
