"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { Activity, LockKeyhole } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export default function LoginPage() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch(`${apiBase}/api/v1/auth/login`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: form.get("email"), password: form.get("password") }) });
      if (!response.ok) throw new Error(response.status === 401 ? "Email or password is incorrect." : "Sign in could not be completed.");
      window.location.assign("/");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Sign in could not be completed."); setBusy(false); }
  }
  return <main className="auth-page"><section className="auth-card"><div className="auth-brand"><span><Activity size={24} /></span><strong>BedSynth <em>AI</em></strong></div><LockKeyhole className="auth-icon" size={24} /><h1>Welcome back</h1><p>Sign in to your hospital operations workspace.</p><form onSubmit={submit}><label>Email<input name="email" type="email" autoComplete="username" required maxLength={254} /></label><label>Password<input name="password" type="password" autoComplete="current-password" required maxLength={128} /></label>{error && <p className="auth-error" role="alert">{error}</p>}<button className="auth-submit" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button></form><p className="auth-switch">New to BedSynth AI? <Link href="/register">Create an account</Link></p></section></main>;
}
