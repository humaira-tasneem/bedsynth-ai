"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Activity, ArrowRight, BarChart3, Database, FlaskConical, LoaderCircle } from "lucide-react";
import MarketingLanding from "@/components/MarketingLanding";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
type Run = { run_id: string; hospital_name: string; started_at: string; status: string; scenario_name: string | null; record_counts: { patients: number; admissions: number } };
type Dashboard = { user_email: string; total_datasets: number; total_generated_records: number; latest_occupancy_pct: number | null; latest_occupancy_date: string | null; recent_runs: Run[] };

export default function HomePage() {
  const [access, setAccess] = useState<"checking" | "account" | "anonymous">("checking");
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    fetch(`${apiBase}/api/v1/auth/me`, { credentials: "include", cache: "no-store" }).then(async (response) => {
      if (response.ok) { if (active) setAccess("account"); return; }
      if (active) setAccess("anonymous");
    }).catch(() => { if (active) setAccess("anonymous"); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (access !== "account") return;
    let active = true;
    fetch(`${apiBase}/api/v1/dashboard/user`, { credentials: "include", cache: "no-store" })
      .then(async (response) => { if (!response.ok) throw new Error(response.status === 401 ? "Your session has expired. Sign in again." : "Dashboard data could not be loaded."); return response.json(); })
      .then((value) => { if (active) setData(value); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Dashboard data could not be loaded."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [access]);

  const cards = [
    { label: "Your datasets", value: data?.total_datasets ?? 0, detail: "Completed runs you own", icon: Database, tone: "metric-icon-violet" },
    { label: "Synthetic records", value: data?.total_generated_records.toLocaleString() ?? "0", detail: "Persisted operational rows; bed inventory excluded", icon: Activity, tone: "metric-icon-blue" },
    { label: "Latest occupancy", value: data?.latest_occupancy_pct == null ? "Unavailable" : `${data.latest_occupancy_pct.toFixed(1)}%`, detail: data?.latest_occupancy_date ? `Snapshot · ${data.latest_occupancy_date}` : "No saved occupancy snapshot", icon: BarChart3, tone: "metric-icon-teal" },
  ];

  if (access !== "account") return <MarketingLanding />;

  return <main className="page-content dashboard-page" id="main-content">
    <div className="dashboard-welcome-row"><div className="page-heading"><div><div className="page-kicker"><span className="kicker-line" /> RESEARCH WORKSPACE</div><h1>Welcome{data?.user_email ? `, ${data.user_email.split("@")[0]}` : " to BedSynth AI"}</h1><p className="page-subtitle">Create reproducible synthetic hospital operations datasets for research and model testing.</p></div></div><Link href="/generate" className="button button-primary dashboard-primary-action"><FlaskConical size={18} /> Generate Dataset <ArrowRight size={16} /></Link></div>
    {error && <div className="generator-alert generator-alert-error" role="alert">{error}<button type="button" onClick={() => window.location.reload()}>Retry</button></div>}
    {loading && <div className="generator-loading" role="status"><LoaderCircle className="generator-spin" size={18} /> Loading your research summary…</div>}
    <section className="section-block" aria-label="Your research summary"><div className="snapshot-grid">{cards.map(({ label, value, detail, icon: Icon, tone }, index) => <motion.article className="metric-card" key={label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22, delay: index * 0.06 }}><div className="metric-top"><span className={`metric-icon ${tone}`}><Icon size={18} /></span><span className="metric-label">{label}</span></div><div className="metric-empty">{loading ? "…" : value}</div><p className="metric-foot">{detail}</p></motion.article>)}</div></section>
    <section className="section-block dashboard-recent" aria-labelledby="recent-runs-heading"><div className="section-title-row"><div><h2 id="recent-runs-heading">Recent generation activity</h2><p className="section-subtitle">Your latest runs and their current status.</p></div><Link href="/datasets" className="text-link">View My Datasets <ArrowRight size={15} /></Link></div>
      {loading ? <div className="generator-loading"><LoaderCircle className="generator-spin" size={18} /> Loading your recent runs…</div> : !data?.recent_runs.length ? <div className="dashboard-empty"><Database size={22} /><h3>Your research workspace is ready</h3><p>Generate your first fictional dataset to see run activity and occupancy summaries here.</p><Link href="/generate" className="button button-primary">Open Generator <ArrowRight size={15} /></Link></div> : <div className="dashboard-run-list">{data.recent_runs.map((run) => <Link className="dashboard-run-row" href={`/datasets/${run.run_id}`} key={run.run_id}><span className="dashboard-run-icon"><Database size={18} /></span><span className="dashboard-run-copy"><strong>{run.hospital_name}</strong><small>{run.scenario_name ?? "Scenario unavailable"} · {new Date(run.started_at).toLocaleString()}</small></span><span className={`generator-status generator-status-${run.status}`}>{run.status}</span><span className="dashboard-run-count">{run.record_counts.admissions.toLocaleString()} admissions</span><ArrowRight className="dashboard-run-arrow" size={16} /></Link>)}</div>}
    </section>
    <section className="dashboard-shortcuts" aria-label="Research tools"><Link href="/datasets" className="dashboard-shortcut"><span className="metric-icon metric-icon-violet"><Database size={19} /></span><span><strong>My Datasets</strong><small>Inspect, compare, and export your saved runs.</small></span><ArrowRight size={16} /></Link><Link href="/analytics" className="dashboard-shortcut"><span className="metric-icon metric-icon-blue"><BarChart3 size={19} /></span><span><strong>My Analytics</strong><small>Explore occupancy and patient flow from your runs.</small></span><ArrowRight size={16} /></Link></section>
    <footer className="page-footer"><span>BedSynth AI · Synthetic data for research and optimization testing</span><span>Generated records are fictional</span></footer>
  </main>;
}
