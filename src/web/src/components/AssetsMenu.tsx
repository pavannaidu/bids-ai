import { useState } from "react";
import { C, F, shadow } from "../theme";
import { useDismiss } from "../hooks";
import { fetchAssets } from "../api";
import { IconExternal, IconStack } from "./icons";
import type { AssetLink } from "../types";

// Sidebar menu that opens the Databricks assets behind the app (its Lakebase project, the Unity
// Catalog documents volume, the model serving endpoints) in the workspace, so a viewer can inspect
// what powers each screen. Links come from GET /api/assets, built server-side from the workspace host.
export default function AssetsMenu({ collapsed }: { collapsed: boolean }) {
  const [open, setOpen] = useState(false);
  const [assets, setAssets] = useState<AssetLink[] | null>(null);
  const [failed, setFailed] = useState(false);
  const ref = useDismiss<HTMLDivElement>(open, () => setOpen(false));

  const toggle = () => {
    setOpen((o) => !o);
    if (assets === null) {
      setFailed(false);
      fetchAssets().then(setAssets).catch(() => setFailed(true));
    }
  };

  const groups = (assets ?? []).reduce<Record<string, AssetLink[]>>((acc, a) => {
    (acc[a.group] ??= []).push(a);
    return acc;
  }, {});

  return (
    <div ref={ref} style={{ position: "relative", marginTop: "auto", marginBottom: 8 }}>
      <button
        onClick={toggle}
        title="Databricks assets behind this demo"
        style={{
          display: "flex", alignItems: "center", justifyContent: collapsed ? "center" : "flex-start",
          background: open ? "rgba(255,255,255,.16)" : "transparent", border: "none",
          color: "rgba(255,255,255,.92)", borderRadius: 7, padding: collapsed ? "9px 0" : "9px 10px",
          cursor: "pointer", fontSize: 13, width: "100%", textAlign: "left",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", flex: "none" }}><IconStack /></span>
        {!collapsed && <span style={{ marginLeft: 10 }}>Databricks assets</span>}
      </button>
      {open && (
        <div style={{
          position: "absolute", left: "calc(100% + 12px)", bottom: 0, zIndex: 60, width: 330,
          maxHeight: "80vh", overflowY: "auto", background: "#fff", border: `1px solid ${C.rule}`,
          borderRadius: 10, boxShadow: shadow.userMenu, padding: "12px 13px", color: C.ink,
        }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Under the hood</div>
          <div style={{ fontSize: 11, color: C.inkFaint, lineHeight: 1.45, marginTop: 3 }}>
            The Databricks assets this demo runs on. Each opens in your workspace.
          </div>
          {failed && <div style={noteStyle}>Couldn't load the asset links.</div>}
          {!failed && assets === null && <div style={noteStyle}>Loading…</div>}
          {assets !== null && assets.length === 0 && (
            <div style={noteStyle}>No workspace is configured, so there's nothing to link to.</div>
          )}
          {Object.entries(groups).map(([group, links]) => (
            <div key={group} style={{ marginTop: 12 }}>
              <div style={{
                fontFamily: F.mono, fontSize: 9.5, letterSpacing: ".06em", textTransform: "uppercase",
                color: C.inkFaint, marginBottom: 4,
              }}>{group}</div>
              {links.map((a) => (
                <a
                  key={a.url}
                  href={a.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: "flex", alignItems: "flex-start", gap: 8, padding: "6px 7px", margin: "0 -7px",
                    borderRadius: 6, textDecoration: "none", color: C.ink,
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = C.wash)}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                >
                  <span style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}>
                    <span style={{ fontSize: 12.5, fontWeight: 600 }}>{a.label}</span>
                    <span style={{
                      fontFamily: F.mono, fontSize: 10.5, color: C.inkSoft, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>{a.detail}</span>
                  </span>
                  <span style={{ color: C.accent, flex: "none", marginTop: 2 }}><IconExternal /></span>
                </a>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const noteStyle: React.CSSProperties = { fontSize: 11.5, color: C.inkSoft, marginTop: 10 };
