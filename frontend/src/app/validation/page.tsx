"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, ArrowLeft, CheckCircle2, CircleAlert, LoaderCircle, RefreshCw, ShieldCheck } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
type Workspace = { id: number; name: string };
type Run = { run_id: string; hospital_id: number; status: string; started_at: string; patients_count: number; admissions_count: number };
type Issue = { category: string; severity: string; code: string; message: string; entity_type?: string | null; entity_id?: string | number | null };
type Category = { category: string; weight: number; checks_performed: number; checks_passed: number; checks_failed: number; issue_count: number; score: number };
type Report = { validation_id: string; run_id: string; validated_at: string; score: number; checks_performed: number; checks_passed: number; checks_failed: number; warning_count: number; status: string; categories: Category[]; issues: Issue[] };

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, { ...options, headers: { "Content-Type": "application/json", ...options.headers }, cache: "no-store" });
  if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail || `Request failed (${response.status})`); }
  return response.json();
}

export default function ValidationPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState("");
  const [history, setHistory] = useState<Report[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("bedsynth-theme");
    const useDark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    setDark(useDark); document.documentElement.dataset.theme = useDark ? "dark" : "light";
  }, []);

  const loadRuns = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const ws = await api<Workspace[]>("/workspaces"); setWorkspaces(ws);
      const all: Run[] = [];
      for (const workspace of ws) all.push(...await api<Run[]>(`/workspaces/${workspace.id}/generation-runs?limit=100`));
      all.sort((a, b) => b.started_at.localeCompare(a.started_at)); setRuns(all);
      if (all.length && !all.some((run) => run.run_id === runId)) setRunId(all[0].run_id);
      if (!all.length) { setRunId(""); setHistory([]); setReport(null); }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load generation runs."); }
    finally { setLoading(false); }
  }, [runId]);

  useEffect(() => { void loadRuns(); }, []); // initial load only

  const loadHistory = useCallback(async (id: string) => {
    if (!id) return;
    setHistoryLoading(true);
    try { const items = await api<Report[]>(`/generation-runs/${id}/validations`); setHistory(items); setReport(items[0] ?? null); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load validation history."); }
    finally { setHistoryLoading(false); }
  }, []);
  useEffect(() => { if (runId) void loadHistory(runId); }, [runId, loadHistory]);

  async function validate() {
    if (!runId) return; setWorking(true); setError(""); setSuccess("");
    try { const result = await api<Report>(`/generation-runs/${runId}/validations`, { method: "POST" }); setReport(result); setHistory((old) => [result, ...old]); setSuccess(`Validation completed with a score of ${result.score.toFixed(1)}.`); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Validation could not be completed."); }
    finally { setWorking(false); }
  }

  const selectedRun = useMemo(() => runs.find((run) => run.run_id === runId), [runs, runId]);
  const severityCounts = useMemo(() => Object.fromEntries(["critical", "high", "medium", "low"].map((severity) => [severity, report?.issues.filter((issue) => issue.severity === severity).length ?? 0])), [report]);
  return <main className="generator-page validation-page" id="main-content">
    <header className="generator-topbar"><Link href="/" className="generator-brand"><span className="generator-brand-mark"><Activity size={18} /></span><span>BedSynth <strong>AI</strong></span></Link><nav aria-label="Page navigation"><Link href="/generate" className="generator-nav-link"><ArrowLeft size={14} /> Generator</Link><Link href="/" className="generator-nav-link">Overview</Link><button type="button" className="validation-theme" onClick={() => { const next = !dark; setDark(next); document.documentElement.dataset.theme = next ? "dark" : "light"; window.localStorage.setItem("bedsynth-theme", next ? "dark" : "light"); }}>{dark ? "Light theme" : "Dark theme"}</button></nav></header>
    <div className="generator-content">
      <div className="generator-heading"><div><span className="generator-kicker"><ShieldCheck size={14} /> DATA QUALITY</span><h1>Validation</h1><p>Review operational integrity for a persisted synthetic generation run. Validation reads source records and stores a separate report.</p></div></div>
      {error && <div className="generator-alert generator-alert-error" role="alert"><CircleAlert size={16} />{error}</div>}
      {success && <div className="generator-alert generator-alert-success" role="status"><CheckCircle2 size={16} />{success}</div>}
      <section className="generator-card validation-controls" aria-labelledby="validation-run-heading"><div className="generator-card-header"><span className="generator-section-icon"><Activity size={18} /></span><div><h2 id="validation-run-heading">Generation run</h2><p>Choose a run to validate or review its saved reports.</p></div><button className="generator-refresh" type="button" onClick={() => void loadRuns()} aria-label="Refresh runs" disabled={loading}><RefreshCw size={16} /></button></div>
        <div className="validation-control-row"><label htmlFor="run-select">Run<select id="run-select" value={runId} onChange={(event) => setRunId(event.target.value)} disabled={loading || runs.length === 0}><option value="">Select a generation run</option>{runs.map((run) => <option value={run.run_id} key={run.run_id}>{run.run_id.slice(0, 8)} · Hospital {run.hospital_id} · {new Date(run.started_at).toLocaleString()} · {run.status}</option>)}</select></label><button className="generator-button generator-button-primary" type="button" onClick={() => void validate()} disabled={!runId || selectedRun?.status !== "completed" || working || loading}>{working ? <LoaderCircle className="generator-spin" size={16} /> : <ShieldCheck size={16} />}{working ? "Validating…" : "Run validation"}</button></div>
        {selectedRun && <p className="validation-run-meta">{selectedRun.admissions_count} admissions · Run <code>{selectedRun.run_id}</code>{selectedRun.status !== "completed" && " · Only completed runs can be validated."}</p>}
      </section>
      {loading ? <div className="generator-loading"><LoaderCircle className="generator-spin" />Loading generation runs…</div> : runs.length === 0 ? <div className="generator-empty"><span className="generator-empty-icon"><Activity size={21} /></span><h2>No generation runs</h2><p>Complete a generation run first. Its validation reports will appear here.</p><Link href="/generate" className="generator-button generator-button-primary">Open generator</Link></div> : <>
        {historyLoading ? <div className="generator-loading"><LoaderCircle className="generator-spin" />Loading validation history…</div> : report ? <>
          <section className="validation-score-grid" aria-label="Validation summary"><article className="generator-card validation-score-card"><span>QUALITY SCORE</span><strong>{report.score.toFixed(1)}<small>/100</small></strong><em className={`validation-status status-${report.status}`}>{report.status.replaceAll("_", " ")}</em></article><article className="generator-card validation-count-card"><span>CHECKS PASSED</span><strong>{report.checks_passed}<small> / {report.checks_performed}</small></strong><p>{report.checks_failed} failed · {report.warning_count} warnings</p></article><article className="generator-card validation-count-card"><span>ISSUES FOUND</span><strong>{report.issues.length}</strong><p>Saved {new Date(report.validated_at).toLocaleString()}</p></article></section>
          <section className="generator-card validation-severity-card" aria-label="Issue severity breakdown"><h2>Issue severity</h2><div>{Object.entries(severityCounts).map(([severity, count]) => <span key={severity} className={`validation-severity severity-${severity}`}>{severity} <strong>{count}</strong></span>)}</div></section>
          <section className="generator-card validation-results"><div className="generator-card-header"><span className="generator-section-icon"><CheckCircle2 size={18} /></span><div><h2>Category results</h2><p>Weighted rule-level results. Critical issues cap the score at 49.</p></div></div><div className="validation-category-list">{report.categories.map((item) => <div className="validation-category" key={item.category}><div><strong>{item.category.replaceAll("_", " ")}</strong><small>{item.checks_passed}/{item.checks_performed} checks · {item.issue_count} issues · weight {item.weight}%</small></div><strong>{item.score.toFixed(0)}%</strong><div className="validation-progress" role="progressbar" aria-label={`${item.category.replaceAll("_", " ")} score`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={item.score}><span style={{ width: `${item.score}%` }} /></div></div>)}</div></section>
          <section className="generator-card validation-results"><div className="generator-card-header"><span className="generator-section-icon"><CircleAlert size={18} /></span><div><h2>Issues</h2><p>Specific findings from this validation report.</p></div></div>{report.issues.length ? <div className="validation-issues">{report.issues.map((issue, index) => <article className="validation-issue" key={`${issue.code}-${index}`}><span className={`validation-severity severity-${issue.severity}`}>{issue.severity}</span><div><strong>{issue.code.replaceAll("_", " ")}</strong><p>{issue.message}</p>{issue.entity_type && <small>{issue.entity_type}{issue.entity_id !== null && issue.entity_id !== undefined ? ` · ${issue.entity_id}` : ""}</small>}</div></article>)}</div> : <div className="generator-history-empty">No issues were found in this report.</div>}</section>
        </> : <div className="generator-empty validation-no-report"><span className="generator-empty-icon"><ShieldCheck size={21} /></span><h2>No validation report yet</h2><p>Start a validation to evaluate this run. Stored records will not be changed.</p></div>}
        <section className="generator-card generator-history"><div className="generator-card-header"><span className="generator-section-icon"><RefreshCw size={17} /></span><div><h2>Validation history</h2><p>Saved reports for the selected generation run. Select a report to review it.</p></div></div>{history.length ? <div className="generator-table-wrap"><table className="generator-history-table"><thead><tr><th>Report</th><th>Validated</th><th>Score</th><th>Checks</th><th>Status</th></tr></thead><tbody>{history.map((item) => <tr key={item.validation_id}><td><button type="button" className="validation-history-select" onClick={() => setReport(item)} aria-label={`Review validation ${item.validation_id}`}>{item.validation_id.slice(0, 8)}</button></td><td>{new Date(item.validated_at).toLocaleString()}</td><td>{item.score.toFixed(1)}</td><td>{item.checks_passed}/{item.checks_performed}</td><td>{item.status.replaceAll("_", " ")}</td></tr>)}</tbody></table></div> : <div className="generator-history-empty">No validations have been recorded for this run.</div>}</section>
      </>}
      <div className="validation-footnote">Generation algorithms, model utility, and privacy risk are evaluated separately; this report checks operational consistency only.</div>
    </div>
  </main>;
}
