"use client";

import Link from "next/link";
import { useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  BedDouble,
  BarChart3,
  CalendarDays,
  Check,
  ClipboardCheck,
  Database,
  FlaskConical,
  Hospital,
  Menu,
  ShieldCheck,
  SlidersHorizontal,
  UsersRound,
  X,
} from "lucide-react";

const features = [
  { icon: FlaskConical, title: "Synthetic dataset generation", copy: "Configure hospital operations, choose a scenario, and review a validated preview before any records are created.", tone: "violet" },
  { icon: Hospital, title: "Hospital operations modeling", copy: "Model hospitals, departments, beds, admissions, discharges, transfers, and occupancy snapshots.", tone: "teal" },
  { icon: SlidersHorizontal, title: "Scenario-based generation", copy: "Choose an operational scenario and review a validated preview before creating records.", tone: "purple" },
  { icon: BarChart3, title: "Analytics", copy: "Explore occupancy patterns and department-level insights from your own runs.", tone: "blue" },
  { icon: ClipboardCheck, title: "Data quality and validation", copy: "Check generated records for operational consistency and inspect validation results before analysis.", tone: "amber" },
  { icon: Database, title: "Dataset management", copy: "Review available datasets, download CSV exports and manifests, and revisit your private run history.", tone: "coral" },
];

const steps = [
  { number: "01", icon: Hospital, title: "Choose a hospital", copy: "Select an available hospital and its configured departments and operational beds." },
  { number: "02", icon: SlidersHorizontal, title: "Configure your dataset", copy: "Set a date range, admission count, scenario, and optional patient and operations parameters." },
  { number: "03", icon: BarChart3, title: "Generate and analyze", copy: "Preview and validate the run, confirm generation, then explore and export the results." },
];

function Brand() {
  return <Link className="landing-brand" href="/" aria-label="BedSynth AI home"><span className="landing-brand-mark"><Activity size={21} strokeWidth={2.2} /></span><span className="landing-brand-copy"><strong>BedSynth <i>AI</i></strong><small>OPERATIONS STUDIO</small></span></Link>;
}

function ProductPreview({ reduceMotion }: { reduceMotion: boolean | null }) {
  return <div className="landing-preview-wrap">
    <div className="landing-orbit landing-orbit-one" aria-hidden="true" />
    <div className="landing-orbit landing-orbit-two" aria-hidden="true" />
    <motion.article className="landing-product-preview" initial={reduceMotion ? false : { opacity: 0, y: 20, rotate: 1.1 }} animate={{ opacity: 1, y: 0, rotate: 0 }} transition={{ duration: 0.65, delay: reduceMotion ? 0 : 0.12 }}>
      <header className="preview-window-bar"><span className="preview-window-dots"><i /><i /><i /></span><span className="preview-window-label"><Activity size={12} /> BedSynth AI / Analytics</span><span className="preview-window-status"><i /> Sample</span></header>
      <div className="preview-dashboard">
        <div className="preview-sidebar" aria-hidden="true"><span className="preview-side-logo"><Activity size={15} /></span><i className="active" /><i /><i /><i /><i /></div>
        <div className="preview-main">
          <div className="preview-title-row"><div><span className="preview-eyebrow">RESEARCH WORKSPACE</span><h2>Operations overview</h2><p>Illustrative dashboard preview</p></div><span className="preview-date"><CalendarDays size={12} /> Sample period</span></div>
          <div className="preview-stat-grid">
            <div><span>Occupancy</span><strong>78.4<small>%</small></strong><i className="preview-stat-line teal-line" /></div>
            <div><span>Admissions</span><strong>248</strong><i className="preview-stat-line purple-line" /></div>
            <div><span>Available beds</span><strong>36</strong><i className="preview-stat-line blue-line" /></div>
          </div>
          <div className="preview-chart-card">
            <div className="preview-chart-heading"><span><strong>Bed occupancy trend</strong><small>Illustrative sample data</small></span><span className="preview-chart-legend"><i /> Occupancy</span></div>
            <svg className="preview-chart" viewBox="0 0 520 145" role="img" aria-label="Illustrative occupancy trend chart">
              <defs><linearGradient id="previewFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#8178f2" stopOpacity=".22" /><stop offset="100%" stopColor="#8178f2" stopOpacity="0" /></linearGradient></defs>
              <path className="preview-gridline" d="M0 25H520M0 65H520M0 105H520" />
              <path d="M0 102 C30 96 35 69 68 75 S112 102 148 84 S192 39 230 54 S270 88 305 67 S350 42 382 56 S425 95 458 62 S494 40 520 27 V145 H0Z" fill="url(#previewFill)" />
              <path className="preview-chart-path" d="M0 102 C30 96 35 69 68 75 S112 102 148 84 S192 39 230 54 S270 88 305 67 S350 42 382 56 S425 95 458 62 S494 40 520 27" />
              <circle cx="458" cy="62" r="4" className="preview-chart-point" />
            </svg>
            <div className="preview-chart-axis"><span>Day 1</span><span>Day 7</span><span>Day 14</span><span>Day 21</span><span>Day 30</span></div>
          </div>
          <div className="preview-bottom-row"><span><BedDouble size={13} /> Department capacity</span><span className="preview-bars"><i /><i /><i /><i /><i /></span><span>Scenario: Normal</span></div>
        </div>
      </div>
      <footer className="preview-sample-note"><ShieldCheck size={12} /> Fictional sample values — not live hospital data</footer>
    </motion.article>
    <motion.div className="landing-float-note" initial={reduceMotion ? false : { opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.5, delay: reduceMotion ? 0 : 0.55 }}><span><Check size={15} /></span><div><strong>Reproducible by design</strong><small>Seeded generation workflow</small></div></motion.div>
  </div>;
}

export default function MarketingLanding() {
  const [menuOpen, setMenuOpen] = useState(false);
  const reduceMotion = useReducedMotion();
  const heroInitial = reduceMotion ? false : { opacity: 0, y: 16 };

  function closeMenu() { setMenuOpen(false); }

  return <main className="marketing-page" id="main-content">
    <section className="marketing-hero-shell" id="top">
      <div className="marketing-glow marketing-glow-one" aria-hidden="true" /><div className="marketing-glow marketing-glow-two" aria-hidden="true" />
      <header className="landing-nav-wrap">
        <nav className="landing-nav" aria-label="Main navigation">
          <Brand />
          <div className={`landing-nav-links${menuOpen ? " is-open" : ""}`} id="landing-menu">
            <a href="#platform" onClick={closeMenu}>Platform</a><a href="#how-it-works" onClick={closeMenu}>How it works</a><a href="#access" onClick={closeMenu}>Access</a>
            <div className="landing-mobile-actions"><Link href="/login" onClick={closeMenu}>Sign in</Link><Link href="/register" onClick={closeMenu}>Create account <ArrowRight size={14} /></Link></div>
          </div>
          <div className="landing-nav-actions"><Link className="landing-signin" href="/login">Sign in</Link><Link className="landing-nav-cta" href="/register">Create account <ArrowUpRight size={15} /></Link></div>
          <button className="landing-menu-toggle" type="button" aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"} aria-expanded={menuOpen} aria-controls="landing-menu" onClick={() => setMenuOpen((open) => !open)}>{menuOpen ? <X size={20} /> : <Menu size={20} />}</button>
        </nav>
      </header>

      <div className="landing-hero marketing-container">
        <motion.div className="landing-hero-copy" initial={heroInitial} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.55 }}>
          <div className="landing-overline"><span className="landing-overline-dot" /> SYNTHETIC HOSPITAL OPERATIONS</div>
          <h1>Generate smarter.<br /><span>Research better.</span></h1>
          <p className="landing-hero-description">Create reproducible synthetic hospital operations datasets for analytics, simulation, and optimization research — without using real patient records.</p>
          <motion.div className="landing-hero-actions" initial={reduceMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.18 }}>
            <Link className="landing-button landing-button-primary" href="/register">Create Free Account<ArrowRight size={17} /></Link>
            <Link className="landing-button landing-button-secondary" href="/login">Sign in<ArrowUpRight size={16} /></Link>
          </motion.div>
          <div className="landing-hero-assurance"><ShieldCheck size={15} /><span>Fictional data only</span><i />No patient records connected</div>
        </motion.div>
        <ProductPreview reduceMotion={reduceMotion} />
      </div>
      <div className="landing-hero-bottom" aria-hidden="true"><span>Built for operations research</span><i /><span>Designed for reproducibility</span><i /><span>Private by default</span></div>
    </section>

    <section className="landing-trust marketing-container" aria-label="Platform principles">
      <div className="landing-trust-intro"><span className="landing-section-eyebrow">A SAFE SPACE TO TEST IDEAS</span><h2>Research with confidence.</h2><p>A purpose-built workspace for exploring hospital operations using fictional, reproducible data.</p></div>
      <div className="landing-trust-items"><article><span className="landing-trust-icon trust-purple"><ShieldCheck size={19} /></span><div><strong>Synthetic by default</strong><small>No real patient records connected</small></div></article><article><span className="landing-trust-icon trust-teal"><Activity size={19} /></span><div><strong>Reproducible runs</strong><small>Repeat configurations with a seed</small></div></article><article><span className="landing-trust-icon trust-blue"><UsersRound size={19} /></span><div><strong>Built for research</strong><small>Analytics, simulation, and optimization</small></div></article></div>
    </section>

    <section className="landing-section landing-features" id="platform" aria-labelledby="platform-title">
      <div className="marketing-container"><div className="landing-section-heading"><span className="landing-section-eyebrow">ONE CONNECTED WORKSPACE</span><h2 id="platform-title">Everything you need to explore hospital operations</h2><p>From virtual bed inventory to exportable datasets, bring your operational testing workflow together.</p></div>
        <div className="landing-feature-grid">{features.map(({ icon: Icon, title, copy, tone }, index) => <motion.article className="landing-feature-card" key={title} initial={reduceMotion ? false : { opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: 0.16 }} transition={{ duration: 0.38, delay: reduceMotion ? 0 : (index % 3) * 0.06 }} whileHover={reduceMotion ? undefined : { y: -4 }}><span className={`landing-feature-icon feature-${tone}`}><Icon size={20} /></span><h3>{title}</h3><p>{copy}</p><span className="landing-feature-mark" aria-hidden="true"><ArrowUpRight size={15} /></span></motion.article>)}</div>
      </div>
    </section>

    <section className="landing-section landing-how" id="how-it-works" aria-labelledby="how-title">
      <div className="marketing-container"><div className="landing-section-heading landing-how-heading"><span className="landing-section-eyebrow">A CLEAR, CONTROLLED WORKFLOW</span><h2 id="how-title">From configuration to insight</h2><p>Every run follows the same transparent path, with review and validation before creation.</p></div>
        <div className="landing-steps">{steps.map(({ number, icon: Icon, title, copy }, index) => <motion.article className="landing-step" key={number} initial={reduceMotion ? false : { opacity: 0, y: 12 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: 0.2 }} transition={{ duration: 0.35, delay: reduceMotion ? 0 : index * 0.08 }}><div className="landing-step-top"><span className="landing-step-number">{number}</span><span className="landing-step-icon"><Icon size={21} /></span></div><h3>{title}</h3><p>{copy}</p>{index < steps.length - 1 && <span className="landing-step-connector" aria-hidden="true"><ArrowRight size={17} /></span>}</motion.article>)}</div>
      </div>
    </section>

    <section className="landing-section landing-access" id="access" aria-labelledby="access-title">
      <div className="marketing-container"><div className="landing-section-heading"><span className="landing-section-eyebrow">ACCESS YOUR RESEARCH WORKSPACE</span><h2 id="access-title">Sign in or create an account.</h2><p>Use your account to configure hospitals, generate datasets, and return to your research runs.</p></div>
        <div className="landing-access-grid">
          <article className="landing-access-card landing-signin-card"><div className="landing-access-card-top"><span className="landing-access-icon access-teal"><ShieldCheck size={21} /></span><span className="landing-access-tag">RETURNING USER</span></div><h3>Sign in</h3><p>Continue to your saved hospital operations research workspace.</p><ul><li><Check size={15} />Open your dashboards and datasets</li><li><Check size={15} />Continue generation workflows</li><li><Check size={15} />Review analytics and validation</li></ul><Link className="landing-button landing-button-signin" href="/login">Sign In<ArrowRight size={16} /></Link><small className="landing-expiry-note">New to BedSynth AI? <Link href="/register">Create an account</Link>.</small></article>
          <article className="landing-access-card landing-account-card"><div className="landing-access-card-top"><span className="landing-access-icon access-purple"><Database size={21} /></span><span className="landing-access-tag account-tag">RESEARCH WORKSPACE</span></div><h3>Create your account</h3><p>Set up an account to save your datasets and return to your research runs.</p><ul><li><Check size={15} />Keep your dataset history</li><li><Check size={15} />Download and compare your runs</li><li><Check size={15} />Explore analytics and validation</li></ul><Link className="landing-button landing-button-account" href="/register">Create Your Account<ArrowUpRight size={16} /></Link><small className="landing-expiry-note">Registration is for BedSynth AI research access.</small></article>
        </div>
        <p className="landing-privacy-note"><ShieldCheck size={15} />Never enter patient-identifying or clinical information. BedSynth AI is designed for fictional synthetic data.</p>
      </div>
    </section>

    <section className="landing-final-cta"><div className="marketing-container landing-final-cta-inner"><div><span className="landing-section-eyebrow">YOUR RESEARCH STARTS HERE</span><h2>Your next research dataset starts here.</h2><p>Explore hospital operations with a reproducible, fictional dataset workflow.</p></div><div className="landing-final-actions"><Link className="landing-button landing-button-light" href="/register">Create Account<ArrowRight size={16} /></Link><Link className="landing-button landing-button-outline" href="/login">Sign in</Link></div></div></section>

    <footer className="landing-footer"><div className="marketing-container landing-footer-main"><div className="landing-footer-brand"><Brand /><p>Fictional hospital operations data for research, analytics, and optimization testing.</p></div><div className="landing-footer-links"><div><strong>Explore</strong><a href="#platform">Platform</a><a href="#how-it-works">How it works</a><a href="#access">Account access</a></div><div><strong>Account</strong><Link href="/login">Sign in</Link><Link href="/register">Create account</Link></div></div></div><div className="marketing-container landing-footer-bottom"><span>© {new Date().getFullYear()} BedSynth AI · Operations Studio</span><span><ShieldCheck size={13} />Synthetic data only · No patient records connected</span></div></footer>
  </main>;
}
