"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Activity, ArrowRight, BarChart3, Database, FlaskConical, LoaderCircle, Users } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
type Counts = { patients: number; admissions: number; discharges: number; bed_assignments: number; bed_transfers: number; occupancy_snapshots: number; waiting_queue: number | null; bed_turnaround: number | null };
type Dataset = { run_id: string; hospital_name: string; started_at: string; completed_at: string | null; status: "generating" | "completed" | "failed"; scenario_name: string | null; record_counts: Counts };
type Library = { items: Dataset[]; total: number; pages: number };
type DashboardData = { totalRuns: number; exportedRows: number; occupancy: number | null; occupancyDate: string | null; recent: Dataset[] };

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, { cache: "no-store", credentials: "include" });
  if (!response.ok) throw new Error(`Request failed (${response.status}).`);
  return response.json();
}

function exportedRowCount(counts: Counts) {
  return [counts.patients, counts.admissions, counts.discharges, counts.bed_assignments, counts.bed_transfers, counts.occupancy_snapshots, counts.waiting_queue, counts.bed_turnaround]
    .reduce<number>((total, count) => total + (count ?? 0), 0);
}

export default function HomePage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const workspaces = await getJson<{ id: number }[]>("/api/v1/workspaces");
        if (!workspaces.length) {
          if (active) setData({ totalRuns: 0, exportedRows: 0, occupancy: null, occupancyDate: null, recent: [] });
          return;
        }
        const workspaceId = workspaces[0].id;
        const first = await getJson<Library>(`/api/v1/workspaces/${workspaceId}/datasets?page=1&page_size=100&sort=newest`);
        const pages: Library[] = [first];
        for (let start = 2; start <= first.pages; start += 4) {
          const batch = Array.from({ length: Math.min(4, first.pages - start + 1) }, (_, index) => start + index);
          pages.push(...await Promise.all(batch.map((page) => getJson<Library>(`/api/v1/workspaces/${workspaceId}/datasets?page=${page}&page_size=100&sort=newest`))));
        }
        const allRuns = pages.flatMap((page) => page.items);
        const completed = allRuns.filter((run) => run.status === "completed");
        const exportedRows = completed.reduce((total, run) => total + exportedRowCount(run.record_counts), 0);
        let occupancy: number | null = null;
        let occupancyDate: string | null = null;
        const latestCompleted = completed[0];
        if (latestCompleted) {
          const detail = await getJson<{ analytics_summary: { latest_occupancy_pct: number | null; latest_snapshot_date: string | null } }>(`/api/v1/generation-runs/${latestCompleted.run_id}/dataset`);
          occupancy = detail.analytics_summary.latest_occupancy_pct;
          occupancyDate = detail.analytics_summary.latest_snapshot_date;
        }
        if (active) setData({ totalRuns: completed.length, exportedRows, occupancy, occupancyDate, recent: allRuns.slice(0, 5) });
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : "Dashboard data could not be loaded.");
      } finally { if (active) setLoading(false); }
    }
    void load();
    return () => { active = false; };
  }, []);

  const cards = [
    { label: "Completed datasets", value: data?.totalRuns ?? 0, detail: "Saved generation runs", icon: Database, tone: "metric-icon-violet" },
    { label: "Operational rows", value: data?.exportedRows ?? 0, detail: "Known rows across completed runs", icon: Users, tone: "metric-icon-blue" },
    { label: "Latest occupancy", value: data?.occupancy == null ? "—" : `${data.occupancy.toFixed(1)}%`, detail: data?.occupancyDate ? `Snapshot · ${data.occupancyDate}` : "No occupancy snapshot available", icon: Activity, tone: "metric-icon-teal" },
  ];

  return <main className="page-content dashboard-page" id="main-content">
    <div className="dashboard-welcome-row">
      <div className="page-heading"><div><div className="page-kicker"><span className="kicker-line" /> SYNTHETIC DATA WORKSPACE</div><h1>Welcome to BedSynth AI</h1><p className="page-subtitle">Generate reproducible hospital operations datasets for research and model testing.</p></div></div>
      <Link href="/generate" className="button button-primary dashboard-primary-action"><FlaskConical size={18} /> Generate Dataset <ArrowRight size={16} /></Link>
    </div>

    {error && <div className="generator-alert generator-alert-error" role="alert">{error} <button type="button" onClick={() => window.location.reload()}>Retry</button></div>}
    {loading && <div className="generator-loading" role="status"><LoaderCircle className="generator-spin" size={18} /> Loading saved dataset summaries…</div>}

    <section className="section-block" aria-label="Dataset summary">
      <div className="snapshot-grid">
        {cards.map(({ label, value, detail, icon: Icon, tone }, index) => <motion.article className="metric-card" key={label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22, delay: index * 0.06 }}><div className="metric-top"><span className={`metric-icon ${tone}`}><Icon size={18} /></span><span className="metric-label">{label}</span></div><div className="metric-empty">{loading ? "…" : value}</div><p className="metric-foot">{detail}</p></motion.article>)}
      </div>
      <p className="dashboard-data-note">Row totals use saved counts from completed runs, exclude the separate bed inventory file, and omit historical optional tables whose counts are unavailable.</p>
    </section>

    <section className="section-block dashboard-recent" aria-labelledby="recent-runs-heading">
      <div className="section-title-row"><div><h2 id="recent-runs-heading">Recent generation activity</h2><p className="section-subtitle">Your latest saved runs and their current status.</p></div><Link href="/datasets" className="text-link">View all datasets <ArrowRight size={15} /></Link></div>
      {loading ? <div className="generator-loading"><LoaderCircle className="generator-spin" size={18} /> Loading recent runs…</div>
        : !data?.recent.length ? <div className="dashboard-empty"><Database size={22} /><h3>No datasets yet</h3><p>Configure a hospital, then generate your first synthetic dataset.</p><Link href="/generate" className="button button-primary">Open Generator <ArrowRight size={15} /></Link></div>
          : <div className="dashboard-run-list">{data.recent.map((run) => <Link className="dashboard-run-row" href={`/datasets/${run.run_id}`} key={run.run_id}><span className="dashboard-run-icon"><Database size={18} /></span><span className="dashboard-run-copy"><strong>{run.hospital_name}</strong><small>{run.scenario_name ?? "Scenario unavailable"} · {new Date(run.started_at).toLocaleString()}</small></span><span className={`generator-status generator-status-${run.status}`}>{run.status}</span><span className="dashboard-run-count">{run.record_counts.patients.toLocaleString()} patients</span><ArrowRight className="dashboard-run-arrow" size={16} /></Link>)}</div>}
    </section>

    <section className="dashboard-shortcuts" aria-label="Research tools">
      <Link href="/datasets" className="dashboard-shortcut"><span className="metric-icon metric-icon-violet"><Database size={19} /></span><span><strong>Dataset library</strong><small>Search, inspect, and export saved runs.</small></span><ArrowRight size={16} /></Link>
      <Link href="/analytics" className="dashboard-shortcut"><span className="metric-icon metric-icon-blue"><BarChart3 size={19} /></span><span><strong>Analytics</strong><small>Explore occupancy and patient flow.</small></span><ArrowRight size={16} /></Link>
    </section>
    <footer className="page-footer"><span>BedSynth AI · Synthetic data for research and optimization testing</span><span>Generated records are fictional</span></footer>
  </main>;
}
