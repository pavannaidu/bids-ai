import { useState } from "react";
import { C, F, shadow } from "../theme";
import { useDismiss } from "../hooks";
import { IconWorkbench, IconAllBids, IconMatrix, IconPlus } from "./icons";
import type { ExtractionMethodSetting, MatchSensitivity } from "../types";

export type NavTab = "workbench" | "all-bids" | "matrix";

interface QueueEntry { team: string; count: number; }

interface Props {
  collapsed: boolean;
  onToggleCollapse: () => void;
  active: NavTab;
  onNavigate: (tab: NavTab) => void;
  onNewBid: () => void;
  // Reviewer queue (Requirements team filter). Hidden when there's no bid.
  queue: QueueEntry[] | null;
  scope: string; // "all" or a team name
  onScope: (team: string) => void;
  name: string;
  email: string;
  // Inline settings (no modal).
  extractionMethod: ExtractionMethodSetting;
  matchSensitivity: MatchSensitivity;
  matchThreshold: number;
  onExtractionMethod: (m: ExtractionMethodSetting) => void;
  onMatchSensitivity: (s: MatchSensitivity) => void;
}

const SENSITIVITY_HELP: Record<MatchSensitivity, string> = {
  permissive: "Auto-selects catalog matches at or above 0.60 semantic score.",
  balanced: "Auto-selects catalog matches at or above 0.70 semantic score (default).",
  conservative: "Auto-selects catalog matches at or above 0.80 semantic score.",
};

export default function Sidebar(props: Props) {
  const { collapsed, onToggleCollapse, active, onNavigate, onNewBid, queue, scope, onScope } = props;
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useDismiss<HTMLDivElement>(menuOpen, () => setMenuOpen(false));

  const width = collapsed ? 62 : 212;
  const navItem = (tab: NavTab, label: string, icon: React.ReactNode) => {
    const on = active === tab;
    return (
      <button
        key={tab}
        onClick={() => onNavigate(tab)}
        title={label}
        style={{
          display: "flex", alignItems: "center", justifyContent: collapsed ? "center" : "flex-start",
          gap: 0, background: on ? "rgba(255,255,255,.16)" : "transparent", border: "none",
          color: on ? "#fff" : "rgba(255,255,255,.92)", fontWeight: on ? 600 : 400,
          borderRadius: 7, padding: collapsed ? "9px 0" : "9px 10px", cursor: "pointer",
          fontSize: 13, width: "100%", textAlign: "left",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", flex: "none" }}>{icon}</span>
        {!collapsed && <span style={{ marginLeft: 10 }}>{label}</span>}
      </button>
    );
  };

  const initial = (props.name || props.email || "?").trim().charAt(0).toUpperCase();

  return (
    <div style={{
      width, flex: "none", background: C.accentDeep, color: "rgba(255,255,255,.92)",
      padding: "14px 10px", display: "flex", flexDirection: "column", height: "100vh",
    }}>
      {/* Brand row: BA monogram is the expand button when collapsed. Collapsed it
          fills the icon-rail tile (matching the nav items); expanded it's a compact
          26px mark next to the wordmark. */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: collapsed ? "center" : "flex-start", gap: 9, marginBottom: 4, minHeight: collapsed ? 40 : 26 }}>
        <button
          onClick={onToggleCollapse}
          title={collapsed ? "Expand sidebar" : "Bids AI"}
          style={{
            width: collapsed ? "100%" : 26, height: collapsed ? 40 : 26,
            borderRadius: collapsed ? 7 : 6, background: "rgba(255,255,255,.16)",
            color: "#fff", border: "none", fontFamily: F.mono,
            fontSize: collapsed ? 15 : 12, fontWeight: 700,
            cursor: "pointer", flex: "none", display: "inline-flex",
            alignItems: "center", justifyContent: "center", letterSpacing: ".02em",
          }}
        >BA</button>
        {!collapsed && (
          <>
            <span style={{ fontSize: 13.5, fontWeight: 600, color: "#fff", lineHeight: 1.2 }}>Bids AI</span>
            <button
              onClick={onToggleCollapse}
              title="Collapse sidebar"
              style={{
                marginLeft: "auto", background: "rgba(255,255,255,.08)", border: "none",
                color: "rgba(255,255,255,.8)", borderRadius: 6, width: 26, height: 26,
                cursor: "pointer", fontSize: 14, lineHeight: 1, flex: "none",
              }}
            >«</button>
          </>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 10 }}>
        {navItem("workbench", "Workbench", <IconWorkbench />)}
        {navItem("all-bids", "All Bids", <IconAllBids />)}
        {navItem("matrix", "Matrix", <IconMatrix />)}
      </div>

      {!collapsed && queue && queue.length > 0 && (
        <div style={{ marginTop: 22, padding: 10, borderRadius: 8, background: "rgba(255,255,255,.07)" }}>
          <div style={{
            fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".07em", textTransform: "uppercase",
            color: "rgba(255,255,255,.55)", marginBottom: 8,
          }}>Reviewer queue</div>
          {queue.map((q) => {
            const on = scope === q.team;
            return (
              <button
                key={q.team}
                onClick={() => onScope(q.team)}
                style={{
                  display: "block", width: "100%", textAlign: "left", background: on ? "rgba(255,255,255,.16)" : "none",
                  border: "none", color: on ? "#fff" : "rgba(255,255,255,.82)", fontWeight: on ? 600 : 400,
                  borderRadius: 5, padding: "5px 8px", fontSize: 12, cursor: "pointer",
                }}
              >{q.team === "all" ? "All teams" : q.team} · {q.count}</button>
            );
          })}
        </div>
      )}

      <button
        onClick={onNewBid}
        title="New bid"
        style={{
          marginTop: "auto", display: "flex", alignItems: "center", justifyContent: "center",
          background: "#fff", color: C.accentDeep, border: "none", borderRadius: 7,
          padding: collapsed ? "8px 0" : "8px 10px", fontSize: 12.5, fontWeight: 600, cursor: "pointer",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", flex: "none" }}><IconPlus /></span>
        {!collapsed && <span style={{ marginLeft: 8 }}>New bid</span>}
      </button>

      <div ref={menuRef} style={{ position: "relative", marginTop: 10 }}>
        <button
          onClick={() => setMenuOpen((o) => !o)}
          style={{
            display: "flex", alignItems: "center", gap: 9, width: "100%", background: "none",
            border: "none", borderRadius: 8, padding: "7px 8px", cursor: "pointer",
            justifyContent: collapsed ? "center" : "flex-start",
          }}
        >
          <span style={{
            display: "inline-flex", alignItems: "center", justifyContent: "center", width: 28, height: 28,
            borderRadius: "50%", background: "#fff", color: C.accentDeep, fontWeight: 700, fontSize: 12, flex: "none",
          }}>{initial}</span>
          {!collapsed && (
            <>
              <span style={{ display: "flex", flexDirection: "column", lineHeight: 1.25, textAlign: "left", minWidth: 0 }}>
                <span style={{ fontSize: 12.5, fontWeight: 600, color: "#fff", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{props.name || "Reviewer"}</span>
                <span style={{ fontSize: 10, color: "rgba(255,255,255,.6)" }}>Bids team · Reviewer</span>
              </span>
              <span style={{ marginLeft: "auto", fontSize: 8, color: "rgba(255,255,255,.6)", flex: "none" }}>▲</span>
            </>
          )}
        </button>
        {menuOpen && (
          <div style={{
            position: "absolute", bottom: "calc(100% + 8px)", left: 0, zIndex: 60, width: 280,
            background: "#fff", border: `1px solid ${C.rule}`, borderRadius: 10,
            boxShadow: shadow.userMenu, padding: "12px 13px",
          }}>
            <div style={{ fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".06em", textTransform: "uppercase", color: C.inkFaint }}>Signed in as</div>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: C.ink, marginTop: 3, wordBreak: "break-word" }}>{props.email || "—"}</div>
            <div style={{ height: 1, background: C.wash, margin: "11px 0" }} />
            <div style={{ fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".06em", textTransform: "uppercase", color: C.inkFaint, marginBottom: 7 }}>Settings</div>
            <label style={{ display: "block", fontSize: 11.5, fontWeight: 600, color: C.inkSoft, marginBottom: 4 }}>Default extraction method</label>
            <select
              value={props.extractionMethod}
              onChange={(e) => props.onExtractionMethod(e.target.value as ExtractionMethodSetting)}
              style={selectStyle}
            >
              <option value="ai_extract">ai_extract</option>
              <option value="ai_query">ai_query</option>
            </select>
            <div style={helpStyle}>
              {props.extractionMethod === "ai_extract"
                ? "Structured extraction (default). No external model endpoint needed."
                : "Legacy prompt-based path via the model serving endpoint (recovery)."}
            </div>
            <label style={{ display: "block", fontSize: 11.5, fontWeight: 600, color: C.inkSoft, margin: "11px 0 4px" }}>Match sensitivity</label>
            <select
              value={props.matchSensitivity}
              onChange={(e) => props.onMatchSensitivity(e.target.value as MatchSensitivity)}
              style={selectStyle}
            >
              <option value="permissive">Permissive</option>
              <option value="balanced">Balanced (default)</option>
              <option value="conservative">Conservative</option>
            </select>
            <div style={helpStyle}>{SENSITIVITY_HELP[props.matchSensitivity]}</div>
          </div>
        )}
      </div>
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  width: "100%", padding: "6px 8px", border: `1px solid ${C.rule}`, borderRadius: 6,
  fontSize: 12, fontFamily: "inherit", background: "#fff", color: C.ink, cursor: "pointer",
};
const helpStyle: React.CSSProperties = { fontSize: 10.5, color: C.inkFaint, lineHeight: 1.45, marginTop: 5 };
