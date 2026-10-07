import { useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";
import OutputViewer from "./OutputViewer";
import { figureUrl } from "../services/api";

// Rendered Markdown (tables, KaTeX display math for `$$ … $$`) with a raw toggle. Figure links point at the API.
export default function MarkdownViewer({ markdown, docId }) {
  const [raw, setRaw] = useState(false);
  const components = {
    img: ({ src = "", alt }) => (
      <img alt={alt} style={{ maxWidth: "100%" }} src={src.startsWith("figures/") ? figureUrl(docId, src.slice("figures/".length)) : src} />
    ),
  };
  return (
    <div>
      <button onClick={() => setRaw(!raw)}>{raw ? "Show rendered" : "Show raw Markdown"}</button>
      {raw ? (
        <OutputViewer output={markdown} />
      ) : (
        <div className="markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={components}>
            {markdown}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}
