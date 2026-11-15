"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity, ArrowLeft, ArrowUpRight, BarChart3, BedDouble, Building2,
  CalendarDays, CircleAlert, LoaderCircle, Moon, RefreshCw, Sun, GitCompareArrows,
} from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const TEAL = "#0f766e";
const CYAN = "#0e7490";
const NAVY = "#54708c";
const GRID = "#dbe4ed";
const SCENARIOS: { id: Scenario; name: string }[] = [
  { id: "normal_operations", name: "Normal Operations" },
  { id: "high_patient_inflow", name: "High Patient Inflow" },
  { id: "seasonal_disease_surge", name: "Seasonal Disease Surge" },
  { id: "emergency_surge", name: "Emergency Surge" },
  { id: "low_occupancy", name: "Low Occupancy" },
];

type Workspace = { id: number };
type Department = { id: number; name: string; code: string };
type Hospital = { id: number; workspace_id: number; name: string; code: string; is_archived: boolean; departments: (Department & { is_archived: boolean })[] };
type Metadata = {
  hospital_id: number; hospital_name: string; run_id: string | null; run_started_at: string | null;
  seed: number | null; department_id: number | null; department_name: string | null;
  scenario: string | null; scenario_name: string | null; patient_profile: Record<string, unknown> | null;
  start_date: string | null; end_date: string | null; time_zone: "UTC"; snapshot_cadence: string; has_data: boolean;
};
type Overview = { metadata: Metadata; insights: Insight[]; metrics: {
  operational_beds: number; occupied_beds_latest: number | null; available_beds_latest: number | null;
  latest_occupancy_pct: number | null; latest_occupancy_date: string | null; departments_reporting_latest: number;
  departments_expected: number; average_occupancy_pct: number | null; peak_occupancy_pct: number | null; lowest_occupancy_pct: number | null; average_length_of_stay_hours: number | null;
  admissions: number; discharges: number; transfers: number; occupancy_snapshots: number;
} };
type Occupancy = { metadata: Metadata; items: { date: string; operational_beds: number; occupied_beds: number; available_beds: number; occupancy_pct: number | null; departments_reporting: number; snapshot_count: number }[] };
type Flow = { metadata: Metadata; items: { date: string; admissions: number; discharges: number; transfers: number }[] };
type DepartmentMetric = { department_id: number; department_name: string; department_code: string; operational_beds: number; occupied_beds_latest: number | null; available_beds_latest: number | null; latest_occupancy_pct: number | null; average_occupancy_pct: number | null; peak_occupancy_pct: number | null; lowest_occupancy_pct: number | null; snapshots: number; admissions: number; admission_share_pct: number | null; incoming_transfers: number; outgoing_transfers: number; daily_occupancy: { date: string; occupancy_pct: number | null }[] };
type TransferRoute = { source_department_id: number; source_department_name: string; destination_department_id: number; destination_department_name: string; transfers: number };
type Utilization = { metadata: Metadata; items: DepartmentMetric[]; transfer_routes: TransferRoute[] };
type Scenario = "normal_operations" | "high_patient_inflow" | "seasonal_disease_surge" | "emergency_surge" | "low_occupancy";
type RunOption = { run_id: string; hospital_id: number; hospital_name: string; started_at: string; completed_at: string; start_date: string | null; end_date: string | null; scenario: Scenario | null; scenario_name: string | null; seed: number; patient_profile: Record<string, unknown> | null; patients_count: number; admissions_count: number; departments: { id: number; name: string; code: string }[] };
type ComparedRun = { run_id: string; hospital_name: string; start_date: string | null; end_date: string | null; scenario: Scenario | null; scenario_name: string | null; patient_profile: Record<string, unknown> | null; seed: number; patients: number; admissions: number; discharges: number; transfers: number; average_occupancy_pct: number | null; peak_occupancy_pct: number | null; lowest_occupancy_pct: number | null; average_length_of_stay_hours: number | null; metrics_vs_baseline: Record<string, { absolute_difference: number | null; percentage_change: number | null }>; departments: DepartmentMetric[]; transfer_routes: TransferRoute[]; occupancy_trend: Occupancy["items"] };
type Comparison = { baseline_run_id: string; items: ComparedRun[] };
type Insight = { kind: string; text: string; source: "calculated_rule"; metrics: Record<string, string | number | null> };

async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, { cache: "no-store", signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Request failed (${response.status}).`);
  }
  return response.json();
}
async function postApi<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(payload?.detail || `Request failed (${response.status}).`);
  return payload as T;
}

function percent(value: number | null | undefined) { return value === null || value === undefined ? "—" : `${value.toFixed(1)}%`; }
function shortDate(value: string) { return new Date(`${value}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" }); }
function queryString(start: string, end: string, department: string, runId: string, scenario: string) {
  const params = new URLSearchParams();
  if (start && end) { params.set("start_date", start); params.set("end_date", end); }
  if (department) params.set("department_id", department);
  if (runId) params.set("run_id", runId);
  if (scenario) params.set("scenario", scenario);
  return params.size ? `?${params.toString()}` : "";
}

export default function AnalyticsPage() {
  const [hospitals, setHospitals] = useState<Hospital[]>([]);
  const [hospitalId, setHospitalId] = useState("");
  const [runs, setRuns] = useState<RunOption[]>([]);
  const [runId, setRunId] = useState("");
  const [scenario, setScenario] = useState("");
  const [comparisonRunIds, setComparisonRunIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState("");
  const [insights, setInsights] = useState<Insight[]>([]);
  const [departmentId, setDepartmentId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [appliedStart, setAppliedStart] = useState("");
  const [appliedEnd, setAppliedEnd] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [occupancy, setOccupancy] = useState<Occupancy | null>(null);
  const [flow, setFlow] = useState<Flow | null>(null);
  const [utilization, setUtilization] = useState<Utilization | null>(null);
  const [loadingHospitals, setLoadingHospitals] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filterError, setFilterError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [dark, setDark] = useState(false);
  const selectedHospital = useMemo(() => hospitals.find((hospital) => String(hospital.id) === hospitalId), [hospitals, hospitalId]);

  useEffect(() => {
    const saved = window.localStorage.getItem("bedsynth-theme");
    const useDark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    setDark(useDark); document.documentElement.dataset.theme = useDark ? "dark" : "light";
  }, []);

  useEffect(() => {
    if (!hospitalId) { setRuns([]); setRunId(""); setComparison(null); return; }
    const controller = new AbortController();
    async function loadRuns() {
      try {
        const result = await api<{ items: RunOption[] }>(`/analytics/hospitals/${hospitalId}/runs`, controller.signal);
        if (controller.signal.aborted) return;
        setRuns(result.items);
        setComparisonRunIds((current) => current.filter((selected) => result.items.some((run) => run.run_id === selected)));
        setRunId((current) => result.items.some((run) => run.run_id === current) ? current : "");
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Generation runs could not be loaded.");
      }
    }
    void loadRuns();
    return () => controller.abort();
  }, [hospitalId, refreshKey]);

  useEffect(() => {
    const controller = new AbortController();
    async function loadHospitals() {
      setLoadingHospitals(true); setError("");
      try {
        const workspaces = await api<Workspace[]>("/workspaces", controller.signal);
        const results = await Promise.all(workspaces.map((workspace) => api<Hospital[]>(`/workspaces/${workspace.id}/hospitals`, controller.signal)));
        const available = results.flat().filter((hospital) => !hospital.is_archived);
        setHospitals(available);
        setHospitalId((current) => current && available.some((hospital) => String(hospital.id) === current) ? current : String(available[0]?.id ?? ""));
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Hospitals could not be loaded.");
      } finally { if (!controller.signal.aborted) setLoadingHospitals(false); }
    }
    void loadHospitals();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!hospitalId) { setOverview(null); setOccupancy(null); setFlow(null); setUtilization(null); setInsights([]); return; }
    const controller = new AbortController();
    async function loadAnalytics() {
      setLoading(true); setError("");
      const query = queryString(appliedStart, appliedEnd, departmentId, runId, scenario);
      try {
        const [summary, trend, patientFlow, departments] = await Promise.all([
          api<Overview>(`/analytics/hospitals/${hospitalId}/overview${query}`, controller.signal),
          api<Occupancy>(`/analytics/hospitals/${hospitalId}/occupancy${query}`, controller.signal),
          api<Flow>(`/analytics/hospitals/${hospitalId}/patient-flow${query}`, controller.signal),
          api<Utilization>(`/analytics/hospitals/${hospitalId}/departments${query}`, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        setOverview(summary); setOccupancy(trend); setFlow(patientFlow); setUtilization(departments); setInsights(summary.insights ?? []);
        if (!appliedStart && !appliedEnd && !runId && !scenario && summary.metadata.start_date && summary.metadata.end_date) {
          setStartDate(summary.metadata.start_date); setEndDate(summary.metadata.end_date);
          setAppliedStart(summary.metadata.start_date); setAppliedEnd(summary.metadata.end_date);
        }
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Analytics could not be loaded.");
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void loadAnalytics();
    return () => controller.abort();
  }, [hospitalId, departmentId, appliedStart, appliedEnd, runId, scenario, refreshKey]);

  function changeHospital(value: string) {
    setHospitalId(value); setDepartmentId(""); setRunId(""); setScenario(""); setStartDate(""); setEndDate(""); setAppliedStart(""); setAppliedEnd(""); setFilterError(""); setComparison(null); setComparisonRunIds([]);
  }

  function changeRun(value: string) {
    setRunId(value); setScenario(""); setDepartmentId(""); setStartDate(""); setEndDate(""); setAppliedStart(""); setAppliedEnd(""); setFilterError("");
  }

  function changeScenario(value: string) {
    setScenario(value); setRunId(""); setDepartmentId(""); setStartDate(""); setEndDate(""); setAppliedStart(""); setAppliedEnd(""); setFilterError("");
  }

  function toggleComparisonRun(id: string) {
    setComparisonError(""); setComparison(null);
    setComparisonRunIds((current) => current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id]);
  }

  async function compareRuns() {
    if (comparisonRunIds.length < 2) { setComparisonError("Select at least two completed runs to compare."); return; }
    setComparisonLoading(true); setComparisonError("");
    try {
      const result = await postApi<Comparison>("/analytics/runs/compare", {
        run_ids: comparisonRunIds,
        baseline_run_id: comparisonRunIds[0],
        ...(appliedStart && appliedEnd ? { start_date: appliedStart, end_date: appliedEnd } : {}),
        ...(departmentId ? { department_id: Number(departmentId) } : {}),
      });
      setComparison(result);
    } catch (cause) {
      setComparisonError(cause instanceof Error ? cause.message : "Run comparison could not be calculated.");
      setComparison(null);
    } finally { setComparisonLoading(false); }
  }

  function applyFilters() {
    setFilterError("");
    if (Boolean(startDate) !== Boolean(endDate)) { setFilterError("Choose both a start date and an end date."); return; }
    if (startDate && endDate && startDate > endDate) { setFilterError("End date must be on or after the start date."); return; }
    setAppliedStart(startDate); setAppliedEnd(endDate);
  }

  const metrics = overview?.metrics;
  const departmentOptions = utilization && utilization.metadata.hospital_id === selectedHospital?.id
    ? utilization.items.map((item) => ({ id: item.department_id, name: item.department_name }))
    : selectedHospital?.departments.filter((department) => !department.is_archived).map((department) => ({ id: department.id, name: department.name })) ?? [];
  const noHospitals = !loadingHospitals && hospitals.length === 0;
  const hasRun = Boolean(overview?.metadata.run_id);
  const latestCoverage = metrics ? `${metrics.departments_reporting_latest} of ${metrics.departments_expected} departments reporting at latest snapshot` : "";
  const departmentTrend = useMemo(() => {
    const days = new Map<string, Record<string, string | number | null>>();
    for (const department of utilization?.items ?? []) for (const point of department.daily_occupancy) {
      const row = days.get(point.date) ?? { date: point.date };
      row[String(department.department_id)] = point.occupancy_pct;
      days.set(point.date, row);
    }
    return [...days.values()].sort((left, right) => String(left.date).localeCompare(String(right.date)));
  }, [utilization]);
  const comparisonTrend = useMemo(() => {
    const days = new Map<string, Record<string, string | number | null>>();
    for (const run of comparison?.items ?? []) for (const point of run.occupancy_trend) {
      const row = days.get(point.date) ?? { date: point.date };
      row[run.run_id] = point.occupancy_pct;
      days.set(point.date, row);
    }
    return [...days.values()].sort((left, right) => String(left.date).localeCompare(String(right.date)));
  }, [comparison]);

  return <main className="generator-page analytics-page" id="main-content">
    <header className="generator-topbar">
      <Link href="/" className="generator-brand"><span className="generator-brand-mark"><Activity size={18} /></span><span>BedSynth <strong>AI</strong></span></Link>
      <nav aria-label="Workspace navigation" className="analytics-topbar"><Link href="/" className="generator-nav-link"><ArrowLeft size={14} /> Overview</Link><Link href="/generate" className="generator-nav-link">Generator <ArrowUpRight size={13} /></Link><Link href="/validation" className="generator-nav-link">Validation <ArrowUpRight size={13} /></Link><button type="button" className="validation-theme" onClick={() => { const next = !dark; setDark(next); document.documentElement.dataset.theme = next ? "dark" : "light"; window.localStorage.setItem("bedsynth-theme", next ? "dark" : "light"); }} aria-label={`Switch to ${dark ? "light" : "dark"} theme`}>{dark ? <Sun size={15} /> : <Moon size={15} />}</button></nav>
    </header>

    <div className="analytics-content">
      <div className="analytics-heading"><div><span className="generator-kicker"><BarChart3 size={14} /> HOSPITAL PERFORMANCE</span><h1>Analytics</h1><p>Explore occupancy, patient flow, and department utilization from persisted synthetic operations records.</p></div><button type="button" className="generator-button generator-button-secondary" onClick={() => setRefreshKey((key) => key + 1)} disabled={loading || loadingHospitals}><RefreshCw size={15} className={loading ? "generator-spin" : ""} /> Refresh</button></div>

      <section className="generator-card analytics-filters" aria-label="Analytics filters">
        <label><span><Building2 size={14} /> Hospital</span><select value={hospitalId} onChange={(event) => changeHospital(event.target.value)} disabled={loadingHospitals || !hospitals.length}><option value="">Select a hospital</option>{hospitals.map((hospital) => <option key={hospital.id} value={hospital.id}>{hospital.name}</option>)}</select></label>
        <label><span><Activity size={14} /> Generation run</span><select value={runId} onChange={(event) => changeRun(event.target.value)} disabled={!runs.length}><option value="">Latest matching run</option>{runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.scenario_name ?? "Run"} · {run.run_id.slice(0, 8)} · {run.completed_at.slice(0, 10)}</option>)}</select></label>
        <label><span><BarChart3 size={14} /> Scenario</span><select value={scenario} onChange={(event) => changeScenario(event.target.value)} disabled={!hospitalId}><option value="">All scenarios</option>{SCENARIOS.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label><span><BedDouble size={14} /> Department</span><select value={departmentId} onChange={(event) => setDepartmentId(event.target.value)} disabled={!selectedHospital}><option value="">All departments</option>{departmentOptions.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>
        <label><span><CalendarDays size={14} /> Start date</span><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} disabled={!hospitalId} /></label>
        <label><span><CalendarDays size={14} /> End date</span><input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} disabled={!hospitalId} /></label>
        <button type="button" className="generator-button generator-button-primary" onClick={applyFilters} disabled={!hospitalId || loading}><Activity size={15} /> Apply filters</button>
      </section>
      <section className="generator-card analytics-compare-picker" aria-label="Generation run comparison">
        <div className="generator-card-header"><span className="generator-section-icon"><GitCompareArrows size={17} /></span><div><h2>Compare generation runs</h2><p>Select two or more completed runs from this hospital. The first selected run is the baseline; runs must share a department scope.</p></div><button type="button" className="generator-button generator-button-secondary" onClick={() => void compareRuns()} disabled={comparisonLoading || comparisonRunIds.length < 2}><GitCompareArrows size={14} />{comparisonLoading ? "Comparing…" : `Compare ${comparisonRunIds.length || "selected"}`}</button></div>
        {runs.length ? <div className="analytics-run-options">{runs.map((run) => <label key={run.run_id} className="analytics-run-option"><input type="checkbox" checked={comparisonRunIds.includes(run.run_id)} onChange={() => toggleComparisonRun(run.run_id)} disabled={!comparisonRunIds.includes(run.run_id) && comparisonRunIds.length >= 10} /><span><strong>{run.scenario_name ?? "Generation run"}</strong><small>{run.start_date ?? "Unknown start"} – {run.end_date ?? "Unknown end"} · {run.admissions_count} admissions · seed {run.seed}</small><code>{run.run_id.slice(0, 8)}</code></span></label>)}</div> : <p className="analytics-run-empty">Completed generation runs will appear here when available.</p>}
        {comparisonError && <p className="analytics-compare-error" role="alert">{comparisonError}</p>}
      </section>
      {filterError && <div className="generator-alert generator-alert-error" role="alert"><CircleAlert size={16} />{filterError}</div>}
      {error && <div className="generator-alert generator-alert-error" role="alert"><CircleAlert size={16} />{error}<button type="button" className="analytics-inline-action" onClick={() => setRefreshKey((key) => key + 1)}>Try again</button></div>}

      {comparison && <section className="analytics-comparison-results" aria-label="Generation run comparison results">
        <div className="analytics-period"><div><strong>Run comparison</strong><span>Absolute and percentage differences use the first selected run as baseline. Patient counts are whole-run totals; event and occupancy metrics follow the selected comparison period.</span></div><button type="button" className="analytics-inline-action" onClick={() => setComparison(null)}>Clear comparison</button></div>
        <div className="analytics-run-summary-grid">{comparison.items.map((run) => <article key={run.run_id} className="generator-card analytics-run-summary"><span>{run.scenario_name ?? "Scenario unavailable"}</span><strong>{run.hospital_name}</strong><small>{run.start_date ?? "Unknown start"} – {run.end_date ?? "Unknown end"} · seed {run.seed}</small><small>Age profile: {run.patient_profile ? JSON.stringify(run.patient_profile.age_distribution ?? {}) : "Unavailable"}</small><small>Gender profile: {run.patient_profile ? JSON.stringify(run.patient_profile.gender_distribution ?? {}) : "Unavailable"}</small></article>)}</div>
        <section className="analytics-chart-grid analytics-comparison-charts" aria-label="Run comparison charts">
          <ChartCard title="Admissions by run" subtitle="Persisted admission events in the selected comparison period." empty={!comparison.items.some((run) => run.admissions > 0)}><ResponsiveContainer width="100%" height="100%"><BarChart data={comparison.items} margin={{ top: 8, right: 12, left: 0, bottom: 4 }} accessibilityLayer><CartesianGrid stroke={GRID} strokeDasharray="3 5" vertical={false} /><XAxis dataKey="scenario_name" tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 9 }} interval={0} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} width={38} /><Tooltip contentStyle={tooltipStyle} /><Bar dataKey="admissions" name="Admissions" fill={TEAL} radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></ChartCard>
          <ChartCard title="Occupancy trend by run" subtitle="Persisted daily rates; run periods may not overlap." empty={!comparisonTrend.length}><ResponsiveContainer width="100%" height="100%"><LineChart data={comparisonTrend} margin={{ top: 8, right: 12, left: 0, bottom: 4 }} accessibilityLayer><CartesianGrid stroke={GRID} strokeDasharray="3 5" vertical={false} /><XAxis dataKey="date" tickFormatter={shortDate} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} minTickGap={22} /><YAxis domain={[0, 100]} unit="%" tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} width={42} /><Tooltip labelFormatter={(value) => shortDate(String(value))} formatter={(value) => [percent(typeof value === "number" ? value : null), "Occupancy"]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 9 }} />{comparison.items.map((run, index) => <Line key={run.run_id} type="monotone" dataKey={run.run_id} name={run.scenario_name ?? run.run_id.slice(0, 8)} stroke={[TEAL, CYAN, "#7c3aed", "#c2410c", "#2563eb", "#be185d"][index % 6]} strokeWidth={2} dot={false} connectNulls={false} />)}</LineChart></ResponsiveContainer></ChartCard>
        </section>
        <div className="generator-card analytics-department-table"><div className="generator-card-header"><span className="generator-section-icon"><GitCompareArrows size={17} /></span><div><h2>Comparison metrics</h2><p>Differences are relative to the baseline. Percentage change is unavailable when baseline is zero or a metric is missing.</p></div></div><div className="generator-table-wrap"><table className="generator-history-table"><thead><tr><th>Scenario / run</th><th>Patients</th><th>Admissions</th><th>Discharges</th><th>Transfers</th><th>Average occupancy</th><th>Peak occupancy</th><th>Lowest occupancy</th><th>Average stay (hours)</th></tr></thead><tbody>{comparison.items.map((run) => <tr key={run.run_id}><td><strong>{run.scenario_name ?? "Unknown scenario"}</strong><small>{run.run_id.slice(0, 8)}{run.run_id === comparison.baseline_run_id ? " · baseline" : ""}</small></td>{(["patients", "admissions", "discharges", "transfers", "average_occupancy_pct", "peak_occupancy_pct", "lowest_occupancy_pct", "average_length_of_stay_hours"] as const).map((key) => { const value = run[key]; const delta = run.metrics_vs_baseline[key]; return <td key={key}>{value === null ? "Unavailable" : key.endsWith("occupancy_pct") ? percent(value as number) : (value as number).toLocaleString()}<small>{delta.absolute_difference === null ? "No difference" : `${delta.absolute_difference > 0 ? "+" : ""}${delta.absolute_difference}${delta.percentage_change === null ? " · % n/a" : ` · ${delta.percentage_change > 0 ? "+" : ""}${delta.percentage_change}%`}`}</small></td>; })}</tr>)}</tbody></table></div></div>
        <div className="generator-card analytics-department-table"><div className="generator-card-header"><span className="generator-section-icon"><BedDouble size={17} /></span><div><h2>Department comparison</h2><p>Admissions, admission share, recorded occupancy range, and transfer activity.</p></div></div><div className="generator-table-wrap"><table className="generator-history-table"><thead><tr><th>Run / department</th><th>Admissions</th><th>Admission share</th><th>Average occupancy</th><th>Peak occupancy</th><th>Lowest occupancy</th><th>Incoming transfers</th><th>Outgoing transfers</th></tr></thead><tbody>{comparison.items.flatMap((run) => run.departments.map((department) => <tr key={`${run.run_id}-${department.department_id}`}><td><strong>{run.scenario_name ?? run.run_id.slice(0, 8)} · {department.department_name}</strong><small>{department.department_code}</small></td><td>{department.admissions}</td><td>{percent(department.admission_share_pct)}</td><td>{percent(department.average_occupancy_pct)}</td><td>{percent(department.peak_occupancy_pct)}</td><td>{percent(department.lowest_occupancy_pct)}</td><td>{department.incoming_transfers}</td><td>{department.outgoing_transfers}</td></tr>))}</tbody></table></div></div>
        <div className="generator-card analytics-department-table"><div className="generator-card-header"><span className="generator-section-icon"><Activity size={17} /></span><div><h2>Department transfer routes</h2><p>Persisted transfers grouped by source and destination departments.</p></div></div><div className="generator-table-wrap"><table className="generator-history-table"><thead><tr><th>Scenario / run</th><th>Source department</th><th>Destination department</th><th>Transfers</th></tr></thead><tbody>{comparison.items.flatMap((run) => run.transfer_routes.map((route, index) => <tr key={`${run.run_id}-route-${index}`}><td>{run.scenario_name ?? run.run_id.slice(0, 8)}</td><td>{route.source_department_name}</td><td>{route.destination_department_name}</td><td>{route.transfers}</td></tr>))}</tbody></table></div>{comparison.items.every((run) => run.transfer_routes.length === 0) && <div className="generator-history-empty">No transfer routes were recorded in these runs.</div>}</div>
      </section>}

      {loadingHospitals ? <div className="generator-loading"><LoaderCircle className="generator-spin" />Loading hospitals…</div>
        : noHospitals ? <div className="generator-empty"><span className="generator-empty-icon"><Building2 size={20} /></span><h2>No active hospitals</h2><p>Add a hospital and generate an operations dataset before exploring analytics.</p><Link href="/hospitals" className="generator-button generator-button-primary">Open Hospital Studio</Link></div>
        : loading && !overview ? <div className="generator-loading"><LoaderCircle className="generator-spin" />Loading hospital analytics…</div>
        : overview && <>
          <section className="analytics-period" aria-live="polite"><div><strong>{selectedHospital?.name}</strong><span>{overview.metadata.start_date && overview.metadata.end_date ? `${shortDate(overview.metadata.start_date)} – ${shortDate(overview.metadata.end_date)} · UTC` : "No reporting period available"}</span></div><div>{overview.metadata.run_id ? <>{overview.metadata.scenario_name ?? "Completed run"} <code>{overview.metadata.run_id.slice(0, 8)}</code> · seed {overview.metadata.seed}</> : "No completed run matches these filters"}</div></section>

          {!hasRun || !overview.metadata.has_data ? <div className="generator-empty analytics-no-data"><span className="generator-empty-icon"><BarChart3 size={21} /></span><h2>{hasRun ? "No records in this reporting period" : "No generated data yet"}</h2><p>{hasRun ? "The selected run has no persisted events or occupancy snapshots within these filters. No missing values are interpolated." : "Generate a dataset for this hospital to populate analytics from its saved records."}</p>{!hasRun && <Link href="/generate" className="generator-button generator-button-primary">Open generator</Link>}</div> : <>
            <div className="analytics-note"><Activity size={15} /><span>Using {overview.metadata.scenario_name ?? "the selected completed run"}; separate generation runs are not merged. Occupancy values are calculated from recorded snapshots. Current bed inventory can differ from inventory recorded at generation time.</span></div>

            {insights.length > 0 && <section className="generator-card analytics-insights"><div className="generator-card-header"><span className="generator-section-icon"><Activity size={17} /></span><div><h2>Calculated insights</h2><p>Rule-based observations derived from the selected run's aggregate metrics. Relative flags are not clinical thresholds.</p></div></div><ul>{insights.map((item, index) => <li key={`${item.kind}-${index}`}><span>{item.text}</span><small>Calculated from aggregate records · no patient-level data</small></li>)}</ul></section>}

            <section className="analytics-kpis" aria-label="Analytics overview">
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label"><BedDouble size={14} /> OPERATIONAL BEDS</span><strong>{metrics?.operational_beds ?? "—"}</strong><small>Current active inventory</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label"><Activity size={14} /> LATEST OCCUPANCY</span><strong>{percent(metrics?.latest_occupancy_pct)} </strong><small>{metrics?.latest_occupancy_date ? `${shortDate(metrics.latest_occupancy_date)} · ${latestCoverage}` : "No snapshots in period"}</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label">OCCUPIED / AVAILABLE</span><strong>{metrics?.occupied_beds_latest ?? "—"}<small> / {metrics?.available_beds_latest ?? "—"}</small></strong><small>At latest recorded snapshot</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label">AVERAGE OCCUPANCY</span><strong>{percent(metrics?.average_occupancy_pct)}</strong><small>Mean of daily recorded hospital samples</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label">PEAK OCCUPANCY</span><strong>{percent(metrics?.peak_occupancy_pct)}</strong><small>Highest daily recorded sample</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label">LOWEST OCCUPANCY</span><strong>{percent(metrics?.lowest_occupancy_pct)}</strong><small>Lowest daily recorded sample</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label">AVERAGE LENGTH OF STAY</span><strong>{metrics?.average_length_of_stay_hours === null || metrics?.average_length_of_stay_hours === undefined ? "Unavailable" : `${metrics.average_length_of_stay_hours.toFixed(1)} h`}</strong><small>Completed admissions with valid persisted timestamps</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label">ADMISSIONS</span><strong>{metrics?.admissions ?? "—"}</strong><small>Admission events in period</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label">DISCHARGES</span><strong>{metrics?.discharges ?? "—"}</strong><small>Discharge events in period</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label">TRANSFERS / SNAPSHOTS</span><strong>{metrics?.transfers ?? "—"}<small> / {metrics?.occupancy_snapshots ?? "—"}</small></strong><small>Separate operational event counts</small></article>
            </section>

            <section className="analytics-chart-grid" aria-label="Hospital charts">
              <ChartCard title="Occupancy trend" subtitle="Daily occupied operational beds ÷ recorded operational beds." empty={!occupancy?.items.length}>
                <ResponsiveContainer width="100%" height="100%"><LineChart data={occupancy?.items} margin={{ top: 8, right: 12, left: 0, bottom: 2 }} accessibilityLayer><CartesianGrid stroke={GRID} strokeDasharray="3 5" vertical={false} /><XAxis dataKey="date" tickFormatter={shortDate} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} minTickGap={22} /><YAxis domain={[0, 100]} unit="%" tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} width={42} /><Tooltip labelFormatter={(value) => shortDate(String(value))} formatter={(value) => [percent(typeof value === "number" ? value : null), "Occupancy"]} contentStyle={tooltipStyle} /><Line type="monotone" dataKey="occupancy_pct" name="Occupancy" stroke={TEAL} strokeWidth={2.5} dot={{ r: 3, fill: TEAL }} activeDot={{ r: 5 }} connectNulls={false} /></LineChart></ResponsiveContainer>
              </ChartCard>
              <ChartCard title="Occupied vs available" subtitle="Daily recorded bed counts. Missing snapshots are not filled." empty={!occupancy?.items.length}>
                <ResponsiveContainer width="100%" height="100%"><BarChart data={occupancy?.items} margin={{ top: 8, right: 12, left: 0, bottom: 2 }} accessibilityLayer><CartesianGrid stroke={GRID} strokeDasharray="3 5" vertical={false} /><XAxis dataKey="date" tickFormatter={shortDate} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} minTickGap={22} /><YAxis tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} width={38} /><Tooltip labelFormatter={(value) => shortDate(String(value))} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 10 }} /><Bar dataKey="occupied_beds" name="Occupied" stackId="beds" fill={TEAL} radius={[3, 3, 0, 0]} /><Bar dataKey="available_beds" name="Available" stackId="beds" fill={CYAN} radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer>
              </ChartCard>
              <ChartCard title="Admissions vs discharges" subtitle="Daily event counts from the selected run." empty={!flow?.items.length}>
                <ResponsiveContainer width="100%" height="100%"><BarChart data={flow?.items} margin={{ top: 8, right: 12, left: 0, bottom: 2 }} accessibilityLayer><CartesianGrid stroke={GRID} strokeDasharray="3 5" vertical={false} /><XAxis dataKey="date" tickFormatter={shortDate} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} minTickGap={22} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} width={38} /><Tooltip labelFormatter={(value) => shortDate(String(value))} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 10 }} /><Bar dataKey="admissions" name="Admissions" fill={TEAL} radius={[3, 3, 0, 0]} /><Bar dataKey="discharges" name="Discharges" fill={CYAN} radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer>
              </ChartCard>
              <ChartCard title="Department occupancy" subtitle="Latest occupancy recorded per department in the selected period." empty={!utilization?.items.some((item) => item.latest_occupancy_pct !== null)}>
                <ResponsiveContainer width="100%" height="100%"><BarChart data={utilization?.items} layout="vertical" margin={{ top: 8, right: 20, left: 12, bottom: 2 }} accessibilityLayer><CartesianGrid stroke={GRID} strokeDasharray="3 5" horizontal={false} /><XAxis type="number" domain={[0, 100]} unit="%" tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} /><YAxis type="category" dataKey="department_name" width={115} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} /><Tooltip formatter={(value) => [percent(Number(value)), "Occupancy"]} contentStyle={tooltipStyle} /><ReferenceLine x={0} stroke={GRID} /><Bar dataKey="latest_occupancy_pct" name="Occupancy" fill={TEAL} radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer>
              </ChartCard>
              <ChartCard title="Department admission distribution" subtitle="Admission events grouped by their initial department." empty={!utilization?.items.some((item) => item.admissions > 0)}>
                <ResponsiveContainer width="100%" height="100%"><BarChart data={utilization?.items} margin={{ top: 8, right: 12, left: 0, bottom: 2 }} accessibilityLayer><CartesianGrid stroke={GRID} strokeDasharray="3 5" vertical={false} /><XAxis dataKey="department_name" tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 9 }} interval={0} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} width={38} /><Tooltip contentStyle={tooltipStyle} /><Bar dataKey="admissions" name="Admissions" fill={CYAN} radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
              </ChartCard>
              <ChartCard title="Occupancy trend by department" subtitle="Daily latest recorded snapshot per department; missing points are not interpolated." empty={!departmentTrend.length}>
                <ResponsiveContainer width="100%" height="100%"><LineChart data={departmentTrend} margin={{ top: 8, right: 12, left: 0, bottom: 2 }} accessibilityLayer><CartesianGrid stroke={GRID} strokeDasharray="3 5" vertical={false} /><XAxis dataKey="date" tickFormatter={shortDate} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} minTickGap={22} /><YAxis domain={[0, 100]} unit="%" tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} width={42} /><Tooltip labelFormatter={(value) => shortDate(String(value))} formatter={(value) => [percent(typeof value === "number" ? value : null), "Occupancy"]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 9 }} />{(utilization?.items ?? []).map((item, index) => <Line key={item.department_id} type="monotone" dataKey={String(item.department_id)} name={item.department_name} stroke={[TEAL, CYAN, "#7c3aed", "#c2410c", "#2563eb", "#be185d"][index % 6]} strokeWidth={2} dot={false} connectNulls={false} />)}</LineChart></ResponsiveContainer>
              </ChartCard>
              <ChartCard title="Daily transfers" subtitle="Transfers are counted as separate movement events, not admissions." empty={!flow?.items.some((item) => item.transfers > 0)}>
                <ResponsiveContainer width="100%" height="100%"><LineChart data={flow?.items} margin={{ top: 8, right: 12, left: 0, bottom: 2 }} accessibilityLayer><CartesianGrid stroke={GRID} strokeDasharray="3 5" vertical={false} /><XAxis dataKey="date" tickFormatter={shortDate} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} minTickGap={22} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} width={38} /><Tooltip labelFormatter={(value) => shortDate(String(value))} contentStyle={tooltipStyle} /><Line type="monotone" dataKey="transfers" name="Transfers" stroke={CYAN} strokeWidth={2.5} dot={{ r: 3, fill: CYAN }} activeDot={{ r: 5 }} /></LineChart></ResponsiveContainer>
              </ChartCard>
            </section>
            <section className="generator-card analytics-department-table"><div className="generator-card-header"><span className="generator-section-icon"><BedDouble size={17} /></span><div><h2>Department utilization detail</h2><p>Current inventory alongside persisted occupancy and event counts for the selected period.</p></div></div><div className="generator-table-wrap"><table className="generator-history-table"><thead><tr><th>Department</th><th>Admissions</th><th>Admission share</th><th>Operational</th><th>Occupied</th><th>Available</th><th>Latest occupancy</th><th>Average</th><th>Peak</th><th>Lowest</th><th>Incoming transfers</th><th>Outgoing transfers</th></tr></thead><tbody>{utilization?.items.map((item) => <tr key={item.department_id}><td><strong>{item.department_name}</strong><small>{item.department_code}</small></td><td>{item.admissions}</td><td>{percent(item.admission_share_pct)}</td><td>{item.operational_beds}</td><td>{item.occupied_beds_latest ?? "—"}</td><td>{item.available_beds_latest ?? "—"}</td><td>{percent(item.latest_occupancy_pct)}</td><td>{percent(item.average_occupancy_pct)}</td><td>{percent(item.peak_occupancy_pct)}</td><td>{percent(item.lowest_occupancy_pct)}</td><td>{item.incoming_transfers}</td><td>{item.outgoing_transfers}</td></tr>)}</tbody></table></div>{!utilization?.items.length && <div className="generator-history-empty">No active departments match this hospital.</div>}</section>
            <section className="generator-card analytics-department-table"><div className="generator-card-header"><span className="generator-section-icon"><Activity size={17} /></span><div><h2>Transfer activity between departments</h2><p>Transfer events grouped by their persisted source and destination departments.</p></div></div><div className="generator-table-wrap"><table className="generator-history-table"><thead><tr><th>Source department</th><th>Destination department</th><th>Transfers</th></tr></thead><tbody>{utilization?.transfer_routes.map((route) => <tr key={`${route.source_department_id}-${route.destination_department_id}`}><td>{route.source_department_name}</td><td>{route.destination_department_name}</td><td>{route.transfers}</td></tr>)}</tbody></table></div>{!utilization?.transfer_routes.length && <div className="generator-history-empty">No department transfer routes were recorded in this selection.</div>}</section>
          </>}
          <footer className="analytics-footer">Daily occupancy points use the latest persisted snapshot for each department on each UTC date. A zero operational-bed denominator returns no percentage. Values are not interpolated. Department admission shares divide each department's initial-department admission events by the filtered total. Transfers are separate events grouped by source or destination department. Latest bed status is current; historical bed-status changes are not versioned. All values describe simulated operations, not clinical capacity or real hospital performance.</footer>
        </>}
    </div>
  </main>;
}

const tooltipStyle = { border: "1px solid var(--border-strong)", borderRadius: 9, background: "var(--surface)", color: "var(--text)", fontSize: 11, boxShadow: "var(--shadow)" };

function ChartCard({ title, subtitle, empty, children }: { title: string; subtitle: string; empty: boolean; children: ReactNode }) {
  return <article className="generator-card analytics-chart-card"><div className="analytics-chart-heading"><h2>{title}</h2><p>{subtitle}</p></div><div className="analytics-chart-area" role="group" aria-label={`${title}. ${subtitle}`}>{empty ? <div className="analytics-chart-empty">No recorded values for this selection.</div> : children}</div></article>;
}
