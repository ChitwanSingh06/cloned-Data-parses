import React, { useState } from "react";
import Home from "./pages/Home";
import Results from "./pages/Results";
import Documents from "./pages/Documents";

const NAV = [["dashboard", "Dashboard"], ["documents", "Documents"], ["history", "History"]];

export default function App() {
  const [docId, setDocId] = useState(null);
  const [view, setView] = useState("dashboard");

  const go = (v) => { setDocId(null); setView(v); };
  const open = (id) => setDocId(id);

  return (
    <div className="app-shell">
      <header className="topnav">
        <button className="brand" onClick={() => go("dashboard")} aria-label="ParseAnything home">
          <span className="brand-mark">P</span>
          <span>ParseAnything</span>
        </button>
        <nav className="nav-pills" aria-label="Primary">
          {NAV.map(([k, label]) => (
            <button key={k} className={!docId && view === k ? "on" : ""} onClick={() => go(k)}>{label}</button>
          ))}
        </nav>
        <span className="nav-tag">Document intelligence</span>
      </header>
      <main className="page">
        {docId ? (
          <Results docId={docId} onReset={() => go("dashboard")} />
        ) : view === "dashboard" ? (
          <Home onDone={open} onOpen={open} onSeeAll={() => setView("documents")} />
        ) : (
          <Documents mode={view} onOpen={open} />
        )}
      </main>
    </div>
  );
}
