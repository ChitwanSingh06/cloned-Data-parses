import { useState } from "react";
import { RecentList } from "../components/RecentDocuments";
import { forgetDocument, loadRecent } from "../lib/recent";

export default function Documents({ mode, onOpen }) {
  const [docs, setDocs] = useState(loadRecent());
  const history = mode === "history";
  const remove = (id) => { forgetDocument(id); setDocs(loadRecent()); };
  return (
    <>
      <section className="hero compact">
        <span className="eyebrow">{history ? "History" : "Library"}</span>
        <h1>{history ? "Everything you've parsed." : "Your documents."}</h1>
        <p>{history ? "Most recent first, from this browser." : "Open any previously parsed document to review its extraction."}</p>
      </section>
      <RecentList docs={docs} onOpen={onOpen} onRemove={remove} timeline={history} emptyText="Nothing parsed in this browser yet." />
    </>
  );
}
