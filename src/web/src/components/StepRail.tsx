import { C, F } from "../theme";

export const STEPS = ["upload", "requirements", "line-items", "match", "generate"] as const;
export type StepId = (typeof STEPS)[number];

const LABELS: Record<StepId, string> = {
  upload: "Upload",
  requirements: "Requirements",
  "line-items": "Line items",
  match: "Match",
  generate: "Generate",
};

export function stepIndex(step: StepId): number {
  return STEPS.indexOf(step);
}

interface Props {
  bidName: string;
  bidId: string;
  meta: string; // "Customer · Due date"
  primaryLabel: string;
  primaryDisabled?: boolean;
  onPrimary: () => void;
  viewStep: StepId;
  maxStep: StepId;
  onStepClick: (step: StepId) => void;
}

// Top bar (bid identity + single primary action) plus the 5-step rail. Dot state
// is driven by the furthest step reached (maxStep), NOT the current step, and
// numerals never swap to a checkmark — reached steps stay green and clickable in
// both directions.
export default function StepRail({
  bidName, bidId, meta, primaryLabel, primaryDisabled, onPrimary, viewStep, maxStep, onStepClick,
}: Props) {
  const maxIdx = stepIndex(maxStep);

  return (
    <div style={{ flex: "none", background: "#fff", borderBottom: `1px solid ${C.rule}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 18px 8px" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontFamily: F.serif, fontSize: 19, lineHeight: 1.1 }}>{bidName}</span>
            <span style={{ fontFamily: F.mono, fontSize: 10.5, color: C.inkFaint, background: C.wash, borderRadius: 4, padding: "2px 5px" }}>{bidId}</span>
          </div>
          <div style={{ fontSize: 11.5, color: C.inkFaint, marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{meta}</div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={onPrimary}
            disabled={primaryDisabled}
            style={{
              background: C.accent, color: "#fff", border: "none", borderRadius: 6,
              padding: "7px 14px", fontSize: 12.5, fontWeight: 600,
              cursor: primaryDisabled ? "default" : "pointer", opacity: primaryDisabled ? 0.55 : 1,
            }}
          >{primaryLabel}</button>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "stretch", padding: "0 18px", overflowX: "auto" }}>
        {STEPS.map((step, i) => {
          const reached = i <= maxIdx;
          const activeStep = step === viewStep;
          return (
            <button
              key={step}
              onClick={() => reached && onStepClick(step)}
              disabled={!reached}
              style={{
                flex: 1, minWidth: 130, background: "none", border: "none",
                borderBottom: activeStep ? `2px solid ${C.accent}` : "2px solid transparent",
                padding: "10px 4px", cursor: reached ? "pointer" : "not-allowed", textAlign: "center",
              }}
            >
              <span style={{ display: "flex", alignItems: "center", gap: 7, justifyContent: "center" }}>
                <span style={{
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  width: 18, height: 18, borderRadius: "50%",
                  background: reached ? C.accent : C.wash,
                  color: reached ? "#fff" : C.inkDisabled,
                  border: reached ? "none" : `1px solid ${C.rule}`,
                  boxShadow: activeStep ? `0 0 0 3px ${C.accentSoft}` : "none",
                  fontFamily: F.mono, fontSize: 10, fontWeight: 700, flex: "none",
                }}>{i + 1}</span>
                <span style={{
                  fontFamily: F.mono, fontSize: 10.5, letterSpacing: ".06em", textTransform: "uppercase",
                  color: reached ? C.ink : C.inkDisabled,
                }}>{LABELS[step]}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
