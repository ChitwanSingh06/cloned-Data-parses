import { useEffect, useState } from "react";
import FileUpload from "../components/FileUpload";
import { RecentList, StatCards } from "../components/RecentDocuments";
import { loadRecent } from "../lib/recent";

export default function Home({ onDone, onOpen, onSeeAll }) {
  const [recent, setRecent] = useState([]);
  useEffect(() => { setRecent(loadRecent()); }, []);
  return (
    <>
      <section className="hero">
        <span className="eyebrow">ParseAnything · Universal document ingestion</span>
        <h1>Turn documents into <em>structured data.</em></h1>
        <p>Upload a PDF, Word, PowerPoint or Excel file and get text, tables, JSON and Markdown — every block traced back to its source.</p>
      </section>
      <FileUpload onDone={onDone} />
      <StatCards docs={recent} />
      <div className="section-head">
        <h2>Recent documents</h2>
        {recent.length > 5 && <button className="link-btn" onClick={onSeeAll}>View all</button>}
      </div>
      <RecentList docs={recent.slice(0, 5)} onOpen={onOpen} emptyText="Documents you parse will appear here." />
    </>
  );
}
