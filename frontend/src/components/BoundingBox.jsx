// Draws a PDF-point bbox over a page image using percentages, so it scales with the image.
export default function BoundingBox({ bbox, pageWidth, pageHeight, label, active = true }) {
  if (!bbox || !pageWidth || !pageHeight) return <span className="bbox">No bounding box</span>;
  const [x0, y0, x1, y1] = bbox;
  const style = {
    left: `${(x0 / pageWidth) * 100}%`,
    top: `${(y0 / pageHeight) * 100}%`,
    width: `${((x1 - x0) / pageWidth) * 100}%`,
    height: `${((y1 - y0) / pageHeight) * 100}%`,
  };
  return (
    <div className={`bbox-overlay ${active ? "active" : ""}`} style={style} title={label}>
      {label && <span className="bbox-label">{label}</span>}
    </div>
  );
}
