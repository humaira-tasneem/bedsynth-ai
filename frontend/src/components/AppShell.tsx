"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { backendHealthLabel } from "@/lib/assistant-status.mjs";
import { landingPathForRole, restrictedDestination } from "@/lib/role-routing.mjs";
import { guestRouteAllowed } from "@/lib/guest-access.mjs";
import {
  Activity, BarChart3, Building2, ChevronDown, Database, LogOut, UserRoundCog,
  FlaskConical, LayoutDashboard, Menu, Moon, PanelLeftClose,
  PanelLeftOpen, ShieldCheck, Sparkles, Sun, X,
} from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const adminNavigationGroups = [
  { label: "PLATFORM", items: [
    { href: "/admin", label: "Admin Dashboard", icon: LayoutDashboard },
    { href: "/hospitals", label: "Hospital Management", icon: Building2 },
    { href: "/users", label: "User Management", icon: UserRoundCog },
    { href: "/admin/datasets", label: "All Datasets", icon: Database },
    { href: "/analytics", label: "Platform Analytics", icon: BarChart3 },
    { href: "/assistant", label: "AI Assistant", icon: Sparkles },
    { href: "/settings", label: "Settings", icon: Activity },
  ] },
];
const userNavigationGroups = [
  { label: "RESEARCH", items: [{ href: "/", label: "Dashboard", icon: LayoutDashboard }, { href: "/generate", label: "Generate Dataset", icon: FlaskConical }, { href: "/datasets", label: "My Datasets", icon: Database }, { href: "/analytics", label: "My Analytics", icon: BarChart3 }, { href: "/assistant", label: "AI Assistant", icon: Sparkles }] },
  { label: "PREFERENCES", items: [{ href: "/settings", label: "Settings", icon: Activity }] },
];
const guestNavigationGroups = [{ label: "GUEST MODE", items: [{ href: "/generate", label: "Generate Dataset", icon: FlaskConical }] }];

function routeLabel(pathname: string, navigation: { href: string; label: string }[]) {
  if (pathname.startsWith("/datasets/")) return "Dataset details";
  return navigation.find((item) => item.href === pathname)?.label ?? "Workspace";
}

export default function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const [motionPreference, setMotionPreference] = useState<"system" | "reduce" | "full">("system");
  const [health, setHealth] = useState<"checking" | "online" | "offline">("checking");
  const [identity, setIdentity] = useState<{ id: number; email: string; role: "admin" | "user" } | null>(null);
  const [guestSession, setGuestSession] = useState<{ expires_at: string } | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const isAuthPage = pathname === "/login" || pathname === "/register";
  const navigationGroups = identity?.role === "admin" ? adminNavigationGroups : guestSession ? guestNavigationGroups : userNavigationGroups;
  const navigation = navigationGroups.flatMap((group) => group.items);

  useEffect(() => {
    let active = true;
    const verifySession = async (initial = false) => {
      try {
        const response = await fetch(`${apiBase}/api/v1/auth/me`, { credentials: "include", cache: "no-store" });
        if (response.ok) {
          const user = await response.json();
          if (active) {
            setIdentity((current) => current && current.id === user.id && current.email === user.email && current.role === user.role ? current : user);
            setGuestSession(null); setAuthChecked(true);
          }
        } else if (response.status === 401) {
          const guestResponse = await fetch(`${apiBase}/api/v1/guest/session`, { credentials: "include", cache: "no-store" });
          const guest = guestResponse.ok ? await guestResponse.json() : null;
          if (active) { setIdentity(null); setGuestSession(guest); setAuthChecked(true); }
        } else if (initial && active) setAuthChecked(true);
      } catch {
        if (initial && active) { setIdentity(null); setAuthChecked(true); }
      }
    };
    void verifySession(true);
    const timer = window.setInterval(() => void verifySession(), 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!authChecked) return;
    if (!identity && !guestSession && !isAuthPage && pathname !== "/") router.replace("/");
    if (guestSession && !guestRouteAllowed(pathname)) router.replace("/generate");
    if (guestSession && pathname === "/") return;
    if (identity && isAuthPage) router.replace(landingPathForRole(identity.role));
    if (identity) {
      const restricted = restrictedDestination(identity.role, pathname);
      if (restricted) router.replace(restricted);
      else if (identity.role === "admin" && pathname === "/") router.replace("/admin");
    }
  }, [authChecked, guestSession, identity, isAuthPage, pathname, router]);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem("bedsynth-sidebar-collapsed") === "true");
    const savedMotion = window.localStorage.getItem("bedsynth-reduced-motion");
    setMotionPreference(savedMotion === null ? "system" : savedMotion === "true" ? "reduce" : "full");
    const savedTheme = window.localStorage.getItem("bedsynth-theme");
    const useDark = savedTheme ? savedTheme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    setDark(useDark);
    document.documentElement.dataset.theme = useDark ? "dark" : "light";
  }, []);

  useEffect(() => {
    const syncTheme = (event: Event) => {
      const theme = (event as CustomEvent<"light" | "dark">).detail;
      if (theme !== "light" && theme !== "dark") return;
      setDark(theme === "dark");
      document.documentElement.dataset.theme = theme;
      window.localStorage.setItem("bedsynth-theme", theme);
    };
    window.addEventListener("bedsynth-theme-change", syncTheme);
    return () => window.removeEventListener("bedsynth-theme-change", syncTheme);
  }, []);

  useEffect(() => {
    const sidebar = (event: Event) => setCollapsed(Boolean((event as CustomEvent<boolean>).detail));
    const motion = (event: Event) => setMotionPreference((event as CustomEvent<boolean>).detail ? "reduce" : "full");
    window.addEventListener("bedsynth-sidebar-change", sidebar);
    window.addEventListener("bedsynth-motion-change", motion);
    return () => { window.removeEventListener("bedsynth-sidebar-change", sidebar); window.removeEventListener("bedsynth-motion-change", motion); };
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

  if (!authChecked && pathname !== "/" && !isAuthPage) return <main className="auth-loading" role="status">Checking your secure session…</main>;
  if (isAuthPage) return <>{children}</>;
  if (!identity && !guestSession && pathname === "/") return <>{children}</>;
  if (!identity && !guestSession) return <main className="auth-loading" role="status">Returning to the BedSynth AI welcome page…</main>;

  async function logout() {
    if (guestSession) {
      await fetch(`${apiBase}/api/v1/guest/session`, { method: "DELETE", credentials: "include", headers: { Origin: window.location.origin } });
      setGuestSession(null);
      router.replace("/");
      return;
    }
    await fetch(`${apiBase}/api/v1/auth/logout`, { method: "POST", credentials: "include" });
    setIdentity(null);
    router.replace("/login");
  }

  return <div className={`product-shell${collapsed ? " is-collapsed" : ""}`}>
    {mobileOpen && <button className="product-backdrop" type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
    <aside className={`product-sidebar${mobileOpen ? " is-open" : ""}`} aria-label="Main navigation">
      <div className="product-brand-row">
        <Link href="/" className="product-brand" aria-label="BedSynth AI overview"><span className="product-brand-mark"><Activity size={21} /></span><span className="product-brand-copy"><strong>BedSynth <em>AI</em></strong><small>OPERATIONS STUDIO</small></span></Link>
        <button className="product-icon-button product-mobile-close" type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><X size={19} /></button>
        <button className="product-icon-button product-collapse" type="button" onClick={toggleSidebar} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed}>{collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}</button>
      </div>
      {!guestSession && <button className="product-workspace" type="button" title="My workspace organizes hospitals and hospital networks">
        <span className="product-workspace-avatar">B</span><span className="product-workspace-copy"><small>WORKSPACE</small><strong>My workspace</strong><span className="product-workspace-detail">Hospitals &amp; networks</span></span><ChevronDown size={15} />
      </button>}
      <nav className="product-navigation" aria-label="Application sections">
        {navigationGroups.map((group) => <div className="product-nav-group" key={group.label}>
          <span className="product-nav-label">{group.label}</span>
          {group.items.map(({ href, label, icon: Icon }) => {
            const isActive = href === "/datasets" ? pathname.startsWith(href)
              : href === "/admin/datasets" ? pathname === href || pathname.startsWith("/datasets/")
                : pathname === href;
            return <Link key={href} href={href} className={`product-nav-link${isActive ? " is-active" : ""}`} aria-current={isActive ? "page" : undefined} aria-label={collapsed ? label : undefined} title={collapsed ? label : undefined}>
              <Icon size={18} strokeWidth={1.9} /><span>{label}</span>
            </Link>;
          })}
        </div>)}
      </nav>
      <div className="product-sidebar-footer">
        <div className="product-privacy"><ShieldCheck size={17} /><span>{guestSession ? "TEMPORARY GUEST SESSION" : "PRIVACY & DATA SAFETY"}<br /><strong>{guestSession ? `Expires ${new Date(guestSession.expires_at).toLocaleString()}` : "No patient data connected"}</strong></span></div>
        <div className="product-user-identity"><span className="product-workspace-avatar">{guestSession ? "G" : identity?.email.slice(0, 1).toUpperCase()}</span><span className="product-workspace-copy"><small>{guestSession ? "GUEST MODE" : identity?.role === "admin" ? "ADMINISTRATOR" : "USER"}</small><strong>{guestSession ? "Temporary access" : identity?.email}</strong></span><button className="product-icon-button" type="button" onClick={logout} aria-label={guestSession ? "End guest session" : "Sign out"} title={guestSession ? "End guest session" : "Sign out"}><LogOut size={17} /></button></div>
        {guestSession && <Link className="product-nav-link" href="/register">Create an account</Link>}
      </div>
    </aside>

    <div className="product-main">
      <header className="product-topbar">
        <div className="product-topbar-leading">
          <button type="button" className="product-icon-button product-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <div className="product-breadcrumb"><span>Workspace</span><span aria-hidden="true">/</span><strong>{routeLabel(pathname, navigation)}</strong></div>
        </div>
        <div className="product-topbar-actions"><div className={`product-health health-${health}`} role="status" aria-live="polite"><i />{backendHealthLabel(health)}</div><button type="button" className="product-icon-button product-theme" onClick={toggleTheme} aria-label={`Switch to ${dark ? "light" : "dark"} theme`} title={`Switch to ${dark ? "light" : "dark"} theme`}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button></div>
      </header>
      <MotionConfig reducedMotion={motionPreference === "system" ? "user" : motionPreference === "reduce" ? "always" : "never"}>
        <AnimatePresence mode="sync" initial={false}>
          <motion.div key={pathname} className="product-route-frame" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.1, ease: "easeOut" }}>
            {children}
          </motion.div>
        </AnimatePresence>
      </MotionConfig>
    </div>
  </div>;
}
