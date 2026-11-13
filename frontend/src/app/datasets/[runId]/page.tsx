"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Activity, ArrowLeft, Download, FileJson2, FileSpreadsheet, LoaderCircle, Search, ShieldCheck } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const entities = [
  { id: "patients", label: "Patients", count: "patients" },
  { id: "admissions", label: "Admissions", count: "admissions" },
  { id: "discharges", label: "Discharges", count: "discharges" },
  { id: "bed_assignments", label: "Bed assignments", count: "bed_assignments" },
  { id: "bed_transfers", label: "Bed transfers", count: "bed_transfers" },
  { id: "occupancy_snapshots", label: "Occupancy snapshots", count: "occupancy_snapshots" },
] as const;
type Entity = (typeof entities)[number]["id"];
type Counts = { patients: number; admissions: number; discharges: number; bed_assignments: number; bed_transfers: number; occupancy_snapshots: number };
type ValidationReport = { validation_id: string; validated_at: string; score: number; status: string; checks_performed: number; checks_passed: number; checks_failed: number };
type Department = { department_id: number; code: string; name: string };
type Dataset = {
  run_id: string; workspace_id: number; hospital_id: number; hospital_name: string; started_at: string; completed_at: string | null;
  status: string; seed: number; configured_start_date: string | null; configured_end_date: string | null;
  target_occupancy_pct: number | null; generator_version: string | null; record_counts: Counts;
  latest_validation: ValidationReport | null; generation_config: Record<string, unknown>;
  selected_departments: Department[]; validation_reports: ValidationReport[];
  analytics_summary: { latest_snapshot_date: string | null; latest_occupancy_pct: number | null; average_occupancy_pct: number | null; peak_occupancy_pct: number | null; occupied_beds_latest: number | null; available_beds_latest: number | null; recorded_days: number };
};
type Preview = { run_id: string; entity: Entity; columns: { key: string; label: string }[]; items: Record<string, unknown>[]; total: number; page: number; page_size: number; pages: number };

async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, { cache: "no-store", signal });
  if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail || `Request failed (${response.status}).`); }
  return response.json();
}

function displayValue(key: string, value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if ((key.endsWith("_at") || key === "created_at") && typeof value === "string") return new Date(value).toLocaleString();
  if (key === "occupancy_pct" && typeof value === "number") return `${value.toFixed(2)}%`;
  return String(value);
}

export default function DatasetDetailPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [entity, setEntity] = useState<Entity>("patients");
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [error, setError] = useState("");
  const [previewError, setPreviewError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    api<Dataset>(`/generation-runs/${runId}/dataset`, controller.signal).then((result) => {
      if (!controller.signal.aborted) setDataset(result);
    }).catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Dataset details could not be loaded."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [runId]);

  useEffect(() => {
    const controller = new AbortController();
    setPreviewLoading(true); setPreviewError("");
    const params = new URLSearchParams({ page: String(page), page_size: "25" });
    if (query) params.set("q", query);
    api<Preview>(`/generation-runs/${runId}/dataset/preview/${entity}?${params}`, controller.signal).then((result) => {
      if (!controller.signal.aborted) setPreview(result);
    }).catch((cause) => { if (!controller.signal.aborted) setPreviewError(cause instanceof Error ? cause.message : "Dataset preview could not be loaded."); })
      .finally(() => { if (!controller.signal.aborted) setPreviewLoading(false); });
    return () => controller.abort();
  }, [runId, entity, page, query]);

  function applySearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setPage(1); setQuery(search.trim());
  }

  const config = dataset?.generation_config ?? {};
  const requestConfig = (config.request && typeof config.request === "object" ? config.request : {}) as Record<string, unknown>;
  const counts = dataset?.record_counts;
  const reportLabel = useMemo(() => dataset?.latest_validation ? `${dataset.latest_validation.score.toFixed(1)} / 100 · ${dataset.latest_validation.status.replaceAll("_", " ")}` : "No validation report", [dataset]);

  return <main className="generator-page dataset-page" id="main-content">
    <header className="generator-topbar"><Link href="/datasets" className="generator-brand"><span className="generator-brand-mark"><FileSpreadsheet size={18} /></span><span>BedSynth <strong>AI</strong></span></Link><nav aria-label="Dataset detail navigation"><Link href="/datasets" className="generator-nav-link"><ArrowLeft size={14} /> Dataset library</Link><Link href="/validation" className="generator-nav-link">Validation <ShieldCheck size={13} /></Link></nav></header>
    <div className="dataset-content">
      {loading ? <div className="generator-loading"><LoaderCircle className="generator-spin" />Loading dataset details…</div>
        : error ? <div className="generator-empty"><span className="generator-empty-icon"><FileSpreadsheet size={20} /></span><h2>Dataset unavailable</h2><p>{error}</p><Link href="/datasets" className="generator-button generator-button-secondary">Back to dataset library</Link></div>
        : dataset && <>
          <div className="dataset-heading"><div><span className="generator-kicker"><FileSpreadsheet size={14} /> DATASET DETAILS</span><h1>{dataset.hospital_name}</h1><p>Generation run <code>{dataset.run_id}</code> · Workspace {dataset.workspace_id}</p></div><div className="dataset-export-actions"><a className="generator-button generator-button-secondary" href={`${apiBase}/api/v1/generation-runs/${runId}/dataset/manifest`}><FileJson2 size={15} /> Download manifest</a><span className={`generator-status generator-status-${dataset.status}`}>{dataset.status}</span></div></div>

          <section className="generator-card dataset-config-card" aria-labelledby="dataset-config-title"><div className="generator-card-header"><span className="generator-section-icon"><Activity size={18} /></span><div><h2 id="dataset-config-title">Generation configuration</h2><p>Persisted run configuration and lifecycle information.</p></div></div><div className="dataset-config-grid">
            <div><span>Hospital</span><strong>{dataset.hospital_name}</strong></div><div><span>Seed</span><strong>{dataset.seed}</strong></div><div><span>Configured dates</span><strong>{dataset.configured_start_date ?? "—"} – {dataset.configured_end_date ?? "—"}</strong></div><div><span>Target occupancy</span><strong>{dataset.target_occupancy_pct === null ? "—" : `${dataset.target_occupancy_pct}%`}</strong></div><div><span>Target admissions</span><strong>{String(requestConfig.target_admissions ?? "—")}</strong></div><div><span>Generation version</span><strong>{dataset.generator_version ?? "Not recorded"}</strong></div><div><span>Started</span><strong>{new Date(dataset.started_at).toLocaleString()}</strong></div><div><span>Completed</span><strong>{dataset.completed_at ? new Date(dataset.completed_at).toLocaleString() : "—"}</strong></div>
            <div className="dataset-config-departments"><span>Resolved departments</span><strong>{dataset.selected_departments.length ? dataset.selected_departments.map((department) => `${department.name} (${department.code})`).join(", ") : "Not recorded"}</strong></div>
            <div className="dataset-config-raw"><span>Generation metadata</span><pre>{JSON.stringify(config, null, 2)}</pre></div>
          </div></section>

          <section className="dataset-count-grid" aria-label="Persisted entity counts">{entities.map((item) => <article className="generator-card dataset-count-card" key={item.id}><span>{item.label}</span><strong>{counts?.[item.count] ?? 0}</strong></article>)}</section>

          <section className="dataset-analytics" aria-label="Run occupancy summary">
            <article className="generator-card dataset-count-card"><span>Latest occupancy</span><strong>{dataset.analytics_summary.latest_occupancy_pct === null ? "—" : `${dataset.analytics_summary.latest_occupancy_pct.toFixed(2)}%`}</strong><small>{dataset.analytics_summary.latest_snapshot_date ?? "No snapshots"}</small></article>
            <article className="generator-card dataset-count-card"><span>Average occupancy</span><strong>{dataset.analytics_summary.average_occupancy_pct === null ? "—" : `${dataset.analytics_summary.average_occupancy_pct.toFixed(2)}%`}</strong><small>Recorded snapshot days</small></article>
            <article className="generator-card dataset-count-card"><span>Peak occupancy</span><strong>{dataset.analytics_summary.peak_occupancy_pct === null ? "—" : `${dataset.analytics_summary.peak_occupancy_pct.toFixed(2)}%`}</strong><small>{dataset.analytics_summary.recorded_days} recorded days</small></article>
            <article className="generator-card dataset-count-card"><span>Latest occupied / available</span><strong>{dataset.analytics_summary.occupied_beds_latest === null ? "—" : `${dataset.analytics_summary.occupied_beds_latest} / ${dataset.analytics_summary.available_beds_latest}`}</strong><small>From latest snapshot day</small></article>
          </section>

          <section className="generator-card dataset-validation-card"><div className="generator-card-header"><span className="generator-section-icon"><ShieldCheck size={18} /></span><div><h2>Validation reports</h2><p>Saved quality checks associated with this generation run.</p></div><strong className="dataset-validation-summary">{reportLabel}</strong></div>{dataset.validation_reports.length ? <div className="generator-table-wrap"><table className="generator-history-table"><thead><tr><th>Report ID</th><th>Validated</th><th>Score</th><th>Checks passed</th><th>Status</th></tr></thead><tbody>{dataset.validation_reports.map((report) => <tr key={report.validation_id}><td className="generator-run-id">{report.validation_id}</td><td>{new Date(report.validated_at).toLocaleString()}</td><td>{report.score.toFixed(1)}</td><td>{report.checks_passed}/{report.checks_performed}</td><td>{report.status.replaceAll("_", " ")}</td></tr>)}</tbody></table></div> : <div className="generator-history-empty">No validation reports are associated with this run.</div>}</section>

          <section className="generator-card dataset-preview-card" aria-labelledby="dataset-preview-title"><div className="generator-card-header"><span className="generator-section-icon"><DatabaseIcon /></span><div><h2 id="dataset-preview-title">Dataset preview</h2><p>Read-only paginated records from this run. No operational records are editable here.</p></div><a className="generator-button generator-button-secondary dataset-tab-export" href={`${apiBase}/api/v1/generation-runs/${runId}/dataset/export/${entity}`}><Download size={14} /> Export {entities.find((item) => item.id === entity)?.label} CSV</a></div>
            <div className="dataset-tab-row" role="tablist" aria-label="Dataset entity previews">{entities.map((item) => <button type="button" key={item.id} role="tab" aria-selected={entity === item.id} className={entity === item.id ? "dataset-tab dataset-tab-active" : "dataset-tab"} onClick={() => { setEntity(item.id); setPage(1); setQuery(""); setSearch(""); }}>{item.label}<span>{counts?.[item.count] ?? 0}</span></button>)}</div>
            <div className="dataset-preview-tools"><form className="dataset-search dataset-preview-search" onSubmit={applySearch}><label htmlFor="preview-search">Search {entities.find((item) => item.id === entity)?.label.toLowerCase()}</label><div><Search size={15} aria-hidden="true" /><input id="preview-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search records" maxLength={120} /><button type="submit">Search</button></div></form><span>{preview?.total ?? 0} matching records</span></div>
            {previewError && <div className="generator-alert generator-alert-error" role="alert">{previewError}</div>}
            {previewLoading ? <div className="generator-loading"><LoaderCircle className="generator-spin" />Loading records…</div>
              : preview && preview.items.length ? <><div className="generator-table-wrap dataset-preview-table-wrap"><table className="generator-history-table dataset-preview-table"><thead><tr>{preview.columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{preview.items.map((row, rowIndex) => <tr key={String(row.id ?? `${page}-${rowIndex}`)}>{preview.columns.map((column) => <td key={column.key} title={String(row[column.key] ?? "")}>{displayValue(column.key, row[column.key])}</td>)}</tr>)}</tbody></table></div><div className="dataset-pagination"><span>Page {preview.page} of {preview.pages} · {preview.total} records</span><div><button type="button" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1}>Previous</button><button type="button" onClick={() => setPage((value) => Math.min(preview.pages, value + 1))} disabled={page >= preview.pages}>Next</button></div></div></>
              : <div className="generator-history-empty">No {entities.find((item) => item.id === entity)?.label.toLowerCase()} match this selection.</div>}
          </section>
          <p className="dataset-manifest-note">The manifest reports the generation and schema versions that were actually persisted. This run does not record a dataset schema version, so the manifest does not claim full reproducibility.</p>
        </>}
    </div>
  </main>;
}

function DatabaseIcon() { return <FileSpreadsheet size={18} />; }
