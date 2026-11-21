"use client";

import { useEffect, useState } from "react";
import { Activity, Building2, Check, CircleHelp, Database, Eye, KeyRound, LayoutDashboard, LockKeyhole, LogOut, Moon, MonitorCog, Palette, ShieldCheck, Sun, UserRound, X } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
type Account = { id: number; email: string; role: "admin" | "user"; is_active: boolean; created_at: string; last_login_at: string | null };
type Workspace = { id: number; name: string; is_shared: boolean };
type Hospital = { id: number; name: string; code: string; is_archived: boolean };
type Density = "comfortable" | "compact";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, { credentials: "include", cache: "no-store" });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.detail || "Settings could not be loaded.");
  return body as T;
}
function dateTime(value: string) { return new Intl.DateTimeFormat(undefined, { dateStyle: "long", timeStyle: "short" }).format(new Date(value)); }

export default function SettingsPage() {
  const [account, setAccount] = useState<Account | null>(null);
  const [expiresAt, setExpiresAt] = useState("");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [hospitals, setHospitals] = useState<Record<number, Hospital[]>>({});
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [density, setDensity] = useState<Density>("comfortable");
  const [reducedMotion, setReducedMotion] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyWorkspace, setBusyWorkspace] = useState<number | null>(null);
  const [error, setError] = useState(""); const [success, setSuccess] = useState("");
  const [currentPassword, setCurrentPassword] = useState(""); const [newPassword, setNewPassword] = useState(""); const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);

  useEffect(() => {
    setTheme((localStorage.getItem("bedsynth-theme") as "light" | "dark") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
    const storedDensity = (localStorage.getItem("bedsynth-density") as Density) || "comfortable";
    setDensity(storedDensity); document.documentElement.dataset.density = storedDensity;
    const savedMotion = localStorage.getItem("bedsynth-reduced-motion");
    setReducedMotion(savedMotion === null ? matchMedia("(prefers-reduced-motion: reduce)").matches : savedMotion === "true");
    setCollapsed(localStorage.getItem("bedsynth-sidebar-collapsed") === "true");
    let active = true;
    (async () => {
      setLoading(true); setError("");
      try {
        const [session, user] = await Promise.all([
          get<{ account: Account; session_expires_at: string }>("/auth/settings"),
          get<Account>("/auth/me"),
        ]);
        if (!active) return;
        setAccount(session.account); setExpiresAt(session.session_expires_at);
        const rows = user.role === "admin" ? await get<Workspace[]>("/admin/workspaces") : await get<Workspace[]>("/workspaces");
        if (!active) return;
        setWorkspaces(rows);
        const hospitalRows = await Promise.all(rows.map(async (workspace) => [workspace.id, await get<Hospital[]>(`/workspaces/${workspace.id}/hospitals`)] as const));
        if (active) setHospitals(Object.fromEntries(hospitalRows));
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "Settings could not be loaded."); }
      finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, []);

  function applyTheme(value: "light" | "dark") { setTheme(value); localStorage.setItem("bedsynth-theme", value); document.documentElement.dataset.theme = value; window.dispatchEvent(new CustomEvent("bedsynth-theme-change", { detail: value })); }
  function applyDensity(value: Density) { setDensity(value); localStorage.setItem("bedsynth-density", value); document.documentElement.dataset.density = value; }
  function applyMotion(value: boolean) { setReducedMotion(value); localStorage.setItem("bedsynth-reduced-motion", String(value)); document.documentElement.dataset.reducedMotion = String(value); window.dispatchEvent(new CustomEvent("bedsynth-motion-change", { detail: value })); }
  function applySidebar(value: boolean) { setCollapsed(value); localStorage.setItem("bedsynth-sidebar-collapsed", String(value)); window.dispatchEvent(new CustomEvent("bedsynth-sidebar-change", { detail: value })); }

  async function toggleSharing(workspace: Workspace) {
    setBusyWorkspace(workspace.id); setError(""); setSuccess("");
    try {
      const response = await fetch(`${apiBase}/api/v1/admin/workspaces/${workspace.id}/sharing`, { method: "PATCH", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_shared: !workspace.is_shared }) });
      const updated = await response.json().catch(() => null);
      if (!response.ok) throw new Error(updated?.detail || "Workspace access could not be updated.");
      setWorkspaces((current) => current.map((item) => item.id === updated.id ? updated : item));
      setSuccess(`${updated.name} is now ${updated.is_shared ? "shared with standard users" : "admin-only"}.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Workspace access could not be updated."); }
    finally { setBusyWorkspace(null); }
  }

  async function changePassword(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setSuccess("");
    if (newPassword !== confirmPassword) { setError("New password and confirmation do not match."); return; }
    if (newPassword.length < 12) { setError("Use at least 12 characters for the new password."); return; }
    setPasswordBusy(true);
    try {
      const response = await fetch(`${apiBase}/api/v1/auth/change-password`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || "Password could not be changed.");
      setCurrentPassword(""); setNewPassword(""); setConfirmPassword(""); setSuccess("Password changed successfully.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Password could not be changed."); }
    finally { setPasswordBusy(false); }
  }

  return <main className="page-content settings-center" id="main-content">
    <header className="page-heading"><div><div className="page-kicker"><span className="kicker-line" /> PERSONALIZATION & SECURITY</div><h1>Settings Center</h1><p className="page-subtitle">Manage this device’s appearance, account security, and workspace access.</p></div></header>
    {error && <div className="settings-feedback error" role="alert">{error}<button type="button" aria-label="Dismiss error" onClick={() => setError("")}><X size={16} /></button></div>}
    {success && <div className="settings-feedback success" role="status">{success}<button type="button" aria-label="Dismiss message" onClick={() => setSuccess("")}><X size={16} /></button></div>}
    {loading && <div className="generator-loading" role="status">Loading your settings…</div>}
    <div className="settings-center-grid">
      <nav className="settings-index" aria-label="Settings sections"><strong>SETTINGS</strong><a href="#appearance"><Palette size={16} />Appearance</a><a href="#account"><UserRound size={16} />Account</a><a href="#security"><LockKeyhole size={16} />Security</a><a href="#workspace"><Building2 size={16} />Workspace access</a><a href="#privacy"><Eye size={16} />Data &amp; privacy</a><a href="#about"><CircleHelp size={16} />About</a></nav>
      <div className="settings-sections">
        <section className="settings-panel" id="appearance"><header><span><Palette size={18} /></span><div><h2>Appearance &amp; display</h2><p>Preferences are stored on this device and apply immediately.</p></div></header>
          <div className="settings-control-row"><div><strong>Color theme</strong><small>Choose the display used throughout the application.</small></div><div className="settings-choice-group" role="group" aria-label="Color theme"><button type="button" aria-pressed={theme === "light"} className={theme === "light" ? "selected" : ""} onClick={() => applyTheme("light")}><Sun size={16} />Light</button><button type="button" aria-pressed={theme === "dark"} className={theme === "dark" ? "selected" : ""} onClick={() => applyTheme("dark")}><Moon size={16} />Dark</button></div></div>
          <div className="settings-control-row"><div><strong>Sidebar</strong><small>Keep a compact or expanded navigation rail.</small></div><label className="settings-switch"><input type="checkbox" checked={collapsed} onChange={(event) => applySidebar(event.target.checked)} /><span>{collapsed ? "Collapsed" : "Expanded"}</span></label></div>
          <div className="settings-control-row"><div><strong>Content density</strong><small>Choose comfortable spacing or a more compact view.</small></div><select value={density} onChange={(event) => applyDensity(event.target.value as Density)} aria-label="Content density"><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></div>
          <div className="settings-control-row"><div><strong>Reduce motion</strong><small>Respect your preference for fewer interface animations.</small></div><label className="settings-switch"><input type="checkbox" checked={reducedMotion} onChange={(event) => applyMotion(event.target.checked)} /><span>{reducedMotion ? "On" : "Off"}</span></label></div>
        </section>

        <section className="settings-panel" id="account"><header><span><UserRound size={18} /></span><div><h2>Account profile</h2><p>Read-only account information from your authenticated session.</p></div></header>
          {account && <dl className="settings-account-grid"><div><dt>Email</dt><dd>{account.email}</dd></div><div><dt>Role</dt><dd>{account.role === "admin" ? "Administrator" : "Standard user"}</dd></div><div><dt>Account status</dt><dd><span className={`settings-status ${account.is_active ? "active" : "inactive"}`}>{account.is_active ? "Active" : "Deactivated"}</span></dd></div><div><dt>Registered</dt><dd>{dateTime(account.created_at)}</dd></div><div><dt>Last successful login</dt><dd>{account.last_login_at ? dateTime(account.last_login_at) : "Not recorded yet"}</dd></div></dl>}
          <p className="settings-inline-note">Profile details are read-only. Account roles can only be managed by an administrator through User Management.</p>
        </section>

        <section className="settings-panel" id="security"><header><span><ShieldCheck size={18} /></span><div><h2>Security &amp; sessions</h2><p>Session details are based on the current signed-in session.</p></div></header>
          <div className="settings-session-card"><span><Check size={16} /></span><div><strong>Current session active</strong><small>Expires {expiresAt ? dateTime(expiresAt) : "Unavailable"}. Session tokens are never displayed.</small></div><button className="button button-secondary" type="button" onClick={() => void fetch(`${apiBase}/api/v1/auth/logout`, { method: "POST", credentials: "include" }).then(() => { window.location.assign("/login"); })}><LogOut size={15} />Sign out</button></div>
          <form className="settings-password-form" onSubmit={(event) => void changePassword(event)}><div className="settings-form-heading"><KeyRound size={17} /><div><strong>Change password</strong><small>Use at least 12 characters. Your current password is required.</small></div></div><label>Current password<input type="password" autoComplete="current-password" required minLength={1} maxLength={128} value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label><div className="settings-password-grid"><label>New password<input type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label><label>Confirm new password<input type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} /></label></div><button className="button button-primary" type="submit" disabled={passwordBusy}>{passwordBusy ? "Updating…" : "Update password"}</button></form>
        </section>

        {account?.role === "admin" && <section className="settings-panel" id="workspace"><header><span><Building2 size={18} /></span><div><h2>Workspace access</h2><p>Sharing determines whether standard users can access a workspace’s hospitals and datasets.</p></div></header>
          {workspaces.length === 0 ? <div className="settings-empty">No workspaces are configured.</div> : workspaces.map((workspace) => <article className="settings-workspace-row" key={workspace.id}><div><strong>{workspace.name}</strong><small>{hospitals[workspace.id]?.filter((hospital) => !hospital.is_archived).map((hospital) => hospital.name).join(", ") || "No active hospitals"}</small><span className={`settings-status ${workspace.is_shared ? "active" : "inactive"}`}>{workspace.is_shared ? "Shared workspace" : "Admin-only workspace"}</span></div><button className="button button-secondary" type="button" disabled={busyWorkspace === workspace.id} onClick={() => void toggleSharing(workspace)}>{busyWorkspace === workspace.id ? "Saving…" : workspace.is_shared ? "Stop sharing" : "Share workspace"}</button></article>)}
        </section>}
        {account?.role === "user" && <section className="settings-panel" id="workspace"><header><span><Building2 size={18} /></span><div><h2>Accessible workspaces</h2><p>Your access follows the workspace’s current sharing settings.</p></div></header>{workspaces.length ? workspaces.map((workspace) => <article className="settings-workspace-row" key={workspace.id}><div><strong>{workspace.name}</strong><small>{hospitals[workspace.id]?.filter((hospital) => !hospital.is_archived).map((hospital) => hospital.name).join(", ") || "No active hospitals"}</small><span className="settings-status active">View and generate in shared workspace</span></div></article>) : <div className="settings-empty">No shared workspaces are currently available to your account.</div>}</section>}

        <section className="settings-panel" id="privacy"><header><span><Database size={18} /></span><div><h2>Data &amp; privacy</h2><p>How BedSynth AI handles generated operational data.</p></div></header><ul className="settings-privacy-list"><li>BedSynth AI generates synthetic hospital operations data and does not connect to real patient records.</li><li>Registered-user datasets follow the existing ownership and workspace access rules.</li><li>Guest datasets are temporary, expire after 24 hours, and are not available in permanent dataset history.</li></ul><p className="settings-inline-note">Do not enter patient-identifying or clinical information into the assistant.</p></section>

        <section className="settings-panel" id="about"><header><span><Activity size={18} /></span><div><h2>About BedSynth AI</h2><p>A synthetic hospital operations data studio for model testing.</p></div></header><div className="settings-about"><div className="settings-brand-mark"><Activity size={21} /></div><div><strong>BedSynth AI</strong><p>Configure virtual hospitals, generate reproducible synthetic operational datasets, and evaluate them for bed-occupancy and scheduling research.</p><small>Next.js · React · TypeScript · FastAPI · Python · SQLAlchemy · SQLite</small></div></div></section>
      </div>
    </div>
  </main>;
}
