export default function ConfidenceBadge({ confidence = 0, level, status }) {
  const lvl = level || (confidence >= 0.85 ? "HIGH" : confidence >= 0.6 ? "MEDIUM" : "LOW");
  return (
    <span className={`confidence ${lvl.toLowerCase()}`} title={status}>
      {Math.round(confidence * 100)}% {lvl}
      {status === "REVIEW_REQUIRED" && " ⚠ review"}
    </span>
  );
}
