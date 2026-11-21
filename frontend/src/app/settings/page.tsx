"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { MonitorCog, Moon, Sun } from "lucide-react";

type Theme = "light" | "dark";

export default function SettingsPage() {
  const [theme, setTheme] = useState<Theme>("light");
  useEffect(() => {
    const saved = window.localStorage.getItem("bedsynth-theme");
    const current = saved === "dark" || saved === "light" ? saved : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    setTheme(current);
  }, []);

  function chooseTheme(next: Theme) {
    setTheme(next);
    window.dispatchEvent(new CustomEvent("bedsynth-theme-change", { detail: next }));
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
  </main>;
}
