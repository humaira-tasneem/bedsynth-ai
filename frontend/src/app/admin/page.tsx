"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Activity, ArrowRight, BarChart3, Building2, Database, LoaderCircle, UserRoundCog, Users } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");
type ActivityItem = { run_id: string; hospital_name: string; owner_email: string | null; started_at: string; status: string; scenario_name: string | null; record_count: number };
type Summary = { total_registered_users: number; active_users: number; shared_hospitals: number; departments: number; beds: number; generation_runs: number; generated_records: number; recent_activity: ActivityItem[] };

export default function AdminDashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    fetch(`${apiBase}/api/v1/admin/dashboard`, { credentials: "include", cache: "no-store" })
      .then(async (response) => { if (!response.ok) throw new Error(response.status === 403 ? "Administrator access is required." : "Platform summary could not be loaded."); return response.json(); })
      .then((value) => { if (active) setSummary(value); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Platform summary could not be loaded."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const metrics = [
    { label: "Registered users", value: summary?.total_registered_users, detail: `${summary?.active_users ?? 0} active accounts`, icon: Users, tone: "metric-icon-violet" },
    { label: "Shared hospitals", value: summary?.shared_hospitals, detail: "Available in shared workspaces", icon: Building2, tone: "metric-icon-blue" },
    { label: "Departments", value: summary?.departments, detail: "Active departments in shared hospitals", icon: Activity, tone: "metric-icon-teal" },
    { label: "Beds", value: summary?.beds, detail: "Non-retired beds in shared hospitals", icon: Building2, tone: "metric-icon-purple" },
    { label: "Generation runs", value: summary?.generation_runs, detail: "Non-deleted platform runs", icon: Database, tone: "metric-icon-blue" },
    { label: "Generated records", value: summary?.generated_records?.toLocaleString(), detail: "Persisted operational rows; bed inventory excluded", icon: BarChart3, tone: "metric-icon-teal" },
  ];

  return <main className="page-content dashboard-page admin-dashboard-page" id="main-content">
    <div className="dashboard-welcome-row"><div className="page-heading"><div><div className="page-kicker"><span className="kicker-line" /> PLATFORM ADMINISTRATION</div><h1>Admin Dashboard</h1><p className="page-subtitle">Monitor shared hospital configuration, accounts, and synthetic generation activity.</p></div></div><Link href="/admin/datasets" className="button button-primary dashboard-primary-action"><Database size={17} /> Review all datasets <ArrowRight size={16} /></Link></div>
    {error && <div className="generator-alert generator-alert-error" role="alert">{error} <button type="button" onClick={() => window.location.reload()}>Retry</button></div>}
    {loading && <div className="generator-loading" role="status"><LoaderCircle className="generator-spin" size={18} /> Loading platform summary…</div>}
    <section className="section-block" aria-label="Platform metrics"><div className="admin-metric-grid">{metrics.map(({ label, value, detail, icon: Icon, tone }, index) => <motion.article className="metric-card" key={label} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24, delay: index * 0.045 }}><div className="metric-top"><span className={`metric-icon ${tone}`}><Icon size={18} /></span><span className="metric-label">{label}</span></div><div className="metric-empty">{loading ? "…" : value ?? 0}</div><p className="metric-foot">{detail}</p></motion.article>)}</div></section>
    <section className="admin-quick-actions" aria-label="Platform management shortcuts">
      <Link href="/users" className="dashboard-shortcut"><span className="metric-icon metric-icon-violet"><UserRoundCog size={19} /></span><span><strong>Manage users</strong><small>Review accounts and workspace sharing.</small></span><ArrowRight size={16} /></Link>
      <Link href="/hospitals" className="dashboard-shortcut"><span className="metric-icon metric-icon-blue"><Building2 size={19} /></span><span><strong>Manage hospitals</strong><small>Configure shared hospitals, departments, and beds.</small></span><ArrowRight size={16} /></Link>
      <Link href="/users" className="dashboard-shortcut"><span className="metric-icon metric-icon-purple"><Building2 size={19} /></span><span><strong>Share workspaces</strong><small>Control which workspaces users can access.</small></span><ArrowRight size={16} /></Link>
      <Link href="/admin/datasets" className="dashboard-shortcut"><span className="metric-icon metric-icon-blue"><Database size={19} /></span><span><strong>View all datasets</strong><small>Search runs across the platform.</small></span><ArrowRight size={16} /></Link>
      <Link href="/analytics" className="dashboard-shortcut"><span className="metric-icon metric-icon-teal"><BarChart3 size={19} /></span><span><strong>Platform analytics</strong><small>Review operational results across accessible runs.</small></span><ArrowRight size={16} /></Link>
    </section>
    <section className="section-block dashboard-recent" aria-labelledby="platform-activity-heading"><div className="section-title-row"><div><h2 id="platform-activity-heading">Recent platform activity</h2><p className="section-subtitle">Latest non-deleted generation runs across workspaces.</p></div><Link href="/admin/datasets" className="text-link">View all runs <ArrowRight size={15} /></Link></div>
      {loading ? <div className="generator-loading"><LoaderCircle className="generator-spin" size={18} /> Loading recent activity…</div> : !summary?.recent_activity.length ? <div className="dashboard-empty"><Activity size={22} /><h3>No generation activity yet</h3><p>Completed and in-progress generation runs will appear here.</p></div> : <div className="dashboard-run-list">{summary.recent_activity.map((run) => <Link className="dashboard-run-row" href={`/datasets/${run.run_id}`} key={run.run_id}><span className="dashboard-run-icon"><Database size={18} /></span><span className="dashboard-run-copy"><strong>{run.hospital_name}</strong><small>{run.scenario_name ?? "Scenario unavailable"} · {run.owner_email ?? "Historical run · creator unavailable"} · {new Date(run.started_at).toLocaleString()}</small></span><span className={`generator-status generator-status-${run.status}`}>{run.status}</span><span className="dashboard-run-count">{run.record_count.toLocaleString()} records</span><ArrowRight className="dashboard-run-arrow" size={16} /></Link>)}</div>}
    </section>
    <footer className="page-footer"><span>BedSynth AI · Platform administration</span><span>Generated records are fictional</span></footer>
  </main>;
}
