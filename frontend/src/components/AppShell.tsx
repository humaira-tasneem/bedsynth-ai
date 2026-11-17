"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { backendHealthLabel } from "@/lib/assistant-status.mjs";
import {
  Activity, BarChart3, BedDouble, Building2, ChevronDown, Database,
  FlaskConical, LayoutDashboard, Menu, Moon, PanelLeftClose,
  PanelLeftOpen, ShieldCheck, Sparkles, Sun, X,
} from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const navigationGroups = [
  { label: "WORKSPACE", items: [
    { href: "/", label: "Overview", icon: LayoutDashboard },
    { href: "/hospitals", label: "Hospital Studio", icon: Building2 },
  ] },
  { label: "DATA GENERATION", items: [
    { href: "/generate", label: "Generator", icon: FlaskConical },
    { href: "/assistant", label: "AI Assistant", icon: Sparkles },
  ] },
  { label: "QUALITY & INSIGHTS", items: [
    { href: "/analytics", label: "Analytics", icon: BarChart3 },
    { href: "/datasets", label: "Datasets", icon: Database },
    { href: "/validation", label: "Data validation", icon: ShieldCheck },
  ] },
];
const navigation = navigationGroups.flatMap((group) => group.items);

function routeLabel(pathname: string) {
  if (pathname.startsWith("/datasets/")) return "Dataset details";
  return navigation.find((item) => item.href === pathname)?.label ?? "Workspace";
}

export default function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const [health, setHealth] = useState<"checking" | "online" | "offline">("checking");

  useEffect(() => {
    setCollapsed(window.localStorage.getItem("bedsynth-sidebar-collapsed") === "true");
    const savedTheme = window.localStorage.getItem("bedsynth-theme");
    const useDark = savedTheme ? savedTheme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    setDark(useDark);
    document.documentElement.dataset.theme = useDark ? "dark" : "light";
  }, []);

  useEffect(() => { setMobileOpen(false); }, [pathname]);

  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const response = await fetch(`${apiBase}/health`, { cache: "no-store" });
        const body = await response.json();
        if (!response.ok || body.status !== "ok") throw new Error("API unavailable");
        if (active) setHealth("online");
      } catch {
        if (active) setHealth("offline");
      }
    };
    void check();
    const timer = window.setInterval(check, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  function toggleSidebar() {
    setCollapsed((current) => {
      window.localStorage.setItem("bedsynth-sidebar-collapsed", String(!current));
      return !current;
    });
  }

  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.dataset.theme = next ? "dark" : "light";
    window.localStorage.setItem("bedsynth-theme", next ? "dark" : "light");
  }

  return <div className={`product-shell${collapsed ? " is-collapsed" : ""}`}>
    {mobileOpen && <button className="product-backdrop" type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
    <aside className={`product-sidebar${mobileOpen ? " is-open" : ""}`} aria-label="Main navigation">
      <div className="product-brand-row">
        <Link href="/" className="product-brand" aria-label="BedSynth AI overview"><span className="product-brand-mark"><Activity size={21} /></span><span className="product-brand-copy"><strong>BedSynth <em>AI</em></strong><small>OPERATIONS STUDIO</small></span></Link>
        <button className="product-icon-button product-mobile-close" type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><X size={19} /></button>
        <button className="product-icon-button product-collapse" type="button" onClick={toggleSidebar} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed}>{collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}</button>
      </div>
      <button className="product-workspace" type="button" title="My workspace organizes hospitals and hospital networks">
        <span className="product-workspace-avatar">B</span><span className="product-workspace-copy"><small>WORKSPACE</small><strong>My workspace</strong><span className="product-workspace-detail">Hospitals &amp; networks</span></span><ChevronDown size={15} />
      </button>
      <nav className="product-navigation" aria-label="Application sections">
        {navigationGroups.map((group) => <div className="product-nav-group" key={group.label}>
          <span className="product-nav-label">{group.label}</span>
          {group.items.map(({ href, label, icon: Icon }) => {
            const isActive = href === "/datasets" ? pathname.startsWith(href) : pathname === href;
            return <Link key={href} href={href} className={`product-nav-link${isActive ? " is-active" : ""}`} aria-current={isActive ? "page" : undefined} aria-label={collapsed ? label : undefined} title={collapsed ? label : undefined}>
              <Icon size={18} strokeWidth={1.9} /><span>{label}</span>
            </Link>;
          })}
        </div>)}
      </nav>
      <div className="product-sidebar-footer">
        <div className="product-privacy"><ShieldCheck size={17} /><span>PRIVACY &amp; DATA SAFETY<br /><strong>No patient data connected</strong></span></div>
      </div>
    </aside>

    <div className="product-main">
      <header className="product-topbar">
        <div className="product-topbar-leading">
          <button type="button" className="product-icon-button product-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <div className="product-breadcrumb"><span>Workspace</span><span aria-hidden="true">/</span><strong>{routeLabel(pathname)}</strong></div>
        </div>
        <div className="product-topbar-actions"><div className={`product-health health-${health}`} role="status" aria-live="polite"><i />{backendHealthLabel(health)}</div><button type="button" className="product-icon-button product-theme" onClick={toggleTheme} aria-label={`Switch to ${dark ? "light" : "dark"} theme`} title={`Switch to ${dark ? "light" : "dark"} theme`}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button></div>
      </header>
      <div className="product-route-frame">{children}</div>
    </div>
  </div>;
}
