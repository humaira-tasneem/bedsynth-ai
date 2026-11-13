"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity, ArrowLeft, ArrowUpRight, BarChart3, BedDouble, Building2,
  CalendarDays, CircleAlert, LoaderCircle, Moon, RefreshCw, Sun,
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

type Workspace = { id: number };
type Department = { id: number; name: string; code: string };
type Hospital = { id: number; workspace_id: number; name: string; code: string; is_archived: boolean; departments: (Department & { is_archived: boolean })[] };
type Metadata = {
  hospital_id: number; hospital_name: string; run_id: string | null; run_started_at: string | null;
  seed: number | null; department_id: number | null; department_name: string | null;
  start_date: string | null; end_date: string | null; time_zone: "UTC"; snapshot_cadence: string; has_data: boolean;
};
type Overview = { metadata: Metadata; metrics: {
  operational_beds: number; occupied_beds_latest: number | null; available_beds_latest: number | null;
  latest_occupancy_pct: number | null; latest_occupancy_date: string | null; departments_reporting_latest: number;
  departments_expected: number; average_occupancy_pct: number | null; peak_occupancy_pct: number | null;
  admissions: number; discharges: number; transfers: number; occupancy_snapshots: number;
} };
type Occupancy = { metadata: Metadata; items: { date: string; operational_beds: number; occupied_beds: number; available_beds: number; occupancy_pct: number | null; departments_reporting: number; snapshot_count: number }[] };
type Flow = { metadata: Metadata; items: { date: string; admissions: number; discharges: number; transfers: number }[] };
type Utilization = { metadata: Metadata; items: { department_id: number; department_name: string; department_code: string; operational_beds: number; occupied_beds_latest: number | null; available_beds_latest: number | null; latest_occupancy_pct: number | null; average_occupancy_pct: number | null; peak_occupancy_pct: number | null; snapshots: number }[] };

async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, { cache: "no-store", signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Request failed (${response.status}).`);
  }
  return response.json();
}

function percent(value: number | null | undefined) { return value === null || value === undefined ? "—" : `${value.toFixed(1)}%`; }
function shortDate(value: string) { return new Date(`${value}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" }); }
function queryString(start: string, end: string, department: string) {
  const params = new URLSearchParams();
  if (start && end) { params.set("start_date", start); params.set("end_date", end); }
  if (department) params.set("department_id", department);
  return params.size ? `?${params.toString()}` : "";
}

export default function AnalyticsPage() {
  const [hospitals, setHospitals] = useState<Hospital[]>([]);
  const [hospitalId, setHospitalId] = useState("");
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
    if (!hospitalId) { setOverview(null); setOccupancy(null); setFlow(null); setUtilization(null); return; }
    const controller = new AbortController();
    async function loadAnalytics() {
      setLoading(true); setError("");
      const query = queryString(appliedStart, appliedEnd, departmentId);
      try {
        const [summary, trend, patientFlow, departments] = await Promise.all([
          api<Overview>(`/analytics/hospitals/${hospitalId}/overview${query}`, controller.signal),
          api<Occupancy>(`/analytics/hospitals/${hospitalId}/occupancy${query}`, controller.signal),
          api<Flow>(`/analytics/hospitals/${hospitalId}/patient-flow${query}`, controller.signal),
          api<Utilization>(`/analytics/hospitals/${hospitalId}/departments${query}`, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        setOverview(summary); setOccupancy(trend); setFlow(patientFlow); setUtilization(departments);
        if (!appliedStart && !appliedEnd && summary.metadata.start_date && summary.metadata.end_date) {
          setStartDate(summary.metadata.start_date); setEndDate(summary.metadata.end_date);
          setAppliedStart(summary.metadata.start_date); setAppliedEnd(summary.metadata.end_date);
        }
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Analytics could not be loaded.");
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void loadAnalytics();
    return () => controller.abort();
  }, [hospitalId, departmentId, appliedStart, appliedEnd, refreshKey]);

  function changeHospital(value: string) {
    setHospitalId(value); setDepartmentId(""); setStartDate(""); setEndDate(""); setAppliedStart(""); setAppliedEnd(""); setFilterError("");
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

  return <main className="generator-page analytics-page" id="main-content">
    <header className="generator-topbar">
      <Link href="/" className="generator-brand"><span className="generator-brand-mark"><Activity size={18} /></span><span>BedSynth <strong>AI</strong></span></Link>
      <nav aria-label="Workspace navigation" className="analytics-topbar"><Link href="/" className="generator-nav-link"><ArrowLeft size={14} /> Overview</Link><Link href="/generate" className="generator-nav-link">Generator <ArrowUpRight size={13} /></Link><Link href="/validation" className="generator-nav-link">Validation <ArrowUpRight size={13} /></Link><button type="button" className="validation-theme" onClick={() => { const next = !dark; setDark(next); document.documentElement.dataset.theme = next ? "dark" : "light"; window.localStorage.setItem("bedsynth-theme", next ? "dark" : "light"); }} aria-label={`Switch to ${dark ? "light" : "dark"} theme`}>{dark ? <Sun size={15} /> : <Moon size={15} />}</button></nav>
    </header>

    <div className="analytics-content">
      <div className="analytics-heading"><div><span className="generator-kicker"><BarChart3 size={14} /> HOSPITAL PERFORMANCE</span><h1>Analytics</h1><p>Explore occupancy, patient flow, and department utilization from persisted synthetic operations records.</p></div><button type="button" className="generator-button generator-button-secondary" onClick={() => setRefreshKey((key) => key + 1)} disabled={loading || loadingHospitals}><RefreshCw size={15} className={loading ? "generator-spin" : ""} /> Refresh</button></div>

      <section className="generator-card analytics-filters" aria-label="Analytics filters">
        <label><span><Building2 size={14} /> Hospital</span><select value={hospitalId} onChange={(event) => changeHospital(event.target.value)} disabled={loadingHospitals || !hospitals.length}><option value="">Select a hospital</option>{hospitals.map((hospital) => <option key={hospital.id} value={hospital.id}>{hospital.name}</option>)}</select></label>
        <label><span><BedDouble size={14} /> Department</span><select value={departmentId} onChange={(event) => setDepartmentId(event.target.value)} disabled={!selectedHospital}><option value="">All departments</option>{departmentOptions.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>
        <label><span><CalendarDays size={14} /> Start date</span><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} disabled={!hospitalId} /></label>
        <label><span><CalendarDays size={14} /> End date</span><input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} disabled={!hospitalId} /></label>
        <button type="button" className="generator-button generator-button-primary" onClick={applyFilters} disabled={!hospitalId || loading}><Activity size={15} /> Apply filters</button>
      </section>
      {filterError && <div className="generator-alert generator-alert-error" role="alert"><CircleAlert size={16} />{filterError}</div>}
      {error && <div className="generator-alert generator-alert-error" role="alert"><CircleAlert size={16} />{error}<button type="button" className="analytics-inline-action" onClick={() => setRefreshKey((key) => key + 1)}>Try again</button></div>}

      {loadingHospitals ? <div className="generator-loading"><LoaderCircle className="generator-spin" />Loading hospitals…</div>
        : noHospitals ? <div className="generator-empty"><span className="generator-empty-icon"><Building2 size={20} /></span><h2>No active hospitals</h2><p>Add a hospital and generate an operations dataset before exploring analytics.</p><Link href="/hospitals" className="generator-button generator-button-primary">Open Hospital Studio</Link></div>
        : loading && !overview ? <div className="generator-loading"><LoaderCircle className="generator-spin" />Loading hospital analytics…</div>
        : overview && <>
          <section className="analytics-period" aria-live="polite"><div><strong>{selectedHospital?.name}</strong><span>{overview.metadata.start_date && overview.metadata.end_date ? `${shortDate(overview.metadata.start_date)} – ${shortDate(overview.metadata.end_date)} · UTC` : "No reporting period available"}</span></div><div>{overview.metadata.run_id ? <>Latest completed run <code>{overview.metadata.run_id.slice(0, 8)}</code> · seed {overview.metadata.seed}</> : "No completed generation run for this hospital"}</div></section>

          {!hasRun || !overview.metadata.has_data ? <div className="generator-empty analytics-no-data"><span className="generator-empty-icon"><BarChart3 size={21} /></span><h2>{hasRun ? "No records in this reporting period" : "No generated data yet"}</h2><p>{hasRun ? "The selected run has no persisted events or occupancy snapshots within these filters. No missing values are interpolated." : "Generate a dataset for this hospital to populate analytics from its saved records."}</p>{!hasRun && <Link href="/generate" className="generator-button generator-button-primary">Open generator</Link>}</div> : <>
            <div className="analytics-note"><Activity size={15} /><span>Using the latest completed run only; separate generation runs are not merged. Occupancy values are calculated from recorded snapshots at 12:00 UTC. Current bed inventory can differ from inventory recorded at generation time.</span></div>

            <section className="analytics-kpis" aria-label="Analytics overview">
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label"><BedDouble size={14} /> OPERATIONAL BEDS</span><strong>{metrics?.operational_beds ?? "—"}</strong><small>Current active inventory</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label"><Activity size={14} /> LATEST OCCUPANCY</span><strong>{percent(metrics?.latest_occupancy_pct)} </strong><small>{metrics?.latest_occupancy_date ? `${shortDate(metrics.latest_occupancy_date)} · ${latestCoverage}` : "No snapshots in period"}</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label">OCCUPIED / AVAILABLE</span><strong>{metrics?.occupied_beds_latest ?? "—"}<small> / {metrics?.available_beds_latest ?? "—"}</small></strong><small>At latest recorded snapshot</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label">AVERAGE OCCUPANCY</span><strong>{percent(metrics?.average_occupancy_pct)}</strong><small>Mean of daily recorded hospital samples</small></article>
              <article className="generator-card analytics-kpi"><span className="analytics-kpi-label">PEAK OCCUPANCY</span><strong>{percent(metrics?.peak_occupancy_pct)}</strong><small>Highest daily recorded sample</small></article>
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
              <ChartCard title="Daily transfers" subtitle="Transfers are counted as separate movement events, not admissions." empty={!flow?.items.some((item) => item.transfers > 0)}>
                <ResponsiveContainer width="100%" height="100%"><LineChart data={flow?.items} margin={{ top: 8, right: 12, left: 0, bottom: 2 }} accessibilityLayer><CartesianGrid stroke={GRID} strokeDasharray="3 5" vertical={false} /><XAxis dataKey="date" tickFormatter={shortDate} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} minTickGap={22} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: NAVY, fontSize: 10 }} width={38} /><Tooltip labelFormatter={(value) => shortDate(String(value))} contentStyle={tooltipStyle} /><Line type="monotone" dataKey="transfers" name="Transfers" stroke={CYAN} strokeWidth={2.5} dot={{ r: 3, fill: CYAN }} activeDot={{ r: 5 }} /></LineChart></ResponsiveContainer>
              </ChartCard>
            </section>
            <section className="generator-card analytics-department-table"><div className="generator-card-header"><span className="generator-section-icon"><BedDouble size={17} /></span><div><h2>Department utilization detail</h2><p>Current operational bed inventory beside latest and period snapshot metrics.</p></div></div><div className="generator-table-wrap"><table className="generator-history-table"><thead><tr><th>Department</th><th>Operational</th><th>Occupied</th><th>Available</th><th>Latest occupancy</th><th>Average</th><th>Peak</th></tr></thead><tbody>{utilization?.items.map((item) => <tr key={item.department_id}><td><strong>{item.department_name}</strong><small>{item.department_code}</small></td><td>{item.operational_beds}</td><td>{item.occupied_beds_latest ?? "—"}</td><td>{item.available_beds_latest ?? "—"}</td><td>{percent(item.latest_occupancy_pct)}</td><td>{percent(item.average_occupancy_pct)}</td><td>{percent(item.peak_occupancy_pct)}</td></tr>)}</tbody></table></div>{!utilization?.items.length && <div className="generator-history-empty">No active departments match this hospital.</div>}</section>
          </>}
          <footer className="analytics-footer">Daily occupancy points use the latest persisted snapshot for each department on each UTC date. A zero operational-bed denominator returns no percentage. Values are not interpolated. Latest bed status is current; historical bed-status changes are not versioned.</footer>
        </>}
    </div>
  </main>;
}

const tooltipStyle = { border: "1px solid var(--border-strong)", borderRadius: 9, background: "var(--surface)", color: "var(--text)", fontSize: 11, boxShadow: "var(--shadow)" };

function ChartCard({ title, subtitle, empty, children }: { title: string; subtitle: string; empty: boolean; children: ReactNode }) {
  return <article className="generator-card analytics-chart-card"><div className="analytics-chart-heading"><h2>{title}</h2><p>{subtitle}</p></div><div className="analytics-chart-area" role="group" aria-label={`${title}. ${subtitle}`}>{empty ? <div className="analytics-chart-empty">No recorded values for this selection.</div> : children}</div></article>;
}
