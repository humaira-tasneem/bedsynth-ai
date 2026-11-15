"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  ArrowUpRight,
  BedDouble,
  Building2,
  BarChart3,
  Database,
  FlaskConical,
  Network,
} from "lucide-react";

type SectionId = "overview" | "network" | "hospitals" | "generate" | "assistant" | "analytics" | "validation" | "datasets";
type WorkspaceSummary = { hospitals: number; departments: number; beds: number };

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export default function HomePage() {
  const router = useRouter();
  const [summary, setSummary] = useState<WorkspaceSummary | null>(null);
  const [summaryFailed, setSummaryFailed] = useState(false);

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

  function selectSection(id: SectionId) {
    const routes: Record<SectionId, string> = { overview: "/", network: "/hospitals", hospitals: "/hospitals", generate: "/generate", assistant: "/assistant", analytics: "/analytics", validation: "/validation", datasets: "/datasets" };
    router.push(routes[id]);
  }

  return (
    <main className="page-content dashboard-page" id="main-content">
          {
            <>
              <div className="page-heading">
                <div><div className="page-kicker"><span className="kicker-line" /> HOSPITAL OPERATIONS DATA</div><h1>Good morning</h1><p className="page-subtitle">My Workspace brings your hospitals and operational datasets together.</p></div>
                <div className="page-heading-actions"><button className="button button-secondary" onClick={() => selectSection("analytics")}><BarChart3 size={17} /> View analytics <ArrowUpRight size={16} /></button><button className="button button-primary" onClick={() => selectSection("hospitals")}><Building2 size={17} /> Set up a hospital <ArrowUpRight size={16} /></button></div>
              </div>

              <section className="welcome-banner" aria-labelledby="welcome-title">
                <div className="welcome-orb orb-one" /><div className="welcome-orb orb-two" />
                <div className="welcome-content"><span className="welcome-tag"><span className="welcome-tag-dot" /> WORKSPACE ORGANIZATION</span><h2 id="welcome-title">Organize hospitals and networks</h2><p>Hospitals and optional hospital networks live inside My Workspace. Departments, beds, and operational records stay scoped to each hospital.</p><button className="button button-banner" onClick={() => selectSection("network")}>Open Hospital Studio <ArrowUpRight size={16} /></button></div>
                <div className="welcome-illustration" aria-hidden="true"><div className="illustration-ring ring-outer" /><div className="illustration-ring ring-inner" /><div className="illustration-building"><Building2 size={56} strokeWidth={1.2} /></div><span className="illustration-node node-top"><Network size={17} /></span><span className="illustration-node node-left"><BedDouble size={16} /></span><span className="illustration-node node-right"><Activity size={16} /></span></div>
              </section>

              <section className="section-block" aria-labelledby="snapshot-title">
                <div className="section-title-row"><div><h2 id="snapshot-title">Workspace snapshot</h2><p className="section-subtitle">Configured hospitals, departments, and beds in this workspace.</p></div><span className="snapshot-period">CURRENT WORKSPACE</span></div>
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
          }
    </main>
  );
}
