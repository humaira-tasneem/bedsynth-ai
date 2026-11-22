"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Clock3, Database, Info, Users } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");
type Account = { id: number; email: string; role: "admin" | "user"; registered_at: string; completed_dataset_count: number; latest_generation_at: string | null };
type Counts = { patients: number; admissions: number; discharges: number; bed_assignments: number; bed_transfers: number; occupancy_snapshots: number; waiting_queue: number | null; bed_turnaround: number | null };
type Run = { run_id: string; hospital_name: string; status: "generating" | "completed" | "failed"; started_at: string; completed_at: string | null; scenario_name: string | null; configured_start_date: string | null; configured_end_date: string | null; target_admissions: number | null; target_occupancy_pct: number | null; seed: number; departments: string[]; record_counts: Counts };
type UserDetail = Account & { runs: Run[]; total_runs: number; page: number; page_size: number };
type Page = { items: Account[]; total: number; page: number; page_size: number; pages: number };

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1/admin/overview${path}`, { credentials: "include", cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.detail || "Unable to load user information.");
  return body as T;
}
function dateTime(value: string | null) { return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "Unavailable"; }
function shortRun(id: string) { return id.slice(0, 8); }

export default function UsersPage() {
  const [data, setData] = useState<Page | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [page, setPage] = useState(1);
  const [runPage, setRunPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");

  const loadUsers = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError("");
    try { setData(await request<Page>(`/users?page=${page}&page_size=20`, signal)); }
    catch (cause) { if (!signal?.aborted) setError(cause instanceof Error ? cause.message : "Users could not be loaded."); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [page]);
  useEffect(() => { const controller = new AbortController(); void loadUsers(controller.signal); return () => controller.abort(); }, [loadUsers]);

  const loadDetail = useCallback(async (userId: number, requestedPage: number, signal?: AbortSignal) => {
    setDetailLoading(true); setDetailError("");
    try { setDetail(await request<UserDetail>(`/users/${userId}?page=${requestedPage}&page_size=10`, signal)); }
    catch (cause) { if (!signal?.aborted) setDetailError(cause instanceof Error ? cause.message : "Generation history could not be loaded."); }
    finally { if (!signal?.aborted) setDetailLoading(false); }
  }, []);
  useEffect(() => { if (selectedId === null) { setDetail(null); return; } const controller = new AbortController(); void loadDetail(selectedId, runPage, controller.signal); return () => controller.abort(); }, [selectedId, runPage, loadDetail]);

  return <main className="page-content admin-users-page">
    <header className="page-heading"><div><span className="page-eyebrow"><Users size={15} /> ADMINISTRATION</span><h1>User Management</h1><p>Review registered accounts and their generation history. This page is read-only.</p></div></header>
    {error && <div className="users-state users-error" role="alert">{error}</div>}
    {loading ? <div className="users-state" role="status">Loading registered users…</div> : !error && data?.items.length === 0 ? <div className="users-state users-empty"><Users size={24} /><strong>No registered users yet</strong><span>Accounts will appear here after registration.</span></div> : !error && data && <>
      <section className="generator-card users-list-card" aria-labelledby="registered-users-heading">
        <div className="generator-card-header"><div><span className="users-heading-icon"><Users size={17} /></span><div><h2 id="registered-users-heading">Registered accounts</h2><p>{data.total} account{data.total === 1 ? "" : "s"}</p></div></div></div>
        <div className="users-table-wrap"><table className="users-overview-table"><thead><tr><th scope="col">Email</th><th scope="col">Role</th><th scope="col">Registered</th><th scope="col">Completed datasets</th><th scope="col">Latest generation</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead><tbody>{data.items.map((account) => <tr key={account.id} className={selectedId === account.id ? "users-row-selected" : ""}><td><strong>{account.email}</strong></td><td><span className={`users-role users-role-${account.role}`}>{account.role}</span></td><td>{dateTime(account.registered_at)}</td><td>{account.completed_dataset_count}</td><td>{dateTime(account.latest_generation_at)}</td><td><button className="users-view-button" type="button" aria-label={`View generation history for ${account.email}`} aria-pressed={selectedId === account.id} onClick={() => { setSelectedId(account.id); setRunPage(1); }}>View history</button></td></tr>)}</tbody></table></div>
        <div className="users-pagination"><span>Page {data.page} of {Math.max(1, data.pages)}</span><div><button type="button" aria-label="Previous users page" disabled={data.page <= 1} onClick={() => setPage((current) => current - 1)}><ChevronLeft size={16} /></button><button type="button" aria-label="Next users page" disabled={data.page >= data.pages} onClick={() => setPage((current) => current + 1)}><ChevronRight size={16} /></button></div></div>
      </section>
      {selectedId !== null && <section className="generator-card users-history-card" aria-labelledby="user-history-heading">
        <div className="generator-card-header"><div><span className="users-heading-icon"><Database size={17} /></span><div><h2 id="user-history-heading">Generation history</h2><p>{detail?.email ?? "Selected account"} · Metadata only</p></div></div><button className="users-view-button" type="button" onClick={() => { setSelectedId(null); setRunPage(1); }}>Close</button></div>
        {detailLoading && <div className="users-state" role="status">Loading generation history…</div>}
        {detailError && <div className="users-state users-error" role="alert">{detailError}</div>}
        {!detailLoading && !detailError && detail?.runs.length === 0 && <div className="users-state users-empty"><Clock3 size={22} /><strong>No generation history</strong><span>This account has no visible runs.</span></div>}
        {!detailLoading && !detailError && detail?.runs.map((run) => <article className="users-run" key={run.run_id}>
          <header><div><strong>{run.hospital_name}</strong><span>Run {shortRun(run.run_id)} · Scenario: {run.scenario_name ?? "Unavailable"}</span></div><span className={`users-run-status users-run-${run.status}`}>{run.status}</span></header>
          <dl><div><dt>Generation date</dt><dd>{dateTime(run.completed_at ?? run.started_at)}</dd></div><div><dt>Configured period</dt><dd>{run.configured_start_date && run.configured_end_date ? `${run.configured_start_date} – ${run.configured_end_date}` : "Unavailable"}</dd></div><div><dt>Target admissions</dt><dd>{run.target_admissions ?? "Unavailable"}</dd></div><div><dt>Target occupancy</dt><dd>{run.target_occupancy_pct === null ? "Unavailable" : `${run.target_occupancy_pct}%`}</dd></div><div><dt>Seed</dt><dd>{run.seed}</dd></div><div><dt>Departments</dt><dd>{run.departments.length ? run.departments.join(", ") : "Unavailable"}</dd></div></dl>
          <div className="users-record-counts" aria-label="Generation record counts">{([["Patients", run.record_counts.patients], ["Admissions", run.record_counts.admissions], ["Discharges", run.record_counts.discharges], ["Assignments", run.record_counts.bed_assignments], ["Transfers", run.record_counts.bed_transfers], ["Occupancy snapshots", run.record_counts.occupancy_snapshots], ["Waiting queue", run.record_counts.waiting_queue], ["Bed turnaround", run.record_counts.bed_turnaround]] as const).map(([label, value]) => <span key={label}><strong>{value ?? "Unavailable"}</strong>{label}</span>)}</div>
        </article>)}
        {detail && detail.total_runs > detail.page_size && <div className="users-pagination"><span>History page {detail.page} of {Math.ceil(detail.total_runs / detail.page_size)}</span><div><button type="button" aria-label="Previous history page" disabled={runPage <= 1} onClick={() => setRunPage((current) => current - 1)}><ChevronLeft size={16} /></button><button type="button" aria-label="Next history page" disabled={runPage >= Math.ceil(detail.total_runs / detail.page_size)} onClick={() => setRunPage((current) => current + 1)}><ChevronRight size={16} /></button></div></div>}
        <p className="users-privacy-note"><Info size={14} /> Run inspection includes configuration metadata and aggregate counts only. Patient-level records and exports are not shown.</p>
      </section>}
    </>}
  </main>;
}
