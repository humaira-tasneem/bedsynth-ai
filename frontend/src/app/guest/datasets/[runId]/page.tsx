"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2, Download, LoaderCircle, ShieldCheck } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const files = ["patients", "admissions", "discharges", "bed_assignments", "bed_transfers", "occupancy_snapshots", "waiting_queue", "bed_turnaround", "bed_inventory"];
type Dataset = { run_id: string; hospital_name: string; status: string; scenario_name: string | null; started_at: string; completed_at: string | null; seed: number; configured_start_date: string | null; configured_end_date: string | null; record_counts: Record<string, number | null> };

export default function GuestDatasetPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [validation, setValidation] = useState("");
  const [validating, setValidating] = useState(false);
  useEffect(() => {
    let active = true;
    fetch(`${apiBase}/api/v1/guest/generation-runs/${runId}/dataset`, { credentials: "include", cache: "no-store" })
      .then(async (response) => { const body = await response.json().catch(() => null); if (!response.ok) throw new Error(body?.detail ?? "This temporary dataset is unavailable."); return body as Dataset; })
      .then((body) => { if (active) setDataset(body); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Dataset could not be loaded."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [runId]);

  async function validateDataset() {
    setValidating(true); setValidation("");
    try {
      const response = await fetch(`${apiBase}/api/v1/guest/generation-runs/${runId}/validations`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" } });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "Validation could not be completed.");
      setValidation(`Validation ${body.status.replaceAll("_", " ")} · ${body.checks_passed}/${body.checks_performed} checks passed.`);
    } catch (cause) { setValidation(cause instanceof Error ? cause.message : "Validation could not be completed."); }
    finally { setValidating(false); }
  }

  return <main className="page-content" id="main-content">
    <header className="section-title-row"><div><div className="page-kicker"><span className="kicker-line" /> TEMPORARY DATASET</div><h1>Guest dataset</h1><p className="section-subtitle">Review and download your generated synthetic operations data.</p></div><Link href="/generate" className="button button-secondary"><ArrowLeft size={16} /> Generator</Link></header>
    <div className="generator-alert generator-alert-info" role="status"><ShieldCheck size={18} /><span>This dataset belongs to your temporary guest session and expires when that session expires. Create an account if you need permanent dataset history.</span></div>
    {loading && <div className="generator-loading" role="status"><LoaderCircle className="generator-spin" size={20} /> Loading dataset…</div>}
    {error && <div className="generator-alert generator-alert-error" role="alert">{error}</div>}
    {dataset && <>
      <section className="generator-card guest-dataset-summary"><div className="generator-card-header"><span className="generator-section-icon"><CheckCircle2 size={18} /></span><div><h2>{dataset.hospital_name}</h2><p>{dataset.scenario_name ?? "Scenario unavailable"} · {dataset.configured_start_date ?? "Date unavailable"} – {dataset.configured_end_date ?? "Date unavailable"}</p></div></div><dl className="guest-dataset-facts"><div><dt>Generation run</dt><dd className="generator-mono">{dataset.run_id}</dd></div><div><dt>Seed</dt><dd>{dataset.seed}</dd></div><div><dt>Status</dt><dd>{dataset.status}</dd></div><div><dt>Admissions</dt><dd>{dataset.record_counts.admissions ?? "Unavailable"}</dd></div><div><dt>Patients</dt><dd>{dataset.record_counts.patients ?? "Unavailable"}</dd></div><div><dt>Discharges</dt><dd>{dataset.record_counts.discharges ?? "Unavailable"}</dd></div></dl></section>
      <section className="generator-card guest-download-card"><div className="generator-card-header"><span className="generator-section-icon"><Download size={18} /></span><div><h2>Download dataset files</h2><p>CSV exports preserve the run’s original generated records.</p></div></div><div className="guest-download-grid">{files.map((file) => <a key={file} className="button button-secondary" href={`${apiBase}/api/v1/guest/generation-runs/${runId}/dataset/export/${file}`}><Download size={15} /> {file.replaceAll("_", " ")}.csv</a>)}<a className="button button-secondary" href={`${apiBase}/api/v1/guest/generation-runs/${runId}/dataset/manifest`}><Download size={15} /> Export manifest</a></div></section>
      <section className="generator-card guest-validation-card"><div className="generator-card-header"><span className="generator-section-icon"><CheckCircle2 size={18} /></span><div><h2>Data quality validation</h2><p>Run the existing validation engine on this generated dataset.</p></div><button className="button button-primary" type="button" disabled={validating} onClick={validateDataset}>{validating ? "Validating…" : "Validate dataset"}</button></div>{validation && <p className="generator-inline-success" role="status">{validation}</p>}</section>
      <p className="guest-account-prompt">Want to keep datasets in a permanent library? <Link href="/register" className="text-link">Create an account</Link> or <Link href="/login" className="text-link">sign in</Link>.</p>
    </>}
  </main>;
}
