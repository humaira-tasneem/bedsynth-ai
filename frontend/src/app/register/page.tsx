"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { Activity, ShieldCheck } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");

export default function RegisterPage() {
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setBusy(true); const form = new FormData(event.currentTarget);
    try {
      const response = await fetch(`${apiBase}/api/v1/auth/register`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: form.get("email"), password: form.get("password") }) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Account creation could not be completed.");
      window.location.assign("/");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Account creation could not be completed."); setBusy(false); }
  }
  return <main className="auth-page"><section className="auth-card"><div className="auth-brand"><span><Activity size={24} /></span><strong>BedSynth <em>AI</em></strong></div><ShieldCheck className="auth-icon" size={24} /><h1>Create your account</h1><p>Accounts start with standard user access. An administrator can update roles.</p><form onSubmit={submit}><label>Email<input name="email" type="email" autoComplete="email" required maxLength={254} /></label><label>Password<input name="password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} /><small>Use at least 12 characters.</small></label>{error && <p className="auth-error" role="alert">{error}</p>}<button className="auth-submit" type="submit" disabled={busy}>{busy ? "Creating account…" : "Create account"}</button></form><p className="auth-switch">Already registered? <Link href="/login">Sign in</Link></p></section></main>;
}
