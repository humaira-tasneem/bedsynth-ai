"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Activity, ArrowLeft, ArrowUpRight, Database, LoaderCircle, Search, SlidersHorizontal } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
type Workspace = { id: number; name: string };
type Hospital = { id: number; name: string; code: string };
type Counts = { patients: number; admissions: number; discharges: number; bed_assignments: number; bed_transfers: number; occupancy_snapshots: number };
type Dataset = {
  run_id: string; workspace_id: number; hospital_id: number; hospital_name: string; started_at: string;
  completed_at: string | null; status: "generating" | "completed" | "failed"; seed: number;
  configured_start_date: string | null; configured_end_date: string | null; target_occupancy_pct: number | null;
  generator_version: string | null; record_counts: Counts;
  latest_validation: { validation_id: string; validated_at: string; score: number; status: string } | null;
};
type Library = { items: Dataset[]; total: number; page: number; page_size: number; pages: number };

async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, { cache: "no-store", signal });
  if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail || `Request failed (${response.status}).`); }
  return response.json();
}

export default function DatasetsPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [hospitals, setHospitals] = useState<Hospital[]>([]);
  const [hospitalId, setHospitalId] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("newest");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [library, setLibrary] = useState<Library | null>(null);
  const [loadingWorkspaces, setLoadingWorkspaces] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    api<Workspace[]>("/workspaces", controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setWorkspaces(items); setWorkspaceId(String(items[0]?.id ?? ""));
    }).catch((cause) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Workspaces could not be loaded.");
    }).finally(() => { if (!controller.signal.aborted) setLoadingWorkspaces(false); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!workspaceId) { setHospitals([]); setHospitalId(""); return; }
    const controller = new AbortController();
    api<Hospital[]>(`/workspaces/${workspaceId}/hospitals`, controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setHospitals(items);
      setHospitalId((current) => current && items.some((hospital) => String(hospital.id) === current) ? current : "");
    }).catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Hospitals could not be loaded."); });
    return () => controller.abort();
  }, [workspaceId]);

  useEffect(() => {
    if (!workspaceId) { setLibrary(null); return; }
    const controller = new AbortController();
    async function load() {
      setLoading(true); setError("");
      const params = new URLSearchParams({ page: String(page), page_size: "10", sort });
      if (query) params.set("q", query);
      if (hospitalId) params.set("hospital_id", hospitalId);
      if (status) params.set("status", status);
      try { setLibrary(await api<Library>(`/workspaces/${workspaceId}/datasets?${params}`, controller.signal)); }
      catch (cause) { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Datasets could not be loaded."); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, [workspaceId, hospitalId, status, sort, query, page]);

  function applySearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setPage(1); setQuery(search.trim());
  }

  const countLabel = useMemo(() => library ? `${library.total} dataset${library.total === 1 ? "" : "s"}` : "Datasets", [library]);
  const noWorkspaces = !loadingWorkspaces && workspaces.length === 0;

  return <main className="generator-page dataset-page" id="main-content">
    <header className="generator-topbar"><Link href="/" className="generator-brand"><span className="generator-brand-mark"><Database size={18} /></span><span>BedSynth <strong>AI</strong></span></Link><nav aria-label="Dataset navigation"><Link href="/" className="generator-nav-link"><ArrowLeft size={14} /> Overview</Link><Link href="/generate" className="generator-nav-link">Generator <ArrowUpRight size={13} /></Link><Link href="/analytics" className="generator-nav-link">Analytics <ArrowUpRight size={13} /></Link></nav></header>
    <div className="dataset-content">
      <div className="dataset-heading"><div><span className="generator-kicker"><Database size={14} /> DATASET LIBRARY</span><h1>Datasets</h1><p>Browse generated runs, review validation status, and preview or export persisted synthetic records.</p></div><Link href="/generate" className="generator-button generator-button-primary">Generate dataset <ArrowUpRight size={14} /></Link></div>

      <section className="generator-card dataset-filters" aria-label="Dataset filters">
        <label>Workspace<select value={workspaceId} onChange={(event) => { setWorkspaceId(event.target.value); setPage(1); }} disabled={loadingWorkspaces || !workspaces.length}><option value="">Select workspace</option>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select></label>
        <label>Hospital<select value={hospitalId} onChange={(event) => { setHospitalId(event.target.value); setPage(1); }} disabled={!workspaceId}><option value="">All hospitals</option>{hospitals.map((hospital) => <option key={hospital.id} value={hospital.id}>{hospital.name}</option>)}</select></label>
        <label>Status<select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="">All statuses</option><option value="completed">Completed</option><option value="generating">Generating</option><option value="failed">Failed</option></select></label>
        <label>Sort by<select value={sort} onChange={(event) => { setSort(event.target.value); setPage(1); }}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label>
        <form className="dataset-search" onSubmit={applySearch}><label htmlFor="dataset-search">Search datasets</label><div><Search size={15} aria-hidden="true" /><input id="dataset-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Hospital or run ID" maxLength={120} /><button type="submit">Search</button></div></form>
      </section>
      {error && <div className="generator-alert generator-alert-error" role="alert">{error}</div>}

      {loadingWorkspaces || loading ? <div className="generator-loading"><LoaderCircle className="generator-spin" />Loading datasets…</div>
        : noWorkspaces ? <div className="generator-empty"><span className="generator-empty-icon"><Database size={20} /></span><h2>No workspace available</h2><p>Create a workspace and generate a dataset before opening the library.</p></div>
        : <section className="generator-card dataset-library-card" aria-labelledby="dataset-list-title">
          <div className="generator-card-header"><span className="generator-section-icon"><Database size={18} /></span><div><h2 id="dataset-list-title">Generation runs</h2><p>{countLabel} in the selected workspace. Records from other workspaces are not shown.</p></div><span className="dataset-total">{library?.total ?? 0}</span></div>
          {!library?.items.length ? <div className="generator-empty dataset-empty"><span className="generator-empty-icon"><SlidersHorizontal size={19} /></span><h2>{query || status || hospitalId ? "No datasets match these filters" : "No datasets yet"}</h2><p>{query || status || hospitalId ? "Adjust or clear the filters to see more generation runs." : "Generate a synthetic run to add a dataset to this workspace."}</p>{!query && !status && !hospitalId && <Link href="/generate" className="generator-button generator-button-primary">Open generator</Link>}</div>
            : <><div className="generator-table-wrap"><table className="generator-history-table dataset-table"><thead><tr><th>Dataset / run</th><th>Hospital</th><th>Generated</th><th>Configured period</th><th>Status</th><th>Seed</th><th>Patients</th><th>Admissions</th><th>Discharges</th><th>Assignments</th><th>Transfers</th><th>Snapshots</th><th>Validation</th></tr></thead><tbody>{library.items.map((item) => <tr key={item.run_id}><td><Link href={`/datasets/${item.run_id}`} className="dataset-run-link"><span>{item.run_id.slice(0, 8)}</span><small>{item.generator_version ?? "Generator version unavailable"}</small></Link></td><td>{item.hospital_name}</td><td>{new Date(item.started_at).toLocaleString()}</td><td>{item.configured_start_date ?? "—"} – {item.configured_end_date ?? "—"}</td><td><span className={`generator-status generator-status-${item.status}`}>{item.status}</span></td><td>{item.seed}</td><td>{item.record_counts.patients}</td><td>{item.record_counts.admissions}</td><td>{item.record_counts.discharges}</td><td>{item.record_counts.bed_assignments}</td><td>{item.record_counts.bed_transfers}</td><td>{item.record_counts.occupancy_snapshots}</td><td>{item.latest_validation ? <span className={`dataset-validation dataset-validation-${item.latest_validation.status}`}>{item.latest_validation.score.toFixed(1)} · {item.latest_validation.status.replaceAll("_", " ")}</span> : <span className="dataset-validation-missing">Not validated</span>}</td></tr>)}</tbody></table></div>
              <div className="dataset-pagination"><span>Page {library.page} of {library.pages || 1} · {library.total} total</span><div><button type="button" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1}>Previous</button><button type="button" onClick={() => setPage((value) => Math.min(library.pages, value + 1))} disabled={page >= library.pages}>Next</button></div></div></>}
        </section>}
      <footer className="dataset-footer"><span>Only persisted synthetic records are listed and exported.</span><span><Activity size={13} /> Workspace-scoped data access</span></footer>
    </div>
  </main>;
}
