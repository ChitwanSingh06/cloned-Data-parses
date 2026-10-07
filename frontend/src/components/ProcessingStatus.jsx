export default function ProcessingStatus({ status, error }) {
  if (error) return <div className="status error">Error: {error}</div>;
  const busy = status && ["UPLOADING", "QUEUED", "PROCESSING"].includes(status);
  return (
    <div className={`status ${busy ? "busy" : ""}`}>
      {busy && <span className="spinner" />} {status || "Waiting"}
    </div>
  );
}
