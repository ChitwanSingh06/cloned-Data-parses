import { downloadUrl } from "../services/api";

export default function DownloadButtons({ docId }) {
  if (!docId) return null;
  return (
    <div>
      <a className="btn" href={downloadUrl(docId, "json")} download="document.json">Download JSON</a>
      <a className="btn" href={downloadUrl(docId, "markdown")} download="document.md">Download Markdown</a>
    </div>
  );
}
