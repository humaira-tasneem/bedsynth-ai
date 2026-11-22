"use client";

import { useEffect, useState } from "react";
import { Check, KeyRound, LockKeyhole, LogOut, ShieldCheck, UserRound, X } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");
type Account = { id: number; email: string; role: "admin" | "user"; is_active: boolean; created_at: string; last_login_at: string | null };

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(""); const [success, setSuccess] = useState("");
  const [currentPassword, setCurrentPassword] = useState(""); const [newPassword, setNewPassword] = useState(""); const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true); setError("");
      try {
        const session = await get<{ account: Account; session_expires_at: string }>("/auth/settings");
        if (!active) return;
        setAccount(session.account); setExpiresAt(session.session_expires_at);
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "Settings could not be loaded."); }
      finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, []);

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
    <header className="page-heading"><div><div className="page-kicker"><span className="kicker-line" /> ACCOUNT & PLATFORM</div><h1>Settings Center</h1><p className="page-subtitle">Manage your account, security, and platform information.</p></div></header>
    {error && <div className="settings-feedback error" role="alert">{error}<button type="button" aria-label="Dismiss error" onClick={() => setError("")}><X size={16} /></button></div>}
    {success && <div className="settings-feedback success" role="status">{success}<button type="button" aria-label="Dismiss message" onClick={() => setSuccess("")}><X size={16} /></button></div>}
    {loading && <div className="generator-loading" role="status">Loading your settings…</div>}
    <div className="settings-center-grid">
      <nav className="settings-index" aria-label="Settings sections"><strong>SETTINGS</strong><a href="#account"><UserRound size={16} />Account</a><a href="#security"><LockKeyhole size={16} />Security</a></nav>
      <div className="settings-sections">
        <section className="settings-panel" id="account"><header><span><UserRound size={18} /></span><div><h2>Account profile</h2><p>Read-only account information from your authenticated session.</p></div></header>
          {account && <dl className="settings-account-grid"><div><dt>Email</dt><dd>{account.email}</dd></div><div><dt>Role</dt><dd>{account.role === "admin" ? "Administrator" : "Standard user"}</dd></div><div><dt>Account status</dt><dd><span className={`settings-status ${account.is_active ? "active" : "inactive"}`}>{account.is_active ? "Active" : "Deactivated"}</span></dd></div><div><dt>Registered</dt><dd>{dateTime(account.created_at)}</dd></div><div><dt>Last successful login</dt><dd>{account.last_login_at ? dateTime(account.last_login_at) : "Not recorded yet"}</dd></div></dl>}
          <p className="settings-inline-note">Profile details are read-only. Contact an administrator if your account role needs to change.</p>
        </section>

        <section className="settings-panel" id="security"><header><span><ShieldCheck size={18} /></span><div><h2>Security &amp; sessions</h2><p>Session details are based on the current signed-in session.</p></div></header>
          <div className="settings-session-card"><span><Check size={16} /></span><div><strong>Current session active</strong><small>Expires {expiresAt ? dateTime(expiresAt) : "Unavailable"}. Session tokens are never displayed.</small></div><button className="button button-secondary" type="button" onClick={() => void fetch(`${apiBase}/api/v1/auth/logout`, { method: "POST", credentials: "include" }).then(() => { window.location.assign("/login"); })}><LogOut size={15} />Sign out</button></div>
          <form className="settings-password-form" onSubmit={(event) => void changePassword(event)}><div className="settings-form-heading"><KeyRound size={17} /><div><strong>Change password</strong><small>Use at least 12 characters. Your current password is required.</small></div></div><label>Current password<input type="password" autoComplete="current-password" required minLength={1} maxLength={128} value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label><div className="settings-password-grid"><label>New password<input type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label><label>Confirm new password<input type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} /></label></div><button className="button button-primary" type="submit" disabled={passwordBusy}>{passwordBusy ? "Updating…" : "Update password"}</button></form>
        </section>


      </div>
    </div>
  </main>;
}
