import React, { useState } from "react";
import Home from "./pages/Home";
import Results from "./pages/Results";

export default function App() {
  const [docId, setDocId] = useState(null);
  return (
    <main className="container">
      <h1>ParseAnything</h1>
      <p>Universal document ingestion engine</p>
      {docId ? <Results docId={docId} onReset={() => setDocId(null)} /> : <Home onDone={(id) => setDocId(id)} />}
    </main>
  );
}
