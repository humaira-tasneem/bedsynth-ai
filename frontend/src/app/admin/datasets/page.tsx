"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { ArrowUpRight, Database, LoaderCircle, Search } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
type Run = { run_id: string; hospital_name: string; started_at: string; status: string; scenario_name: string | null; owner_email: string | null; deleted_at: string | null; record_counts: { patients: number; admissions: number; discharges: number; bed_assignments: number; bed_transfers: number; occupancy_snapshots: number; waiting_queue: number | null; bed_turnaround: number | null } };
type Result = { items: Run[]; total: number; page: number; pages: number };
const recordCount = (run: Run) => Object.values(run.record_counts).reduce<number>((total, value) => total + (value ?? 0), 0);

export default function AdminDatasetsPage() {
  const [search, setSearch] = useState(""); const [query, setQuery] = useState("");
  const [status, setStatus] = useState(""); const [ownership, setOwnership] = useState(""); const [includeDeleted, setIncludeDeleted] = useState(false);
  const [page, setPage] = useState(1); const [result, setResult] = useState<Result | null>(null); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    const params = new URLSearchParams({ page: String(page), page_size: "20" });
    if (query) params.set("q", query); if (status) params.set("status", status); if (ownership) params.set("ownership", ownership); if (includeDeleted) params.set("include_deleted", "true");
    fetch(`${apiBase}/api/v1/admin/datasets?${params}`, { credentials: "include", cache: "no-store", signal: controller.signal })
      .then(async (response) => { if (!response.ok) throw new Error(response.status === 403 ? "Administrator access is required." : "Platform datasets could not be loaded."); return response.json(); })
      .then((value) => { if (!controller.signal.aborted) setResult(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Platform datasets could not be loaded."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [page, query, status, ownership, includeDeleted]);
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setPage(1); setQuery(search.trim()); }

  return <main className="page-content admin-dataset-page" id="main-content">
    <div className="dashboard-welcome-row"><div className="page-heading"><div><div className="page-kicker"><span className="kicker-line" /> PLATFORM DATASETS</div><h1>All Datasets</h1><p className="page-subtitle">Search generation runs across workspaces, including historical runs with no recorded owner.</p></div></div></div>
    <section className="generator-card dataset-filters admin-dataset-filters" aria-label="Platform dataset filters">
      <form className="dataset-search" onSubmit={submit}><label htmlFor="admin-dataset-search">Search runs</label><div><Search size={15} aria-hidden="true" /><input id="admin-dataset-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Hospital, run ID, or creator" maxLength={120} /><button type="submit">Search</button></div></form>
      <label>Status<select value={status} onChange={(event) => { setPage(1); setStatus(event.target.value); }}><option value="">All statuses</option><option value="completed">Completed</option><option value="generating">Generating</option><option value="failed">Failed</option></select></label>
      <label>Ownership<select value={ownership} onChange={(event) => { setPage(1); setOwnership(event.target.value); }}><option value="">All runs</option><option value="owned">Owned runs</option><option value="historical">Historical unowned</option></select></label>
      <label className="admin-deleted-toggle"><input type="checkbox" checked={includeDeleted} onChange={(event) => { setPage(1); setIncludeDeleted(event.target.checked); }} /> Include soft-deleted</label>
    </section>
    {error && <div className="generator-alert generator-alert-error" role="alert">{error}</div>}
    <section className="generator-card dataset-library-card" aria-label="Platform generation runs">
      <div className="generator-card-header"><span className="generator-section-icon"><Database size={18} /></span><div><h2>Generation runs</h2><p>{result?.total ?? 0} platform-wide records · Deleted runs are hidden by default.</p></div><span className="dataset-total">{result?.total ?? 0}</span></div>
      {loading ? <div className="generator-loading" role="status"><LoaderCircle className="generator-spin" /> Loading platform runs…</div> : !result?.items.length ? <div className="generator-empty dataset-empty"><Database size={20} /><h2>No runs found</h2><p>Change the filters or wait for a generation run to be saved.</p></div> : <><div className="dataset-run-list">{result.items.map((run) => <article className="dataset-run-card" key={run.run_id}>
        <div className="dataset-run-main"><Link href={`/datasets/${run.run_id}`}>Run {run.run_id.slice(0, 8)}</Link><small>{run.scenario_name ?? "Scenario unavailable"} · {new Date(run.started_at).toLocaleString()}</small></div>
        <div className="dataset-run-meta"><strong>{run.hospital_name}</strong><span>Creator: {run.owner_email ?? "Historical · unavailable"}</span></div>
        <div className="dataset-run-meta"><strong>{recordCount(run).toLocaleString()} records</strong><span>{run.record_counts.admissions.toLocaleString()} admissions</span></div>
        <span className={`generator-status generator-status-${run.status}`}>{run.status}</span>
        {run.deleted_at && <span className="dataset-deleted-label">Soft deleted</span>}
        <Link href={`/datasets/${run.run_id}`} className="generator-button generator-button-secondary">View details <ArrowUpRight size={14} /></Link>
      </article>)}</div><div className="dataset-pagination"><span>Page {result.page} of {result.pages || 1} · {result.total} total</span><div><button type="button" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1}>Previous</button><button type="button" onClick={() => setPage((value) => Math.min(result.pages, value + 1))} disabled={page >= result.pages}>Next</button></div></div></>}
    </section>
    <footer className="dataset-footer"><span>Platform-wide access is limited to administrators.</span><span>Soft deletion preserves stored records.</span></footer>
  </main>;
}
