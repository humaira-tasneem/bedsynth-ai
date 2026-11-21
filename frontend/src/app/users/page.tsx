"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, CalendarDays, ChevronLeft, ChevronRight, CircleUserRound, Database, FilterX, Search, Shield, ShieldCheck, UserRoundCheck, UserRoundX, X } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
type UserRecord = { id: number; email: string; role: "admin" | "user"; is_active: boolean; created_at: string; dataset_count: number };
type PageData = { items: UserRecord[]; total: number; page: number; page_size: number; pages: number };
type Stats = { total_accounts: number; active_accounts: number; deactivated_accounts: number; administrators: number; standard_users: number; registrations_7d: number; registrations_30d: number };
type ActivityPoint = { date: string; registrations: number };
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

export default function UsersPage() {
  const [stats, setStats] = useState<Stats>(emptyStats);
  const [activity, setActivity] = useState<ActivityPoint[]>([]);
  const [days, setDays] = useState<7 | 30>(30);
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
      const [nextStats, nextActivity, nextPage] = await Promise.all([
        request<Stats>("/admin/users/stats", { signal }),
        request<{ items: ActivityPoint[] }>(`/admin/users/activity?days=${days}`, { signal }),
        request<PageData>(`/admin/users?${params}`, { signal }),
      ]);
      setStats(nextStats); setActivity(nextActivity.items); setPageData(nextPage);
      setSelected((current) => current ? nextPage.items.find((user) => user.id === current.id) ?? current : null);
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === "AbortError")) setError(cause instanceof Error ? cause.message : "Accounts could not be loaded.");
    } finally { if (!signal?.aborted) setLoading(false); }
  }, [days, page, query, role, sort, status]);

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
      {primaryMetrics.map(({ label, value, icon: Icon, tone }) => <article className={`users-metric users-metric-${tone}`} key={label}><span className="users-metric-icon"><Icon size={19} /></span><span className="users-metric-label">{label}</span><strong>{loading ? "—" : value.toLocaleString()}</strong><small>{label === "Registered accounts" ? "Guest sessions excluded" : label === "Active accounts" ? `${stats.deactivated_accounts.toLocaleString()} deactivated` : "From account creation dates"}</small></article>)}
    </section>
    <section className="users-secondary-metrics" aria-label="Account breakdown">
      <div><Shield size={17} /><span>Administrators</span><strong>{loading ? "—" : stats.administrators.toLocaleString()}</strong></div>
      <div><CircleUserRound size={17} /><span>Standard users</span><strong>{loading ? "—" : stats.standard_users.toLocaleString()}</strong></div>
      <div><UserRoundX size={17} /><span>Deactivated</span><strong>{loading ? "—" : stats.deactivated_accounts.toLocaleString()}</strong></div>
    </section>

    <section className="users-panel users-activity-panel">
      <div className="users-panel-header"><div><span className="users-panel-icon"><Activity size={18} /></span><div><h2>Registration activity</h2><p>Daily new accounts, based on recorded creation timestamps.</p></div></div><div className="users-segment" aria-label="Registration activity range">{([7, 30] as const).map((range) => <button key={range} type="button" aria-pressed={days === range} onClick={() => setDays(range)}>{range} days</button>)}</div></div>
      {loading && !activity.length ? <div className="users-chart-skeleton" aria-label="Loading registration chart" /> : chartHasHistory ? <div className="users-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={activity} margin={{ top: 12, right: 14, left: -18, bottom: 0 }}><defs><linearGradient id="registrationFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--primary)" stopOpacity={0.2} /><stop offset="100%" stopColor="var(--primary)" stopOpacity={0.01} /></linearGradient></defs><CartesianGrid stroke="var(--border)" strokeDasharray="4 5" vertical={false} /><XAxis dataKey="date" tickFormatter={dateLabel} tick={{ fill: "var(--text-muted)", fontSize: 12 }} tickLine={false} axisLine={false} minTickGap={22} /><YAxis allowDecimals={false} width={34} tick={{ fill: "var(--text-muted)", fontSize: 12 }} tickLine={false} axisLine={false} /><Tooltip labelFormatter={(label) => dateLabel(String(label))} formatter={(value) => [value, "Registrations"]} contentStyle={{ borderColor: "var(--border)", borderRadius: 10, background: "var(--surface)", color: "var(--text)" }} /><Area type="monotone" dataKey="registrations" stroke="var(--primary)" strokeWidth={2.5} fill="url(#registrationFill)" activeDot={{ r: 4 }} /></AreaChart></ResponsiveContainer></div> : <div className="users-chart-empty"><Activity size={22} /><strong>No registrations in this period</strong><span>The chart will show account creation activity when available.</span></div>}
    </section>

    <section className="users-panel users-table-panel">
      <div className="users-panel-header"><div><span className="users-panel-icon"><CircleUserRound size={18} /></span><div><h2>Accounts</h2><p>Review access and dataset ownership. Last login is not currently tracked.</p></div></div><span className="users-result-count">{loading ? "Loading…" : `${pageData.total.toLocaleString()} accounts`}</span></div>
      <div className="users-filters">
        <label className="users-search"><Search size={17} /><span className="sr-only">Search email</span><input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search by email" /></label>
        <label><span className="sr-only">Filter by role</span><select value={role} onChange={(event) => setFilter(() => setRole(event.target.value))}><option value="">All roles</option><option value="admin">Administrators</option><option value="user">Standard users</option></select></label>
        <label><span className="sr-only">Filter by status</span><select value={status} onChange={(event) => setFilter(() => setStatus(event.target.value))}><option value="">All statuses</option><option value="active">Active</option><option value="deactivated">Deactivated</option></select></label>
        <label><span className="sr-only">Sort by registration date</span><select value={sort} onChange={(event) => setFilter(() => setSort(event.target.value))}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label>
        <button className="button button-secondary users-clear" type="button" onClick={() => { setSearchText(""); setQuery(""); setRole(""); setStatus(""); setSort("newest"); setPage(1); }}><FilterX size={15} /> Clear</button>
      </div>
      <div className="users-table-wrap"><table className="users-table"><thead><tr><th>Account</th><th>Role</th><th>Status</th><th>Registered</th><th>Datasets</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>
        {loading && pageData.items.length === 0 ? Array.from({ length: 5 }, (_, i) => <tr key={i} className="users-skeleton-row"><td colSpan={6}><span /></td></tr>) : pageData.items.map((user) => <tr key={user.id}>
          <td><button className="users-account-link" type="button" onClick={() => setSelected(user)}><span className="users-avatar">{user.email.slice(0, 1).toUpperCase()}</span><span><strong>{user.email}</strong><small>Account #{user.id}</small></span></button></td>
          <td><span className={`users-role-badge ${user.role}`}>{user.role === "admin" ? <ShieldCheck size={13} /> : <CircleUserRound size={13} />}{user.role === "admin" ? "Admin" : "Standard"}</span></td>
          <td><span className={`users-status ${user.is_active ? "active" : "inactive"}`}><i />{user.is_active ? "Active" : "Deactivated"}</span></td>
          <td>{dateTime(user.created_at)}</td><td><span className="users-dataset-count"><Database size={14} />{user.dataset_count}</span></td>
          <td><div className="users-actions"><select aria-label={`Change role for ${user.email}`} value={user.role} disabled={busy === user.id} onChange={(event) => setConfirm({ user, role: event.target.value as UserRecord["role"] })}><option value="user">User</option><option value="admin">Admin</option></select><button className="users-action-button" type="button" disabled={busy === user.id} onClick={() => setConfirm({ user, is_active: !user.is_active })}>{busy === user.id ? "Saving…" : user.is_active ? "Deactivate" : "Activate"}</button></div></td>
        </tr>)}
        {!loading && !pageData.items.length && <tr><td className="users-empty" colSpan={6}><CircleUserRound size={25} /><strong>{query || role || status ? "No accounts match these filters" : "No registered accounts yet"}</strong><span>Adjust filters or clear them to see accounts.</span><button className="button button-secondary" type="button" onClick={() => { setSearchText(""); setQuery(""); setRole(""); setStatus(""); }}>Clear filters</button></td></tr>}
      </tbody></table></div>
      <div className="users-pagination"><span>Page {pageData.pages ? pageData.page : 0} of {pageData.pages} · {pageData.total.toLocaleString()} accounts</span><div><button className="button button-secondary" type="button" disabled={page <= 1 || loading} aria-label="Previous page" onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={16} /> Previous</button><button className="button button-secondary" type="button" disabled={!pageData.pages || page >= pageData.pages || loading} aria-label="Next page" onClick={() => setPage((value) => value + 1)}>Next <ChevronRight size={16} /></button></div></div>
    </section>

    {selected && <div className="users-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}><section className="users-modal" role="dialog" aria-modal="true" aria-labelledby="users-detail-title"><header><div><h2 id="users-detail-title">Account details</h2><p>Account information and available ownership metadata.</p></div><button type="button" className="users-modal-close" aria-label="Close account details" onClick={() => setSelected(null)}><X size={18} /></button></header><div className="users-detail-email"><span className="users-avatar">{selected.email.slice(0, 1).toUpperCase()}</span><strong>{selected.email}</strong></div><dl className="users-detail-grid"><div><dt>Role</dt><dd>{selected.role === "admin" ? "Administrator" : "Standard user"}</dd></div><div><dt>Status</dt><dd>{selected.is_active ? "Active" : "Deactivated"}</dd></div><div><dt>Registered</dt><dd>{dateTime(selected.created_at)}</dd></div><div><dt>Completed datasets</dt><dd>{selected.dataset_count}</dd></div></dl><p className="users-detail-note">Last login and recent activity are not available because the application does not currently track those events.</p></section></div>}

    {confirm && <div className="users-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && busy === null) setConfirm(null); }}><section className="users-modal users-confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="users-confirm-title" aria-describedby="users-confirm-copy"><header><div><h2 id="users-confirm-title">Confirm account change</h2><p id="users-confirm-copy">{confirm.role ? `Change ${confirm.user.email} from ${confirm.user.role} to ${confirm.role}?` : `${confirm.is_active ? "Activate" : "Deactivate"} ${confirm.user.email}?${confirm.is_active ? " Their active sessions will be revoked." : ""}`}</p></div><button type="button" className="users-modal-close" aria-label="Cancel" onClick={() => setConfirm(null)}><X size={18} /></button></header><div className="users-confirm-actions"><button className="button button-secondary" type="button" disabled={busy !== null} onClick={() => setConfirm(null)}>Cancel</button><button className="button button-primary" type="button" disabled={busy !== null} onClick={() => void applyChange()}>{busy === confirm.user.id ? "Saving…" : "Confirm change"}</button></div></section></div>}
  </main>;
}
