"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  ArrowUpRight,
  BedDouble,
  Building2,
  Database,
  FlaskConical,
  LayoutDashboard,
  Menu,
  Moon,
  Network,
  Settings2,
  ShieldCheck,
  Sun,
  X,
} from "lucide-react";

type HealthState = "checking" | "online" | "offline";
type SectionId = "overview" | "network" | "hospitals" | "generate" | "validation" | "datasets" | "settings";
type WorkspaceSummary = { hospitals: number; departments: number; beds: number };

const navigation: { id: SectionId; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "network", label: "Hospital network", icon: Network },
  { id: "hospitals", label: "Hospital Studio", icon: Building2 },
  { id: "generate", label: "Generate dataset", icon: FlaskConical },
  { id: "validation", label: "Data validation", icon: ShieldCheck },
  { id: "datasets", label: "Datasets", icon: Database },
];

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export default function HomePage() {
  const router = useRouter();
  const pathname = usePathname();
  const [health, setHealth] = useState<HealthState>("checking");
  const [dark, setDark] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [active, setActive] = useState<SectionId>("overview");
  const [summary, setSummary] = useState<WorkspaceSummary | null>(null);
  const [summaryFailed, setSummaryFailed] = useState(false);

  useEffect(() => {
    const savedTheme = window.localStorage.getItem("bedsynth-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const useDark = savedTheme ? savedTheme === "dark" : prefersDark;
    setDark(useDark);
    document.documentElement.dataset.theme = useDark ? "dark" : "light";
  }, []);

  useEffect(() => {
    let mounted = true;
    async function loadSummary() {
      try {
        const workspacesResponse = await fetch(`${apiBase}/api/v1/workspaces`, { cache: "no-store" });
        if (!workspacesResponse.ok) throw new Error("Workspace request failed");
        const workspaces: { id: number }[] = await workspacesResponse.json();
        if (workspaces.length === 0) {
          if (mounted) setSummary({ hospitals: 0, departments: 0, beds: 0 });
          return;
        }
        const hospitalsResponse = await fetch(`${apiBase}/api/v1/workspaces/${workspaces[0].id}/hospitals`, { cache: "no-store" });
        if (!hospitalsResponse.ok) throw new Error("Hospital request failed");
        const hospitals: { departments: { is_archived: boolean; beds: { status: string }[] }[] }[] = await hospitalsResponse.json();
        if (mounted) setSummary({
          hospitals: hospitals.length,
          departments: hospitals.reduce((total, hospital) => total + hospital.departments.filter((department) => !department.is_archived).length, 0),
          beds: hospitals.reduce((total, hospital) => total + hospital.departments.flatMap((department) => department.beds).filter((bed) => bed.status !== "retired").length, 0),
        });
      } catch {
        if (mounted) setSummaryFailed(true);
      }
    }
    void loadSummary();
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    let activeRequest = true;
    const checkHealth = async () => {
      try {
        const response = await fetch(`${apiBase}/health`, { cache: "no-store" });
        if (!response.ok) throw new Error("Health check failed");
        const body: { status?: string } = await response.json();
        if (activeRequest) setHealth(body.status === "ok" ? "online" : "offline");
      } catch {
        if (activeRequest) setHealth("offline");
      }
    };
    void checkHealth();
    const interval = window.setInterval(checkHealth, 30000);
    return () => {
      activeRequest = false;
      window.clearInterval(interval);
    };
  }, []);

  function toggleTheme() {
    const nextDark = !dark;
    setDark(nextDark);
    document.documentElement.dataset.theme = nextDark ? "dark" : "light";
    window.localStorage.setItem("bedsynth-theme", nextDark ? "dark" : "light");
  }

  function selectSection(id: SectionId) {
    setActive(id);
    setMobileOpen(false);
    if (id === "hospitals") router.push("/hospitals");
    else if (id === "generate") router.push("/generate");
    else if (id === "validation") router.push("/validation");
    else if (pathname !== "/") router.push("/");
  }

  const currentSection = pathname === "/hospitals" ? "hospitals" : pathname === "/generate" ? "generate" : pathname === "/validation" ? "validation" : active;
  const selectedLabel = navigation.find((item) => item.id === currentSection)?.label ?? "Settings";

  return (
    <div className="app-shell">
      {mobileOpen && <button aria-label="Close navigation" className="mobile-backdrop" onClick={() => setMobileOpen(false)} />}
      <aside className={`sidebar ${mobileOpen ? "sidebar-open" : ""}`} aria-label="Main navigation">
        <div className="brand-row">
          <div className="brand-mark" aria-hidden="true"><Activity size={21} strokeWidth={2.4} /></div>
          <div className="brand-copy"><span className="brand-name">BedSynth<span> AI</span></span><span className="brand-caption">OPERATIONS STUDIO</span></div>
          <button className="icon-button sidebar-close" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X size={19} /></button>
        </div>

        <div className="workspace-switcher">
          <div className="workspace-avatar">B</div>
          <div className="workspace-copy"><span className="eyebrow">WORKSPACE</span><span className="workspace-name">My workspace</span></div>
        </div>

        <nav className="nav-groups">
          <span className="nav-heading">WORKSPACE</span>
          {navigation.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-item ${currentSection === id ? "nav-item-active" : ""}`} onClick={() => selectSection(id)} aria-current={currentSection === id ? "page" : undefined}>
              <Icon size={18} strokeWidth={1.9} /><span>{label}</span>
            </button>
          ))}
          <span className="nav-heading nav-heading-lower">PREFERENCES</span>
          <button className={`nav-item ${currentSection === "settings" ? "nav-item-active" : ""}`} onClick={() => selectSection("settings")} aria-current={currentSection === "settings" ? "page" : undefined}>
            <Settings2 size={18} strokeWidth={1.9} /><span>Settings</span>
          </button>
        </nav>

        <div className="sidebar-bottom">
          <div className="privacy-note"><ShieldCheck size={17} /><span>Synthetic data workspace<br /><strong>No patient data connected</strong></span></div>
          <div className="profile-button">
            <span className="profile-avatar" aria-hidden="true">WS</span><span className="profile-copy"><strong>Workspace owner</strong><small>Personal workspace</small></span>
          </div>
        </div>
      </aside>

      <main className="main-area" id="main-content">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu size={21} /></button>
          <div className="breadcrumbs"><span>Workspace</span><span className="crumb-divider">/</span><strong>{selectedLabel}</strong></div>
          <div className="topbar-actions">
            <div className={`health-pill health-${health}`} role="status" aria-live="polite">
              <span className="health-dot" />
              <span>{health === "checking" ? "Checking API" : health === "online" ? "API connected" : "API unavailable"}</span>
            </div>
            <button className="icon-button theme-button" onClick={toggleTheme} aria-label={`Switch to ${dark ? "light" : "dark"} theme`} title={`Switch to ${dark ? "light" : "dark"} theme`}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button>
          </div>
        </header>

        <div className="page-content">
          {active === "overview" ? (
            <>
              <div className="page-heading">
                <div><div className="page-kicker"><span className="kicker-line" /> HOSPITAL OPERATIONS DATA</div><h1>Good morning</h1><p className="page-subtitle">Your workspace for configuring and exploring synthetic hospital operations.</p></div>
                <button className="button button-primary" onClick={() => selectSection("hospitals")}><Building2 size={17} /> Set up a hospital <ArrowUpRight size={16} /></button>
              </div>

              <section className="welcome-banner" aria-labelledby="welcome-title">
                <div className="welcome-orb orb-one" /><div className="welcome-orb orb-two" />
                <div className="welcome-content"><span className="welcome-tag"><span className="welcome-tag-dot" /> GETTING STARTED</span><h2 id="welcome-title">Build your virtual hospital network</h2><p>Start by adding a hospital and its departments. Your operational data stays scoped to the right workspace and hospital.</p><button className="button button-banner" onClick={() => selectSection("network")}>Explore your workspace <ArrowUpRight size={16} /></button></div>
                <div className="welcome-illustration" aria-hidden="true"><div className="illustration-ring ring-outer" /><div className="illustration-ring ring-inner" /><div className="illustration-building"><Building2 size={56} strokeWidth={1.2} /></div><span className="illustration-node node-top"><Network size={17} /></span><span className="illustration-node node-left"><BedDouble size={16} /></span><span className="illustration-node node-right"><Activity size={16} /></span></div>
              </section>

              <section className="section-block" aria-labelledby="snapshot-title">
                <div className="section-title-row"><div><h2 id="snapshot-title">Workspace snapshot</h2><p className="section-subtitle">Your configured resources will appear here.</p></div><span className="snapshot-period">CURRENT WORKSPACE</span></div>
                <div className="snapshot-grid">
                  <article className="metric-card"><div className="metric-top"><span className="metric-icon metric-icon-teal"><Building2 size={18} /></span><span className="metric-label">HOSPITALS</span></div><div className="metric-empty">{summaryFailed ? "—" : summary?.hospitals ?? "…"}</div><p className="metric-foot">{summaryFailed ? "Could not load workspace" : summary?.hospitals === 0 ? "No hospitals configured" : "Active in this workspace"}</p></article>
                  <article className="metric-card"><div className="metric-top"><span className="metric-icon metric-icon-blue"><BedDouble size={18} /></span><span className="metric-label">DEPARTMENTS</span></div><div className="metric-empty">{summaryFailed ? "—" : summary?.departments ?? "…"}</div><p className="metric-foot">{summaryFailed ? "Could not load workspace" : "Active hospital departments"}</p></article>
                  <article className="metric-card"><div className="metric-top"><span className="metric-icon metric-icon-violet"><BedDouble size={18} /></span><span className="metric-label">BED INVENTORY</span></div><div className="metric-empty">{summaryFailed ? "—" : summary?.beds ?? "…"}</div><p className="metric-foot">Non-retired beds in this workspace</p></article>
                </div>
              </section>

              <section className="section-block setup-section" aria-labelledby="setup-title">
                <div className="section-title-row"><div><h2 id="setup-title">Your next steps</h2><p className="section-subtitle">A simple path to your first synthetic dataset.</p></div><span className="setup-progress">HOSPITAL CONFIGURATION</span></div>
                <div className="setup-list">
                  <button className="setup-row" onClick={() => selectSection("hospitals")}><span className="setup-number">01</span><span className="setup-row-icon"><Building2 size={19} /></span><span className="setup-row-copy"><strong>Open Hospital Studio</strong><small>Manage hospitals, departments, and bed inventory.</small></span><span className="setup-status">AVAILABLE <ArrowUpRight size={14} /></span></button>
                  <div className="setup-row setup-row-muted"><span className="setup-number">02</span><span className="setup-row-icon"><Network size={19} /></span><span className="setup-row-copy"><strong>Configure your network</strong><small>Create optional groupings for your hospitals.</small></span><span className="setup-status status-pending">IN HOSPITAL STUDIO</span></div>
                  <button className="setup-row" onClick={() => selectSection("generate")}><span className="setup-number">03</span><span className="setup-row-icon"><FlaskConical size={19} /></span><span className="setup-row-copy"><strong>Generate a dataset</strong><small>Configure and review a synthetic operations run.</small></span><span className="setup-status">AVAILABLE <ArrowUpRight size={14} /></span></button>
                </div>
              </section>

              <footer className="page-footer"><span>BedSynth AI <span className="footer-dot">·</span> Synthetic operations data for testing</span><span>Built with privacy and provenance in mind</span></footer>
            </>
          ) : (
            <section className="placeholder-panel"><div className="placeholder-icon"><Settings2 size={23} /></div><span className="page-kicker"><span className="kicker-line" /> WORKSPACE FOUNDATION</span><h1>{selectedLabel}</h1><p>This area is part of the BedSynth AI workspace shell. Its data workflows have not been implemented yet.</p><div className="placeholder-note"><ShieldCheck size={17} /><span>No sample records or generated results are being shown.</span></div><button className="button button-secondary" onClick={() => selectSection("overview")}>Return to overview</button></section>
          )}
        </div>
      </main>
    </div>
  );
}
