import React, { useRef, useState } from "react";
import ProcessingStatus from "./ProcessingStatus";
import { startParse, uploadDocument, waitForCompletion } from "../services/api";

export default function FileUpload({ onDone }) {
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const inputRef = useRef(null);
  const busy = ["UPLOADING", "QUEUED", "PROCESSING"].includes(status);

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

  const onDrop = (e) => {
    e.preventDefault(); setDrag(false);
    if (busy) return;
    const f = e.dataTransfer?.files?.[0];
    if (f) setFile(f);
  };

  return (
    <section className="card upload-card">
      <div
        className={`dropzone ${drag ? "drag" : ""} ${file ? "has-file" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => !busy && inputRef.current?.click()}
        role="button" tabIndex={0}
        onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !busy) { e.preventDefault(); inputRef.current?.click(); } }}
      >
        <div className="drop-ico" aria-hidden="true">↑</div>
        <h2>{file ? file.name : "Drop a document here"}</h2>
        <p className="muted">{file ? "Ready to parse." : "or click to browse · PDF, DOCX, PPTX, XLSX, or an image (PNG, JPG, TIFF…)"}</p>
        <input ref={inputRef} hidden type="file" accept=".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.gif,image/*,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(e) => setFile(e.target.files?.[0] || null)} />
      </div>
      <div className="upload-actions">
        <button className="btn primary" disabled={!file || busy} onClick={run}>Parse Document</button>
        <ProcessingStatus status={status} error={error} />
      </div>
    </section>
  );
}
