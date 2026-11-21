"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { MonitorCog, Moon, Sun } from "lucide-react";

type Theme = "light" | "dark";

export default function SettingsPage() {
  const [theme, setTheme] = useState<Theme>("light");
  const [isAdmin, setIsAdmin] = useState(false);
  const [workspaces, setWorkspaces] = useState<{ id: number; name: string; is_shared: boolean }[]>([]);
  const [sharingError, setSharingError] = useState("");
  useEffect(() => {
    const saved = window.localStorage.getItem("bedsynth-theme");
    const current = saved === "dark" || saved === "light" ? saved : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    setTheme(current);
  }, []);

  useEffect(() => {
    const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
    fetch(`${apiBase}/api/v1/auth/me`, { credentials: "include", cache: "no-store" }).then((response) => response.ok ? response.json() : null).then(async (user) => {
      if (user?.role !== "admin") return;
      setIsAdmin(true);
      const response = await fetch(`${apiBase}/api/v1/admin/workspaces`, { credentials: "include", cache: "no-store" });
      if (!response.ok) throw new Error("Workspace access settings could not be loaded.");
      setWorkspaces(await response.json());
    }).catch((cause) => setSharingError(cause instanceof Error ? cause.message : "Workspace access settings could not be loaded."));
  }, []);

  function chooseTheme(next: Theme) {
    setTheme(next);
    window.dispatchEvent(new CustomEvent("bedsynth-theme-change", { detail: next }));
  }

  async function toggleSharing(workspace: { id: number; is_shared: boolean }) {
    const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
    setSharingError("");
    try {
      const response = await fetch(`${apiBase}/api/v1/admin/workspaces/${workspace.id}/sharing`, { method: "PATCH", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_shared: !workspace.is_shared }) });
      if (!response.ok) throw new Error("Workspace sharing could not be changed.");
      const updated = await response.json(); setWorkspaces((items) => items.map((item) => item.id === updated.id ? updated : item));
    } catch (cause) { setSharingError(cause instanceof Error ? cause.message : "Workspace sharing could not be changed."); }
  }

  return <main className="page-content settings-page" id="main-content">
    <div className="page-heading"><div><div className="page-kicker"><span className="kicker-line" /> PREFERENCES</div><h1>Settings</h1><p className="page-subtitle">Personalize how BedSynth AI appears on this device.</p></div></div>
    <motion.section className="generator-card settings-card" aria-labelledby="appearance-heading" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
      <div className="generator-card-header"><span className="generator-section-icon"><MonitorCog size={19} /></span><div><h2 id="appearance-heading">Appearance</h2><p>Your preference is stored locally in this browser.</p></div></div>
      <div className="settings-theme-options" role="group" aria-label="Color theme">
        <button type="button" className={`settings-theme-option${theme === "light" ? " is-selected" : ""}`} aria-pressed={theme === "light"} onClick={() => chooseTheme("light")}><Sun size={20} /><span><strong>Light</strong><small>Soft surfaces and clear contrast</small></span></button>
        <button type="button" className={`settings-theme-option${theme === "dark" ? " is-selected" : ""}`} aria-pressed={theme === "dark"} onClick={() => chooseTheme("dark")}><Moon size={20} /><span><strong>Dark</strong><small>Low-light workspace colors</small></span></button>
      </div>
      <p className="settings-note">Sidebar width and theme are saved in this browser. BedSynth AI does not connect real patient data.</p>
    </motion.section>
    {isAdmin && <motion.section className="generator-card settings-card" aria-labelledby="workspace-access-heading" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, delay: 0.04 }}><div className="generator-card-header"><span className="generator-section-icon"><MonitorCog size={19} /></span><div><h2 id="workspace-access-heading">Shared workspace access</h2><p>Only explicitly shared workspaces are visible to standard users.</p></div></div><div className="settings-admin-content">{sharingError && <p className="auth-error" role="alert">{sharingError}</p>}{workspaces.map((workspace) => <div className="admin-user-row" key={workspace.id}><span className="admin-user-main"><strong>{workspace.name}</strong><small>Workspace {workspace.id} · {workspace.is_shared ? "Visible to users" : "Administrator only"}</small></span><button className="studio-button studio-button-secondary studio-small-button" type="button" onClick={() => void toggleSharing(workspace)}>{workspace.is_shared ? "Stop sharing" : "Share workspace"}</button></div>)}</div></motion.section>}
  </main>;
}
