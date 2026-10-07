import React, { useState } from "react";
import ProcessingStatus from "./ProcessingStatus";
import { startParse, uploadDocument, waitForCompletion } from "../services/api";

export default function FileUpload({ onDone }) {
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  async function run() {
    setError("");
    try {
      setStatus("UPLOADING");
      const up = await uploadDocument(file);
      await startParse(up.file_id);
      const final = await waitForCompletion(up.file_id, (s) => setStatus(s.status));
      onDone(up.file_id, final);
    } catch (e) {
      setStatus("");
      setError(e.message);
    }
  }

  return (
    <section className="card">
      <h2>Upload Document</h2>
      <input type="file" accept=".pdf,.docx,.pptx,.xlsx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(e) => setFile(e.target.files?.[0] || null)} />
      {file && <p>Selected: {file.name}</p>}
      <button disabled={!file || ["UPLOADING", "QUEUED", "PROCESSING"].includes(status)} onClick={run}>Parse Document</button>
      <ProcessingStatus status={status} error={error} />
    </section>
  );
}
