import { FeedbackIssue, FeedbackVerdict } from "../types";

type Action = {
  label: string;
  verdict: FeedbackVerdict;
  issues: FeedbackIssue[];
};

const actions: Action[] = [
  { label: "Correto", verdict: "correct", issues: [] },
  { label: "Parcial", verdict: "partial", issues: ["context_bad"] },
  { label: "Errado", verdict: "incorrect", issues: ["retrieval_incorrect"] },
  { label: "Faltou XML", verdict: "incorrect", issues: ["xml_missing"] },
  { label: "Contexto Ruim", verdict: "partial", issues: ["context_bad", "compression_bad"] },
];

type Props = {
  disabled?: boolean;
  onAction: (action: Action) => Promise<void>;
};

export default function FeedbackBar({ disabled, onAction }: Props) {
  return (
    <div className="feedback-shell">
      <p className="feedback-caption">Quick judgement</p>
      <div className="feedback-row">
      {actions.map((action) => (
        <button className="feedback-btn" key={action.label} disabled={disabled} onClick={() => onAction(action)}>
          {action.label}
        </button>
      ))}
      </div>
    </div>
  );
}
