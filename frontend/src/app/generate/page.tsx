"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowLeft, ArrowUpRight, BedDouble, Check, CircleAlert, FlaskConical, LoaderCircle, RefreshCw, ShieldCheck, Siren, TrendingUp, Waves, Sun } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

type Workspace = { id: number; name: string };
type Bed = { status: string };
type Department = { id: number; name: string; code: string; is_archived: boolean; beds: Bed[] };
type Hospital = { id: number; workspace_id: number; name: string; code: string; is_archived: boolean; departments: Department[] };
type ScenarioId = "normal_operations" | "high_patient_inflow" | "seasonal_disease_surge" | "emergency_surge" | "low_occupancy";
type AgeDistribution = { children_0_17: number; young_adults_18_35: number; middle_aged_adults_36_59: number; older_adults_60_79: number; elderly_80_plus: number };
type GenderDistribution = { male: number; female: number; other: number };
type PatientProfile = { minimum_age: number; maximum_age: number; age_distribution: AgeDistribution; gender_distribution: GenderDistribution };
type FormConfig = { start_date: string; end_date: string; target_admissions: number; target_occupancy_pct: number; seed: number; scenario: ScenarioId; patient_profile: PatientProfile };
type AssistantHandoff = { workspace_id: number; hospital_id: number; start_date: string; end_date: string; target_admissions: number; target_occupancy_pct: number; seed: number; department_ids: number[] | null };
type Preview = {
  hospital_id: number; hospital_name: string; workspace_id: number; start_date: string; end_date: string;
  target_admissions: number; projected_admissions: number; target_occupancy_pct: number; scenario: ScenarioId; patient_profile: PatientProfile; seed: number;
  departments: { department_id: number; department_name: string; operational_beds: number }[];
  total_operational_beds: number; planned_peak_occupied_beds: number; occupancy_snapshots_planned: number; preview_token: string;
};
type Run = {
  run_id: string; workspace_id: number; hospital_id: number; config: Record<string, unknown>; seed: number;
  status: "generating" | "completed" | "failed"; started_at: string; completed_at: string | null;
  patients_count: number; admissions_count: number; discharges_count: number; transfers_count: number; snapshots_count: number; error_message: string | null;
};

const scenarios = [
  { id: "normal_operations", name: "Normal Operations", description: "Steady admissions, balanced department activity, and the configured occupancy target.", Icon: Activity },
  { id: "high_patient_inflow", name: "High Patient Inflow", description: "Higher admission volume and bed pressure, with added emergency and general medicine demand.", Icon: TrendingUp },
  { id: "seasonal_disease_surge", name: "Seasonal Disease Surge", description: "Higher admission volume and fictional longer stays for selected synthetic age bands.", Icon: Waves },
  { id: "emergency_surge", name: "Emergency Surge", description: "Higher admission volume and emergency demand, with more modeled transfers.", Icon: Siren },
  { id: "low_occupancy", name: "Low Occupancy", description: "Lower admission volume and reduced concurrent bed demand.", Icon: Sun },
] as const;

const DEFAULT_PATIENT_PROFILE: PatientProfile = {
  minimum_age: 0,
  maximum_age: 120,
  age_distribution: { children_0_17: 20, young_adults_18_35: 20, middle_aged_adults_36_59: 20, older_adults_60_79: 20, elderly_80_plus: 20 },
  gender_distribution: { male: 34, female: 33, other: 33 },
};
const AGE_PROFILE_FIELDS: { key: keyof AgeDistribution; label: string }[] = [
  { key: "children_0_17", label: "Children · 0–17" },
  { key: "young_adults_18_35", label: "Young adults · 18–35" },
  { key: "middle_aged_adults_36_59", label: "Middle-aged adults · 36–59" },
  { key: "older_adults_60_79", label: "Older adults · 60–79" },
  { key: "elderly_80_plus", label: "Elderly · 80+" },
];
const GENDER_PROFILE_FIELDS: { key: keyof GenderDistribution; label: string }[] = [
  { key: "male", label: "Male" }, { key: "female", label: "Female" }, { key: "other", label: "Other" },
];

function copyDefaultPatientProfile(): PatientProfile {
  return {
    ...DEFAULT_PATIENT_PROFILE,
    age_distribution: { ...DEFAULT_PATIENT_PROFILE.age_distribution },
    gender_distribution: { ...DEFAULT_PATIENT_PROFILE.gender_distribution },
  };
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
    cache: "no-store",
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item: { msg?: string }) => item.msg ?? "Invalid input").join(" ")
      : typeof detail === "string" ? detail : `Request failed (${response.status}).`;
    throw new Error(message);
  }
  return body as T;
}

function localDateString(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function SyntheticDataGeneratorPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [hospitals, setHospitals] = useState<Hospital[]>([]);
  const [hospitalId, setHospitalId] = useState<number | null>(null);
  const [selectedDepartmentIds, setSelectedDepartmentIds] = useState<number[]>([]);
  const [form, setForm] = useState<FormConfig>({ start_date: "", end_date: "", target_admissions: 50, target_occupancy_pct: 70, seed: 42, scenario: "normal_operations", patient_profile: copyDefaultPatientProfile() });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const [history, setHistory] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingHospitals, setLoadingHospitals] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [success, setSuccess] = useState("");
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const confirmRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const start = new Date();
    const end = new Date(start);
    end.setDate(end.getDate() + 6);
    setForm((current) => ({ ...current, start_date: localDateString(start), end_date: localDateString(end) }));
    const savedTheme = window.localStorage.getItem("bedsynth-theme");
    if (savedTheme === "light" || savedTheme === "dark") document.documentElement.dataset.theme = savedTheme;
  }, []);

  useEffect(() => {
    if (confirmOpen) confirmRef.current?.showModal();
    else if (confirmRef.current?.open) confirmRef.current.close();
  }, [confirmOpen]);

  const selectedHospital = useMemo(() => hospitals.find((hospital) => hospital.id === hospitalId) ?? null, [hospitals, hospitalId]);
  const activeDepartments = useMemo(() => selectedHospital?.departments.filter((department) => !department.is_archived) ?? [], [selectedHospital]);
  const allDepartmentIds = useMemo(() => activeDepartments.map((department) => department.id), [activeDepartments]);
  const effectiveDepartmentIds = selectedDepartmentIds.length ? selectedDepartmentIds : allDepartmentIds;
  const ageTotal = Object.values(form.patient_profile.age_distribution).reduce((total, value) => total + value, 0);
  const genderTotal = Object.values(form.patient_profile.gender_distribution).reduce((total, value) => total + value, 0);
  const profilePercentages = [...Object.values(form.patient_profile.age_distribution), ...Object.values(form.patient_profile.gender_distribution)];
  const percentagesValid = profilePercentages.every((value) => Number.isInteger(value) && value >= 0 && value <= 100);
  const ageLimitsValid = Number.isInteger(form.patient_profile.minimum_age) && Number.isInteger(form.patient_profile.maximum_age)
    && form.patient_profile.minimum_age >= 0 && form.patient_profile.maximum_age <= 120
    && form.patient_profile.minimum_age <= form.patient_profile.maximum_age;
  const selectedAgeGroupUnavailable = AGE_PROFILE_FIELDS.some(({ key }) => {
    const ranges: Record<keyof AgeDistribution, [number, number]> = {
      children_0_17: [0, 17], young_adults_18_35: [18, 35], middle_aged_adults_36_59: [36, 59], older_adults_60_79: [60, 79], elderly_80_plus: [80, 120],
    };
    const [groupMin, groupMax] = ranges[key];
    return form.patient_profile.age_distribution[key] > 0 && (groupMax < form.patient_profile.minimum_age || groupMin > form.patient_profile.maximum_age);
  });
  const patientProfileValid = percentagesValid && ageTotal === 100 && genderTotal === 100 && ageLimitsValid && !selectedAgeGroupUnavailable;

  async function loadHospitals(id: number, assistantHandoff?: AssistantHandoff) {
    setLoadingHospitals(true);
    setHospitals([]); setHospitalId(null); setSelectedDepartmentIds([]); setPreview(null); setHistory([]);
    try {
      const entries = await api<Hospital[]>(`/api/v1/workspaces/${id}/hospitals`);
      setHospitals(entries);
      const handoffHospital = assistantHandoff && assistantHandoff.workspace_id === id
        ? entries.find((hospital) => hospital.id === assistantHandoff.hospital_id)
        : undefined;
      setHospitalId(handoffHospital?.id ?? entries[0]?.id ?? null);
      if (assistantHandoff) {
        if (handoffHospital) {
          setForm({ start_date: assistantHandoff.start_date, end_date: assistantHandoff.end_date, target_admissions: assistantHandoff.target_admissions, target_occupancy_pct: assistantHandoff.target_occupancy_pct, seed: assistantHandoff.seed, scenario: "normal_operations", patient_profile: copyDefaultPatientProfile() });
          setSelectedDepartmentIds(assistantHandoff.department_ids ?? []);
          setSuccess("Assistant configuration loaded. Review it and request a generation preview before confirmation.");
        } else {
          setError("The approved assistant hospital is no longer active in this workspace. Choose an active hospital and review the configuration.");
        }
        window.sessionStorage.removeItem("bedsynth-approved-assistant-config");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load hospitals.");
    } finally { setLoadingHospitals(false); }
  }

  useEffect(() => {
    let mounted = true;
    async function initialize() {
      try {
        const [health, workspaceEntries] = await Promise.all([
          fetch(`${apiBase}/health`, { cache: "no-store" }).then((response) => {
            if (!response.ok) throw new Error("Backend health check failed.");
            return response.json() as Promise<{ status: string }>;
          }),
          api<Workspace[]>("/api/v1/workspaces"),
        ]);
        if (!mounted) return;
        setApiOnline(health.status === "ok");
        setWorkspaces(workspaceEntries);
        if (workspaceEntries.length) {
          let handoff: AssistantHandoff | undefined;
          try {
            const saved = window.sessionStorage.getItem("bedsynth-approved-assistant-config");
            if (saved) handoff = JSON.parse(saved) as AssistantHandoff;
          } catch {
            window.sessionStorage.removeItem("bedsynth-approved-assistant-config");
          }
          const targetWorkspaceId = handoff && workspaceEntries.some((workspace) => workspace.id === handoff?.workspace_id)
            ? handoff.workspace_id
            : workspaceEntries[0].id;
          setWorkspaceId(targetWorkspaceId);
          await loadHospitals(targetWorkspaceId, handoff);
        }
      } catch (cause) {
        if (!mounted) return;
        setApiOnline(false);
        setError(cause instanceof Error ? cause.message : "Could not connect to the BedSynth API.");
      } finally { if (mounted) setLoading(false); }
    }
    void initialize();
    return () => { mounted = false; };
  }, []);

  async function loadHistory(hospital: Hospital) {
    setHistoryError("");
    try {
      const rows = await api<Run[]>(`/api/v1/workspaces/${hospital.workspace_id}/generation-runs?hospital_id=${hospital.id}`);
      setHistory(rows);
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : "Could not load generation history.");
    }
  }

  useEffect(() => {
    if (selectedHospital) void loadHistory(selectedHospital);
  }, [selectedHospital?.id]);

  function updateForm<K extends keyof FormConfig>(key: K, value: FormConfig[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setPreview(null); setIdempotencyKey(""); setError(""); setSuccess("");
  }

  function updatePatientProfile(profile: PatientProfile) {
    updateForm("patient_profile", profile);
  }

  function resetPatientProfile() {
    updatePatientProfile(copyDefaultPatientProfile());
  }

  function toggleDepartment(id: number) {
    const current = selectedDepartmentIds.length ? selectedDepartmentIds : allDepartmentIds;
    const next = current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id];
    setSelectedDepartmentIds(next.length === allDepartmentIds.length ? [] : next);
    setPreview(null); setIdempotencyKey("");
  }

  async function changeWorkspace(id: number) {
    setWorkspaceId(id); setError(""); setSuccess("");
    await loadHospitals(id);
  }

  async function makePreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedHospital) { setError("Choose an active hospital before previewing a generation."); return; }
    if (!patientProfileValid) { setError("Correct the patient profile ranges and percentages before previewing."); return; }
    if (form.target_admissions > 0 && form.target_occupancy_pct === 0) { setError("Target occupancy must be above 0 when generating admissions."); return; }
    if (form.target_admissions === 0 && form.target_occupancy_pct !== 0) { setError("Set target occupancy to 0 when generating 0 admissions."); return; }
    const startMs = Date.parse(`${form.start_date}T00:00:00Z`);
    const endMs = Date.parse(`${form.end_date}T00:00:00Z`);
    if (endMs < startMs || (endMs - startMs) / 86_400_000 > 365) { setError("Choose a valid date range of no more than 366 calendar days."); return; }
    setPreviewing(true); setError(""); setSuccess(""); setPreview(null);
    try {
      const config = {
        ...form,
        target_admissions: Number(form.target_admissions),
        target_occupancy_pct: Number(form.target_occupancy_pct),
        seed: Number(form.seed),
        scenario: form.scenario,
        department_ids: selectedDepartmentIds.length ? selectedDepartmentIds : null,
      };
      const result = await api<Preview>(`/api/v1/hospitals/${selectedHospital.id}/generation-runs/preview`, { method: "POST", body: JSON.stringify(config) });
      setPreview(result);
      setIdempotencyKey(crypto.randomUUID());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create a generation preview.");
    } finally { setPreviewing(false); }
  }

  async function runGeneration() {
    if (!preview || !selectedHospital || !idempotencyKey) return;
    setGenerating(true); setConfirmOpen(false); setError(""); setSuccess("");
    try {
      const result = await api<Run>(`/api/v1/hospitals/${selectedHospital.id}/generation-runs`, {
        method: "POST",
        body: JSON.stringify({
          start_date: form.start_date,
          end_date: form.end_date,
          target_admissions: Number(form.target_admissions),
          target_occupancy_pct: Number(form.target_occupancy_pct),
          seed: Number(form.seed),
          scenario: form.scenario,
          patient_profile: form.patient_profile,
          department_ids: selectedDepartmentIds.length ? selectedDepartmentIds : null,
          idempotency_key: idempotencyKey,
          preview_token: preview.preview_token,
        }),
      });
      if (result.status === "failed") {
        setError(result.error_message ?? "Generation failed. No generated records were committed.");
        setPreview(null); setIdempotencyKey("");
      }
      else if (result.status === "completed") setSuccess(`Generation completed: ${result.patients_count} synthetic patients, ${result.admissions_count} admissions, ${result.transfers_count} transfers, and ${result.snapshots_count} occupancy snapshots.`);
      await loadHistory(selectedHospital);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not generate the dataset.");
      if (cause instanceof Error && (cause.message.toLowerCase().includes("preview") || cause.message.toLowerCase().includes("idempotency"))) {
        setPreview(null); setIdempotencyKey("");
      }
    } finally { setGenerating(false); }
  }

  const hasDepartments = activeDepartments.length > 0;

  return (
    <main className="generator-page" id="main-content">
      <header className="generator-topbar">
        <Link href="/" className="generator-brand"><span className="generator-brand-mark"><Activity size={19} /></span><span>BedSynth <strong>AI</strong></span></Link>
        <nav aria-label="Workspace navigation"><Link href="/" className="generator-nav-link"><ArrowLeft size={15} /> Overview</Link><Link href="/assistant" className="generator-nav-link">AI Assistant <ArrowUpRight size={14} /></Link><Link href="/hospitals" className="generator-nav-link">Hospital Studio <ArrowUpRight size={14} /></Link><Link href="/validation" className="generator-nav-link">Data validation <ArrowUpRight size={14} /></Link></nav>
      </header>

      <div className="generator-content">
        <div className="generator-heading"><div><div className="generator-kicker"><FlaskConical size={14} /> SYNTHETIC OPERATIONS</div><h1>Synthetic Data Generator</h1><p>Build a reproducible, hospital-scoped operations dataset from your configured bed inventory.</p></div><span className={`generator-api-state ${apiOnline === true ? "is-online" : apiOnline === false ? "is-offline" : ""}`} role="status"><span />{apiOnline === true ? "Backend connected" : apiOnline === false ? "Backend unavailable" : "Checking backend"}</span></div>

        {error && <div className="generator-alert generator-alert-error" role="alert"><CircleAlert size={18} /><span>{error}</span></div>}
        {success && <div className="generator-alert generator-alert-success" role="status"><Check size={18} /><span>{success}</span></div>}
        {loading && <div className="generator-loading"><LoaderCircle className="generator-spin" size={22} /> Connecting to your workspace…</div>}
        {!loading && workspaces.length === 0 && <div className="generator-empty"><Building2Icon /><h2>No workspace found</h2><p>Create a workspace and configure an active hospital with departments and operational beds first.</p><Link className="generator-button generator-button-primary" href="/hospitals">Open Hospital Studio <ArrowUpRight size={16} /></Link></div>}
        {!loading && workspaces.length > 0 && <>
          {!selectedHospital && !loadingHospitals && <div className="generator-empty"><Building2Icon /><h2>No active hospitals configured</h2><p>Generation requires a hospital, at least one active department, and operational beds.</p><Link className="generator-button generator-button-primary" href="/hospitals">Configure a hospital <ArrowUpRight size={16} /></Link></div>}
          <div className="generator-grid">
            <section className="generator-card" aria-labelledby="config-heading">
              <div className="generator-card-header"><span className="generator-section-icon"><FlaskConical size={18} /></span><div><h2 id="config-heading">Generation configuration</h2><p>Choose the scope and parameters for this deterministic run.</p></div></div>
              <form className="generator-form" onSubmit={makePreview}>
                {workspaces.length > 1 && <label>Workspace<select value={workspaceId ?? ""} disabled={generating} onChange={(event) => void changeWorkspace(Number(event.target.value))}>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select></label>}
                <label>Hospital<select required value={hospitalId ?? ""} disabled={loadingHospitals || generating || hospitals.length === 0} onChange={(event) => { setHospitalId(Number(event.target.value)); setSelectedDepartmentIds([]); setPreview(null); setIdempotencyKey(""); }}>{hospitals.map((hospital) => <option key={hospital.id} value={hospital.id}>{hospital.name} · {hospital.code}</option>)}</select><small>Only active hospitals in the selected workspace are available.</small></label>
                <fieldset className="generator-fieldset"><legend>Generation period</legend><div className="generator-two-column"><label>Start date<input type="date" required disabled={generating} value={form.start_date} onChange={(event) => updateForm("start_date", event.target.value)} /></label><label>End date<input type="date" required disabled={generating} min={form.start_date} value={form.end_date} onChange={(event) => updateForm("end_date", event.target.value)} /></label></div></fieldset>
                <div className="generator-two-column"><label>Base admissions<input type="number" min={0} max={5000} required disabled={generating} value={form.target_admissions} onChange={(event) => updateForm("target_admissions", Number(event.target.value))} /><small>The selected scenario adjusts this volume; preview shows the projected count (maximum 5,000).</small></label><label>Random seed<input type="number" min={0} max={2147483647} required disabled={generating} value={form.seed} onChange={(event) => updateForm("seed", Number(event.target.value))} /><small>Reuse the same seed and configuration to reproduce records.</small></label></div>
                <label className="generator-occupancy-label">Target occupancy <strong>{form.target_occupancy_pct}%</strong><input type="range" min={0} max={100} step={1} disabled={generating} value={form.target_occupancy_pct} onChange={(event) => updateForm("target_occupancy_pct", Number(event.target.value))} aria-label="Target occupancy percentage" /><small>A scheduling target for peak concurrent bed assignments; snapshots report calculated occupancy.</small></label>
                <fieldset className="generator-fieldset scenario-fieldset"><legend>Operational scenario</legend><p className="scenario-help">Presets adjust the fictional demand pattern and volume. They are simulation assumptions, not real hospital statistics. Select one before previewing.</p><div className="scenario-grid" role="radiogroup" aria-label="Operational scenario">{scenarios.map(({ id, name, description, Icon }) => <label key={id} className={`scenario-option ${form.scenario === id ? "is-selected" : ""}`}><input type="radio" name="scenario" value={id} checked={form.scenario === id} disabled={generating} onChange={() => updateForm("scenario", id)} /><span className="scenario-option-icon"><Icon size={17} /></span><span className="scenario-option-copy"><strong>{name}</strong><small>{description}</small></span><span className="scenario-radio-mark" aria-hidden="true" /></label>)}</div></fieldset>
                <details className="patient-profile-details" open>
                  <summary><span className="patient-profile-summary-copy"><strong>Patient Profile Configuration</strong><small>Configure fictional ages and gender shares for the generated patients.</small></span></summary>
                  <div className="patient-profile-body">
                    <div className="patient-profile-body-header"><p>Demographic settings affect fictional records only. Percentage allocations are rounded deterministically for the projected patient count.</p><button type="button" className="generator-button generator-button-secondary patient-profile-reset" disabled={generating} onClick={resetPatientProfile}>Reset to Defaults</button></div>
                    <div className="patient-profile-age-limits">
                      <label>Minimum age<input type="number" min={0} max={120} step={1} value={form.patient_profile.minimum_age} disabled={generating} aria-invalid={!ageLimitsValid} onChange={(event) => updatePatientProfile({ ...form.patient_profile, minimum_age: Number(event.target.value) })} /></label>
                      <label>Maximum age<input type="number" min={0} max={120} step={1} value={form.patient_profile.maximum_age} disabled={generating} aria-invalid={!ageLimitsValid} onChange={(event) => updatePatientProfile({ ...form.patient_profile, maximum_age: Number(event.target.value) })} /></label>
                      <small>Generated ages stay within these inclusive limits.</small>
                    </div>
                    <div className="patient-profile-distributions">
                      <fieldset className="patient-profile-group"><legend>Age distribution</legend><p>Use whole-number percentages. These defaults are a neutral synthetic mix, not population estimates.</p><div className="patient-profile-input-grid patient-age-input-grid">{AGE_PROFILE_FIELDS.map((field) => <label key={field.key}>{field.label}<span><input type="number" min={0} max={100} step={1} value={form.patient_profile.age_distribution[field.key]} disabled={generating} aria-invalid={ageTotal !== 100} aria-describedby="age-distribution-total" onChange={(event) => updatePatientProfile({ ...form.patient_profile, age_distribution: { ...form.patient_profile.age_distribution, [field.key]: Number(event.target.value) } })} /><span>%</span></span></label>)}</div><output id="age-distribution-total" className={`patient-profile-total ${ageTotal === 100 ? "is-valid" : "is-invalid"}`} aria-live="polite">Age total: {ageTotal}% {ageTotal === 100 ? "✓" : "· must equal 100%"}</output></fieldset>
                      <fieldset className="patient-profile-group"><legend>Gender distribution</legend><p>Gender shares use the same deterministic percentage allocation.</p><div className="patient-profile-input-grid patient-gender-input-grid">{GENDER_PROFILE_FIELDS.map((field) => <label key={field.key}>{field.label}<span><input type="number" min={0} max={100} step={1} value={form.patient_profile.gender_distribution[field.key]} disabled={generating} aria-invalid={genderTotal !== 100} aria-describedby="gender-distribution-total" onChange={(event) => updatePatientProfile({ ...form.patient_profile, gender_distribution: { ...form.patient_profile.gender_distribution, [field.key]: Number(event.target.value) } })} /><span>%</span></span></label>)}</div><output id="gender-distribution-total" className={`patient-profile-total ${genderTotal === 100 ? "is-valid" : "is-invalid"}`} aria-live="polite">Gender total: {genderTotal}% {genderTotal === 100 ? "✓" : "· must equal 100%"}</output></fieldset>
                    </div>
                    {!ageLimitsValid && <p className="patient-profile-error" role="alert">Enter whole-number ages from 0 to 120, with maximum age on or above minimum age.</p>}
                    {selectedAgeGroupUnavailable && <p className="patient-profile-error" role="alert">An age group with a non-zero share does not overlap the configured age limits.</p>}
                  </div>
                </details>
                {hasDepartments && <fieldset className="generator-fieldset"><legend>Departments <span>(all active departments by default)</span></legend><div className="generator-department-list">{activeDepartments.map((department) => {
                  const operationalBeds = department.beds.filter((bed) => bed.status === "operational").length;
                  const checked = selectedDepartmentIds.length === 0 || selectedDepartmentIds.includes(department.id);
                  return <label key={department.id} className="generator-department-option"><input type="checkbox" checked={checked} disabled={generating} onChange={() => toggleDepartment(department.id)} /><span><strong>{department.name}</strong><small>{department.code} · {operationalBeds} operational beds</small></span></label>;
                })}</div></fieldset>}
                <div className="generator-privacy"><ShieldCheck size={17} /><span>Records are fictional. This generator does not accept or store real patient information.</span></div>
                <div className="generator-form-actions"><button className="generator-button generator-button-primary" disabled={!selectedHospital || previewing || generating || loadingHospitals}>{previewing ? <LoaderCircle className="generator-spin" size={16} /> : <RefreshCw size={16} />} {previewing ? "Preparing preview…" : "Preview generation"}</button></div>
              </form>
            </section>

            <aside className="generator-side-column">
              <section className="generator-card generator-summary-card" aria-labelledby="preview-heading">
                <div className="generator-card-header"><span className="generator-section-icon"><BedDouble size={18} /></span><div><h2 id="preview-heading">Generation preview</h2><p>Server-calculated scope and bed availability.</p></div></div>
                {!preview ? <div className="generator-summary-empty"><FlaskConical size={24} /><p>Configure a run and preview it to see the selected hospital, bed inventory, and expected record counts.</p></div> : <>
                  <div className="generator-summary-facts"><div><span>Hospital</span><strong>{preview.hospital_name}</strong></div><div><span>Operational scenario</span><strong>{scenarios.find((scenario) => scenario.id === preview.scenario)?.name ?? "Normal Operations"}</strong></div><div><span>Period</span><strong>{preview.start_date} – {preview.end_date}</strong></div><div><span>Base admissions</span><strong>{preview.target_admissions.toLocaleString()}</strong></div><div><span>Projected admissions</span><strong>{preview.projected_admissions.toLocaleString()}</strong></div><div><span>Target occupancy</span><strong>{preview.target_occupancy_pct}%</strong></div><div><span>Random seed</span><strong className="generator-mono">{preview.seed}</strong></div></div>
                  <section className="patient-profile-preview" aria-label="Preview patient profile"><h3>Patient profile</h3><p>Projected patients: {preview.projected_admissions.toLocaleString()} · Age limits: {preview.patient_profile.minimum_age}–{preview.patient_profile.maximum_age} years</p><strong>Age distribution</strong><div className="patient-preview-chips">{AGE_PROFILE_FIELDS.map((field) => <span key={field.key}>{field.label}: {preview.patient_profile.age_distribution[field.key]}%</span>)}</div><strong>Gender distribution</strong><div className="patient-preview-chips">{GENDER_PROFILE_FIELDS.map((field) => <span key={field.key}>{field.label}: {preview.patient_profile.gender_distribution[field.key]}%</span>)}</div></section>
                  <div className="generator-dept-summary"><h3>Included departments</h3>{preview.departments.map((department) => <div key={department.department_id}><span>{department.department_name}</span><strong>{department.operational_beds} beds</strong></div>)}</div>
                  <div className="generator-planned-stats"><div><strong>{preview.total_operational_beds}</strong><span>Operational beds</span></div><div><strong>{preview.planned_peak_occupied_beds}</strong><span>Planned peak occupied</span></div><div><strong>{preview.occupancy_snapshots_planned}</strong><span>Daily snapshots</span></div></div>
                  <p className="generator-summary-note">Actual occupancy is derived from generated assignment intervals. The requested target is a scheduling input, not a measured result.</p>
                  <button className="generator-button generator-button-primary generator-confirm-button" disabled={previewing || generating} onClick={() => setConfirmOpen(true)}>Review and generate <ArrowUpRight size={16} /></button>
                </>}
              </section>
            </aside>
          </div>

          <section className="generator-card generator-history" aria-labelledby="history-heading">
            <div className="generator-card-header"><span className="generator-section-icon"><Activity size={18} /></span><div><h2 id="history-heading">Generation history</h2><p>Completed and failed runs stored for this hospital.</p></div><button type="button" className="generator-refresh" onClick={() => selectedHospital && void loadHistory(selectedHospital)} disabled={!selectedHospital} aria-label="Refresh generation history"><RefreshCw size={16} /></button></div>
            {historyError && <p className="generator-inline-error" role="alert">{historyError}</p>}
            {history.length === 0 ? <div className="generator-history-empty">{historyError ? "History could not be loaded." : "No generation runs are recorded for this hospital yet."}</div> : <div className="generator-table-wrap"><table className="generator-history-table"><thead><tr><th>Run</th><th>Scenario</th><th>Started</th><th>Status</th><th>Patients</th><th>Admissions</th><th>Discharges</th><th>Transfers</th><th>Snapshots</th></tr></thead><tbody>{history.map((run) => <tr key={run.run_id}><td className="generator-run-id" title={run.run_id}>{run.run_id.slice(0, 8)}</td><td>{scenarios.find((scenario) => scenario.id === (run.config.request as { scenario?: string } | undefined)?.scenario)?.name ?? "Normal Operations"}</td><td>{new Date(run.started_at).toLocaleString()}</td><td><span className={`generator-status generator-status-${run.status}`}>{run.status}</span>{run.error_message && <small className="generator-run-error">{run.error_message}</small>}</td><td>{run.patients_count}</td><td>{run.admissions_count}</td><td>{run.discharges_count}</td><td>{run.transfers_count}</td><td>{run.snapshots_count}</td></tr>)}</tbody></table></div>}
          </section>
        </>}
      </div>

      <dialog ref={confirmRef} className="generator-dialog" aria-labelledby="generator-confirm-title" onCancel={(event) => { event.preventDefault(); setConfirmOpen(false); }}>
        <div className="generator-dialog-heading"><div><span className="generator-kicker">CONFIRM RUN</span><h2 id="generator-confirm-title">Generate synthetic dataset?</h2></div><button type="button" className="generator-dialog-close" aria-label="Close confirmation" onClick={() => setConfirmOpen(false)}>×</button></div>
        <p>This creates records for <strong>{preview?.hospital_name}</strong> using the previewed configuration. Generated records remain scoped to this hospital and workspace.</p>
        <div className="generator-dialog-summary"><span>{scenarios.find((scenario) => scenario.id === preview?.scenario)?.name ?? "Normal Operations"}</span><span>{preview?.projected_admissions.toLocaleString()} projected admissions</span><span>{preview?.departments.length} departments</span><span>Seed {preview?.seed}</span></div>
        <div className="generator-form-actions"><button type="button" className="generator-button generator-button-secondary" onClick={() => setConfirmOpen(false)}>Cancel</button><button type="button" className="generator-button generator-button-primary" disabled={generating} onClick={() => void runGeneration()}>{generating ? <LoaderCircle className="generator-spin" size={16} /> : <Check size={16} />} Confirm generation</button></div>
      </dialog>
      {generating && <div className="generator-progress" role="status"><LoaderCircle className="generator-spin" size={16} /> Creating synthetic records and validating event sequences…</div>}
    </main>
  );
}

function Building2Icon() {
  return <span className="generator-empty-icon"><BedDouble size={23} /></span>;
}
