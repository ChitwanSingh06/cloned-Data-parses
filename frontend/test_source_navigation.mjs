import fs from "node:fs";

const results = fs.readFileSync("src/pages/Results.jsx", "utf8");
const viewer = fs.readFileSync("src/components/SourceViewer.jsx", "utf8");
const search = fs.readFileSync("src/components/SearchPanel.jsx", "utf8");

for (const token of ["doc.format === \"pdf\"", "<SourceViewer doc={doc} selected={selected} onPageChange={setPage} />"]) {
  if (!results.includes(token)) throw new Error(`Results navigation contract missing: ${token}`);
}
for (const token of ["doc.format === \"pptx\"", "doc.format === \"xlsx\"", "doc.format === \"docx\"", "Slide {info.page_number}", "source-cell-selected", "docx-paragraph-", "docx-table-", "docx-image-"]) {
  if (!viewer.includes(token)) throw new Error(`SourceViewer contract missing: ${token}`);
}
if (!search.includes("h.provenance?.sources?.[0]?.source_type")) throw new Error("Search provenance contract missing");
console.log("format-aware source navigation static checks passed");
