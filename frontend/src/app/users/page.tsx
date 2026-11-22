"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, CalendarDays, ChevronLeft, ChevronRight, CircleUserRound, Database, FilterX, Search, Shield, ShieldCheck, UserRoundCheck, UserRoundX, X } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
type UserRecord = { id: number; email: string; role: "admin" | "user"; is_active: boolean; created_at: string; last_login_at: string | null; dataset_count: number };
type PageData = { items: UserRecord[]; total: number; page: number; page_size: number; pages: number };
type Stats = { total_accounts: number; active_accounts: number; deactivated_accounts: number; administrators: number; standard_users: number; registrations_7d: number; registrations_30d: number };
type ActivityPoint = { period: string; registrations: number };
type PeriodStats = { registered_accounts: number; active_registered_accounts: number; deactivated_registered_accounts: number; new_administrators: number; new_standard_users: number };
type AuditEvent = { id: number; actor_email: string | null; target_email: string | null; run_id: string | null; event_type: string; occurred_at: string; metadata: Record<string, unknown> };
type Change = { user: UserRecord; role?: UserRecord["role"]; is_active?: boolean };
const emptyStats: Stats = { total_accounts: 0, active_accounts: 0, deactivated_accounts: 0, administrators: 0, standard_users: 0, registrations_7d: 0, registrations_30d: 0 };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, { ...init, credentials: "include", cache: "no-store", headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers } });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.detail || "The request could not be completed.");
  return body as T;
}

function dateLabel(value: string) { return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(`${value}T00:00:00`)); }
function dateTime(value: string) { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function isoDate(date: Date) { return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`; }
function eventLabel(type: string) { return ({ account_registered:"Account registered", login_succeeded:"Successful login", logout:"Signed out", password_changed:"Password changed", role_changed:"Account role changed", account_activated:"Account activated", account_deactivated:"Account deactivated", dataset_generated:"Dataset generation completed", dataset_soft_deleted:"Dataset moved to deleted history" } as Record<string,string>)[type] ?? "Account activity"; }

export default function UsersPage() {
  const [stats, setStats] = useState<Stats>(emptyStats);
  const [activity, setActivity] = useState<ActivityPoint[]>([]);
  const [periodStats, setPeriodStats] = useState<PeriodStats>({ registered_accounts:0, active_registered_accounts:0, deactivated_registered_accounts:0, new_administrators:0, new_standard_users:0 });
  const [fromDate, setFromDate] = useState(""); const [toDate, setToDate] = useState(""); const [appliedFrom, setAppliedFrom] = useState(""); const [appliedTo, setAppliedTo] = useState("");
  const [dateError, setDateError] = useState(""); const [granularity, setGranularity] = useState("day");
  const [audit, setAudit] = useState<AuditEvent[]>([]); const [auditTotal, setAuditTotal] = useState(0); const [auditPage, setAuditPage] = useState(1); const [auditType, setAuditType] = useState("");
  const [auditQuery, setAuditQuery] = useState(""); const [auditActor, setAuditActor] = useState(""); const [auditTarget, setAuditTarget] = useState("");
  const [selectedActivity, setSelectedActivity] = useState<AuditEvent[]>([]); const [selectedActivityTotal, setSelectedActivityTotal] = useState(0); const [activityTab, setActivityTab] = useState<"details"|"activity">("details");
  const [accountActivityFrom, setAccountActivityFrom] = useState(""); const [accountActivityTo, setAccountActivityTo] = useState(""); const [accountActivityType, setAccountActivityType] = useState(""); const [accountActivityPage, setAccountActivityPage] = useState(1);
  const [pageData, setPageData] = useState<PageData>({ items: [], total: 0, page: 1, page_size: 10, pages: 0 });
  const [searchText, setSearchText] = useState(""); const [query, setQuery] = useState("");
  const [role, setRole] = useState(""); const [status, setStatus] = useState(""); const [sort, setSort] = useState("newest"); const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true); const [error, setError] = useState(""); const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState<number | null>(null); const [confirm, setConfirm] = useState<Change | null>(null); const [selected, setSelected] = useState<UserRecord | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "10", sort });
      if (query) params.set("q", query); if (role) params.set("role", role); if (status) params.set("status", status);
      if (appliedFrom) params.set("from_date", appliedFrom); if (appliedTo) params.set("to_date", appliedTo);
      const range = new URLSearchParams(); if (appliedFrom) range.set("from_date", appliedFrom); if (appliedTo) range.set("to_date", appliedTo); range.set("granularity", "auto");
      const auditParams = new URLSearchParams({ page:String(auditPage), page_size:"10" }); if (auditType) auditParams.set("event_type", auditType); if (appliedFrom) auditParams.set("from_date", appliedFrom); if (appliedTo) auditParams.set("to_date", appliedTo); if (auditQuery) auditParams.set("q",auditQuery); if (auditActor) auditParams.set("actor_id",auditActor); if (auditTarget) auditParams.set("target_id",auditTarget);
      const [nextStats, nextActivity, nextPage, nextPeriodStats, nextAudit] = await Promise.all([
        request<Stats>("/admin/users/stats", { signal }),
        request<{ items: ActivityPoint[]; granularity: string }>(`/admin/users/registration-activity?${range}`, { signal }),
        request<PageData>(`/admin/users?${params}`, { signal }),
        request<PeriodStats>(`/admin/users/registration-stats?${range}`, { signal }),
        request<{items:AuditEvent[];total:number}>(`/admin/account-activity?${auditParams}`,{signal}),
      ]);
      setStats(nextStats); setActivity(nextActivity.items); setGranularity(nextActivity.granularity); setPeriodStats(nextPeriodStats); setPageData(nextPage); setAudit(nextAudit.items); setAuditTotal(nextAudit.total);
      setSelected((current) => current ? nextPage.items.find((user) => user.id === current.id) ?? current : null);
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === "AbortError")) setError(cause instanceof Error ? cause.message : "Accounts could not be loaded.");
    } finally { if (!signal?.aborted) setLoading(false); }
  }, [appliedFrom, appliedTo, auditActor, auditPage, auditQuery, auditTarget, auditType, page, query, role, sort, status]);

  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);
  useEffect(() => { const timer = window.setTimeout(() => { setPage(1); setQuery(searchText.trim()); }, 300); return () => window.clearTimeout(timer); }, [searchText]);
  useEffect(() => { if (!confirm) return; const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setConfirm(null); }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, [confirm]);
  useEffect(() => {
    if (!selected) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = document.querySelector<HTMLElement>(".users-modal[role='dialog']");
    dialog?.querySelector<HTMLElement>("button")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
      if (event.key === "Tab" && dialog) {
        const focusable = Array.from(dialog.querySelectorAll<HTMLElement>("button:not([disabled]),select:not([disabled]),input:not([disabled]),a[href]"));
        if (!focusable.length) return;
        if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable[focusable.length - 1].focus(); }
        else if (!event.shiftKey && document.activeElement === focusable[focusable.length - 1]) { event.preventDefault(); focusable[0].focus(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); previousFocus?.focus(); };
  }, [selected]);

  function setFilter(update: () => void) { update(); setPage(1); }
  const chartHasHistory = useMemo(() => activity.some((point) => point.registrations > 0), [activity]);

  async function openAccount(user: UserRecord) {
    setSelected(user); setActivityTab("details"); setAccountActivityFrom(""); setAccountActivityTo(""); setAccountActivityType(""); setAccountActivityPage(1);
  }

  useEffect(()=>{
    if(!selected)return;
    const params=new URLSearchParams({page:String(accountActivityPage),page_size:"10"});
    if(accountActivityFrom)params.set("from_date",accountActivityFrom);if(accountActivityTo)params.set("to_date",accountActivityTo);if(accountActivityType)params.set("event_type",accountActivityType);
    request<{items:AuditEvent[];total:number}>(`/admin/users/${selected.id}/activity?${params}`).then(result=>{setSelectedActivity(result.items);setSelectedActivityTotal(result.total);}).catch(cause=>setError(cause instanceof Error?cause.message:"Account activity could not be loaded."));
  },[selected,accountActivityFrom,accountActivityTo,accountActivityType,accountActivityPage]);

  function applyRange(from: string, to: string) {
    if (from && Number.isNaN(Date.parse(`${from}T00:00:00Z`)) || to && Number.isNaN(Date.parse(`${to}T00:00:00Z`))) { setDateError("Choose valid calendar dates."); return; }
    if (from && to && from > to) { setDateError("Start date must be on or before end date."); return; }
    if (to && to > isoDate(new Date())) { setDateError("End date cannot be in the future."); return; }
    setDateError(""); setAppliedFrom(from); setAppliedTo(to); setPage(1); setAuditPage(1);
  }
  function preset(name: string) {
    const today = new Date(); let from = ""; let to = "";
    if (name === "7" || name === "30" || name === "90") { to = isoDate(today); const d = new Date(today); d.setDate(d.getDate() - (Number(name)-1)); from = isoDate(d); }
    else if (name === "this") { from = isoDate(new Date(today.getFullYear(),today.getMonth(),1)); to = isoDate(today); }
    else if (name === "previous") { from = isoDate(new Date(today.getFullYear(),today.getMonth()-1,1)); to = isoDate(new Date(today.getFullYear(),today.getMonth(),0)); }
    setFromDate(from); setToDate(to); applyRange(from,to);
  }

  async function applyChange() {
    if (!confirm) return;
    const { user, ...change } = confirm; setBusy(user.id); setError(""); setSuccess("");
    try {
      await request<UserRecord>(`/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify(change) });
      setSuccess(`${user.email} account updated.`); setConfirm(null); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Account could not be updated."); }
    finally { setBusy(null); }
  }

  const primaryMetrics = [
    { label: "Registered accounts", value: stats.total_accounts, icon: CircleUserRound, tone: "purple" },
    { label: "Active accounts", value: stats.active_accounts, icon: UserRoundCheck, tone: "teal" },
    { label: "New · 7 days", value: stats.registrations_7d, icon: Activity, tone: "blue" },
    { label: "New · 30 days", value: stats.registrations_30d, icon: CalendarDays, tone: "amber" },
  ];

  return <main className="page-content users-page" id="main-content">
    <div className="page-heading"><div><div className="page-kicker"><span className="kicker-line" /> ADMINISTRATION</div><h1>User Management</h1><p className="page-subtitle">Account access, registrations, and dataset ownership at a glance.</p></div></div>
    {error && <div className="users-alert users-alert-error" role="alert"><span>{error}</span><button className="button button-secondary" type="button" onClick={() => void load()}>Retry</button></div>}
    {success && <div className="users-alert users-alert-success" role="status">{success}<button type="button" aria-label="Dismiss message" onClick={() => setSuccess("")}><X size={16} /></button></div>}

    <section className="users-metric-grid" aria-label="Account statistics">
      {primaryMetrics.map(({ label, value, icon: Icon, tone }) => <article className={`users-metric users-metric-${tone}`} key={label}><span className="users-metric-icon"><Icon size={19} /></span><span className="users-metric-label">{label}</span><strong>{loading ? "—" : value.toLocaleString()}</strong><small>{label === "Registered accounts" ? "Registered accounts only" : label === "Active accounts" ? `${stats.deactivated_accounts.toLocaleString()} deactivated` : "From account creation dates"}</small></article>)}
    </section>
    <section className="users-secondary-metrics" aria-label="Account breakdown">
      <div><Shield size={17} /><span>Administrators</span><strong>{loading ? "—" : stats.administrators.toLocaleString()}</strong></div>
      <div><CircleUserRound size={17} /><span>Standard users</span><strong>{loading ? "—" : stats.standard_users.toLocaleString()}</strong></div>
      <div><UserRoundX size={17} /><span>Deactivated</span><strong>{loading ? "—" : stats.deactivated_accounts.toLocaleString()}</strong></div>
    </section>

    <section className="users-panel users-activity-panel">
      <div className="users-panel-header"><div><span className="users-panel-icon"><Activity size={18} /></span><div><h2>Registration activity</h2><p>Overall totals stay separate from accounts created during the selected period.</p></div></div><span className="users-granularity">Grouped by {granularity}</span></div>
      <div className="users-date-tools"><div className="users-date-presets" aria-label="Registration date presets">{[["7","Last 7 days"],["30","Last 30 days"],["90","Last 90 days"],["this","This month"],["previous","Previous month"],["all","All time"]].map(([key,label])=><button type="button" key={key} onClick={()=>preset(key)}>{label}</button>)}</div><div className="users-date-fields"><label>From<input type="date" value={fromDate} max={isoDate(new Date())} onChange={e=>setFromDate(e.target.value)} /></label><label>To<input type="date" value={toDate} max={isoDate(new Date())} onChange={e=>setToDate(e.target.value)} /></label><button className="button button-primary" type="button" onClick={()=>applyRange(fromDate,toDate)}>Apply</button><button className="button button-secondary" type="button" onClick={()=>{setFromDate("");setToDate("");applyRange("","");}}>Reset</button></div>{dateError&&<p className="users-date-error" role="alert">{dateError}</p>}</div>
      <div className="users-period-stats"><div><small>Registered in period</small><strong>{periodStats.registered_accounts.toLocaleString()}</strong></div><div><small>Active at query time</small><strong>{periodStats.active_registered_accounts.toLocaleString()}</strong></div><div><small>Deactivated</small><strong>{periodStats.deactivated_registered_accounts.toLocaleString()}</strong></div><div><small>New administrators</small><strong>{periodStats.new_administrators.toLocaleString()}</strong></div><div><small>New standard users</small><strong>{periodStats.new_standard_users.toLocaleString()}</strong></div></div>
      {loading && !activity.length ? <div className="users-chart-skeleton" aria-label="Loading registration chart" /> : chartHasHistory ? <div className="users-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={activity} margin={{ top: 12, right: 14, left: -18, bottom: 0 }}><defs><linearGradient id="registrationFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--primary)" stopOpacity={0.2} /><stop offset="100%" stopColor="var(--primary)" stopOpacity={0.01} /></linearGradient></defs><CartesianGrid stroke="var(--border)" strokeDasharray="4 5" vertical={false} /><XAxis dataKey="period" tickFormatter={(value:string)=>granularity==="week"?`W${value.split("-")[1]}, ${value.split("-")[0]}`:dateLabel(granularity==="month"?`${value}-01`:value)} tick={{ fill: "var(--text-muted)", fontSize: 12 }} tickLine={false} axisLine={false} minTickGap={22} /><YAxis allowDecimals={false} width={34} tick={{ fill: "var(--text-muted)", fontSize: 12 }} tickLine={false} axisLine={false} /><Tooltip labelFormatter={(value)=>granularity==="week"?`Week ${String(value).split("-")[1]}, ${String(value).split("-")[0]}`:granularity==="month"?new Intl.DateTimeFormat(undefined,{month:"long",year:"numeric"}).format(new Date(`${String(value)}-01T00:00:00`)):dateLabel(String(value))} formatter={(value) => [value, "Registrations"]} contentStyle={{ borderColor: "var(--border)", borderRadius: 10, background: "var(--surface)", color: "var(--text)" }} /><Area type="monotone" dataKey="registrations" stroke="var(--primary)" strokeWidth={2.5} fill="url(#registrationFill)" activeDot={{ r: 4 }} /></AreaChart></ResponsiveContainer></div> : <div className="users-chart-empty"><Activity size={22} /><strong>No registrations in this period</strong><span>The chart will show account creation activity when available.</span></div>}
    </section>

    <section className="users-panel users-table-panel">
      <div className="users-panel-header"><div><span className="users-panel-icon"><CircleUserRound size={18} /></span><div><h2>Accounts</h2><p>Search and manage accounts. Registration date filter follows the selected period.</p></div></div><span className="users-result-count">{loading ? "Loading…" : `${pageData.total.toLocaleString()} accounts`}</span></div>
      <div className="users-filters">
        <label className="users-search"><Search size={17} /><span className="sr-only">Search email</span><input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search by email" /></label>
        <label><span className="sr-only">Filter by role</span><select value={role} onChange={(event) => setFilter(() => setRole(event.target.value))}><option value="">All roles</option><option value="admin">Administrators</option><option value="user">Standard users</option></select></label>
        <label><span className="sr-only">Filter by status</span><select value={status} onChange={(event) => setFilter(() => setStatus(event.target.value))}><option value="">All statuses</option><option value="active">Active</option><option value="deactivated">Deactivated</option></select></label>
        <label><span className="sr-only">Sort by registration date</span><select value={sort} onChange={(event) => setFilter(() => setSort(event.target.value))}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label>
        <button className="button button-secondary users-clear" type="button" onClick={() => { setSearchText(""); setQuery(""); setRole(""); setStatus(""); setSort("newest"); setPage(1); }}><FilterX size={15} /> Clear</button>
      </div>
      <div className="users-table-wrap"><table className="users-table"><thead><tr><th>Account</th><th>Role</th><th>Status</th><th>Registered</th><th>Last login</th><th>Datasets</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>
        {loading && pageData.items.length === 0 ? Array.from({ length: 5 }, (_, i) => <tr key={i} className="users-skeleton-row"><td colSpan={7}><span /></td></tr>) : pageData.items.map((user) => <tr key={user.id}>
          <td><button className="users-account-link" type="button" onClick={() => void openAccount(user)}><span className="users-avatar">{user.email.slice(0, 1).toUpperCase()}</span><span><strong>{user.email}</strong><small>Account #{user.id}</small></span></button></td>
          <td><span className={`users-role-badge ${user.role}`}>{user.role === "admin" ? <ShieldCheck size={13} /> : <CircleUserRound size={13} />}{user.role === "admin" ? "Admin" : "Standard"}</span></td>
          <td><span className={`users-status ${user.is_active ? "active" : "inactive"}`}><i />{user.is_active ? "Active" : "Deactivated"}</span></td>
          <td>{dateTime(user.created_at)}</td><td>{user.last_login_at ? dateTime(user.last_login_at) : "Not recorded"}</td><td><span className="users-dataset-count"><Database size={14} />{user.dataset_count}</span></td>
          <td><div className="users-actions"><select aria-label={`Change role for ${user.email}`} value={user.role} disabled={busy === user.id} onChange={(event) => setConfirm({ user, role: event.target.value as UserRecord["role"] })}><option value="user">User</option><option value="admin">Admin</option></select><button className="users-action-button" type="button" disabled={busy === user.id} onClick={() => setConfirm({ user, is_active: !user.is_active })}>{busy === user.id ? "Saving…" : user.is_active ? "Deactivate" : "Activate"}</button></div></td>
        </tr>)}
        {!loading && !pageData.items.length && <tr><td className="users-empty" colSpan={7}><CircleUserRound size={25} /><strong>{query || role || status || appliedFrom || appliedTo ? "No accounts match these filters" : "No registered accounts yet"}</strong><span>Adjust filters or clear them to see accounts.</span><button className="button button-secondary" type="button" onClick={() => { setSearchText(""); setQuery(""); setRole(""); setStatus("");setFromDate("");setToDate("");applyRange("",""); }}>Clear filters</button></td></tr>}
      </tbody></table></div>
      <div className="users-pagination"><span>Page {pageData.pages ? pageData.page : 0} of {pageData.pages} · {pageData.total.toLocaleString()} accounts</span><div><button className="button button-secondary" type="button" disabled={page <= 1 || loading} aria-label="Previous page" onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={16} /> Previous</button><button className="button button-secondary" type="button" disabled={!pageData.pages || page >= pageData.pages || loading} aria-label="Next page" onClick={() => setPage((value) => value + 1)}>Next <ChevronRight size={16} /></button></div></div>
    </section>

    <section className="users-panel users-audit-panel" aria-labelledby="users-audit-heading">
      <div className="users-panel-header"><div><span className="users-panel-icon"><ShieldCheck size={18} /></span><div><h2 id="users-audit-heading">Account activity log</h2><p>Audited events recorded from the date tracking was introduced; no earlier history is inferred.</p></div></div><span className="users-result-count">{auditTotal.toLocaleString()} events</span></div>
      <div className="users-audit-controls"><label>Event type<select value={auditType} onChange={e=>{setAuditType(e.target.value);setAuditPage(1);}}><option value="">All events</option>{["account_registered","login_succeeded","logout","password_changed","role_changed","account_activated","account_deactivated","dataset_generated","dataset_soft_deleted"].map(type=><option key={type} value={type}>{eventLabel(type)}</option>)}</select></label><label>Search actor or target<input value={auditQuery} onChange={e=>{setAuditQuery(e.target.value);setAuditPage(1);}} placeholder="Email address" /></label><label>Actor account ID<input type="number" min="1" value={auditActor} onChange={e=>{setAuditActor(e.target.value);setAuditPage(1);}} placeholder="Any" /></label><label>Target account ID<input type="number" min="1" value={auditTarget} onChange={e=>{setAuditTarget(e.target.value);setAuditPage(1);}} placeholder="Any" /></label><span>{appliedFrom||appliedTo?`${appliedFrom||"All time"} — ${appliedTo||"Today"}`:"All available dates"}</span></div>
      {!audit.length?<div className="users-chart-empty"><Activity size={22}/><strong>No activity events for these filters</strong><span>New successful account and dataset events will be recorded going forward.</span></div>:<div className="users-audit-list">{audit.map(event=><article key={event.id}><span className="users-audit-dot"/><div><strong>{eventLabel(event.event_type)}</strong><small>{event.target_email||"Account unavailable"}{event.actor_email&&event.actor_email!==event.target_email?` · by ${event.actor_email}`:""}{event.run_id?` · run ${event.run_id.slice(0,8)}`:""}</small></div><time dateTime={event.occurred_at}>{dateTime(event.occurred_at)}</time></article>)}</div>}
      <div className="users-pagination"><span>Page {auditTotal?auditPage:0} · {auditTotal.toLocaleString()} events</span><div><button className="button button-secondary" disabled={auditPage<=1} onClick={()=>setAuditPage(p=>Math.max(1,p-1))}>Previous</button><button className="button button-secondary" disabled={auditPage*10>=auditTotal} onClick={()=>setAuditPage(p=>p+1)}>Next</button></div></div>
    </section>

    {selected && <div className="users-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}><section className="users-modal" role="dialog" aria-modal="true" aria-labelledby="users-detail-title"><header><div><h2 id="users-detail-title">Account details</h2><p>Account information and audited activity.</p></div><button type="button" className="users-modal-close" aria-label="Close account details" onClick={() => setSelected(null)}><X size={18} /></button></header><div className="users-detail-tabs" role="tablist"><button role="tab" aria-selected={activityTab==="details"} onClick={()=>setActivityTab("details")}>Details</button><button role="tab" aria-selected={activityTab==="activity"} onClick={()=>setActivityTab("activity")}>Activity</button></div>{activityTab==="details"?<><div className="users-detail-email"><span className="users-avatar">{selected.email.slice(0, 1).toUpperCase()}</span><strong>{selected.email}</strong></div><dl className="users-detail-grid"><div><dt>Role</dt><dd>{selected.role === "admin" ? "Administrator" : "Standard user"}</dd></div><div><dt>Status</dt><dd>{selected.is_active ? "Active" : "Deactivated"}</dd></div><div><dt>Registered</dt><dd>{dateTime(selected.created_at)}</dd></div><div><dt>Last login</dt><dd>{selected.last_login_at?dateTime(selected.last_login_at):"Not recorded yet"}</dd></div><div><dt>Completed datasets</dt><dd>{selected.dataset_count}</dd></div></dl><p className="users-detail-note">Activity tracking began with this release. Earlier activity is unavailable.</p></>:<><div className="users-timeline-filters"><label>From<input type="date" value={accountActivityFrom} onChange={e=>{setAccountActivityFrom(e.target.value);setAccountActivityPage(1);}} /></label><label>To<input type="date" value={accountActivityTo} onChange={e=>{setAccountActivityTo(e.target.value);setAccountActivityPage(1);}} /></label><label>Event<select value={accountActivityType} onChange={e=>{setAccountActivityType(e.target.value);setAccountActivityPage(1);}}><option value="">All events</option>{["account_registered","login_succeeded","logout","password_changed","role_changed","account_activated","account_deactivated","dataset_generated","dataset_soft_deleted"].map(type=><option key={type} value={type}>{eventLabel(type)}</option>)}</select></label><button type="button" onClick={()=>{setAccountActivityFrom("");setAccountActivityTo("");setAccountActivityType("");setAccountActivityPage(1);}}>Reset</button></div><div className="users-account-timeline">{selectedActivity.length?selectedActivity.map(event=><article key={event.id}><span className="users-audit-dot"/><div><strong>{eventLabel(event.event_type)}</strong><small>{event.actor_email?`By ${event.actor_email}`:"System event"}{event.run_id?` · Run ${event.run_id.slice(0,8)}`:""}</small></div><time>{dateTime(event.occurred_at)}</time></article>):<p className="users-detail-note">No activity events have been recorded for this account in this period. Events before tracking began are unavailable.</p>}</div><div className="users-pagination"><span>{selectedActivityTotal} events</span><div><button className="button button-secondary" disabled={accountActivityPage<=1} onClick={()=>setAccountActivityPage(p=>Math.max(1,p-1))}>Previous</button><button className="button button-secondary" disabled={accountActivityPage*10>=selectedActivityTotal} onClick={()=>setAccountActivityPage(p=>p+1)}>Next</button></div></div></>}</section></div>}

    {confirm && <div className="users-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && busy === null) setConfirm(null); }}><section className="users-modal users-confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="users-confirm-title" aria-describedby="users-confirm-copy"><header><div><h2 id="users-confirm-title">Confirm account change</h2><p id="users-confirm-copy">{confirm.role ? `Change ${confirm.user.email} from ${confirm.user.role} to ${confirm.role}?` : `${confirm.is_active ? "Activate" : "Deactivate"} ${confirm.user.email}?${confirm.is_active ? " Their active sessions will be revoked." : ""}`}</p></div><button type="button" className="users-modal-close" aria-label="Cancel" onClick={() => setConfirm(null)}><X size={18} /></button></header><div className="users-confirm-actions"><button className="button button-secondary" type="button" disabled={busy !== null} onClick={() => setConfirm(null)}>Cancel</button><button className="button button-primary" type="button" disabled={busy !== null} onClick={() => void applyChange()}>{busy === confirm.user.id ? "Saving…" : "Confirm change"}</button></div></section></div>}
  </main>;
}
