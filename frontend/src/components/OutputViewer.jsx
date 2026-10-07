// Raw text viewer used for both the Markdown and the JSON tab.
export default function OutputViewer({ output }) {
  const text = typeof output === "string" ? output : JSON.stringify(output, null, 2);
  return <pre className="output">{text}</pre>;
}
