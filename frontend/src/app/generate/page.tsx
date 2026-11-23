"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Activity, ArrowUpRight, BedDouble, Check, CircleAlert, FlaskConical, LoaderCircle, RefreshCw, ShieldCheck, Siren, TrendingUp, Waves, Sun } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");

type Workspace = { id: number; name: string };
type Bed = { status: string };
type Department = { id: number; name: string; code: string; is_archived: boolean; beds: Bed[] };
type Hospital = { id: number; workspace_id: number; name: string; code: string; is_archived: boolean; departments: Department[] };
type ScenarioId = "normal_operations" | "high_patient_inflow" | "seasonal_disease_surge" | "emergency_surge" | "low_occupancy";
type AgeDistribution = { children_0_17: number; young_adults_18_35: number; middle_aged_adults_36_59: number; older_adults_60_79: number; elderly_80_plus: number };
type GenderDistribution = { male: number; female: number; other: number };
type PatientProfile = { minimum_age: number; maximum_age: number; age_distribution: AgeDistribution; gender_distribution: GenderDistribution };
type ArrivalProfile = { planned_pct: number; emergency_pct: number; time_of_day: "uniform" | "daytime" | "evening" | "overnight"; day_of_week: "uniform" | "weekdays" | "weekends" };
type DepartmentDemandWeight = { department_id: number; weight: number };
type LengthOfStayProfile = { distribution: "fixed" | "triangular"; minimum_days: number; mode_days: number; maximum_days: number };
type DepartmentLengthOfStayProfile = LengthOfStayProfile & { department_id: number };
type WaitingQueueConfig = { priority_policy: "emergency_first" | "planned_first" | "arrival_order"; maximum_wait_hours: number };
type BedTurnaroundProfile = { distribution: "fixed" | "triangular"; minimum_hours: number; mode_hours: number; maximum_hours: number };
type DepartmentBedTurnaroundProfile = BedTurnaroundProfile & { department_id: number };
type FormConfig = { start_date: string; end_date: string; target_admissions: number; target_occupancy_pct: number; seed: number; scenario: ScenarioId; patient_profile: PatientProfile; arrival_profile: ArrivalProfile; department_demand_weights: DepartmentDemandWeight[]; length_of_stay_profile: LengthOfStayProfile; department_length_of_stay_profiles: DepartmentLengthOfStayProfile[]; waiting_queue: WaitingQueueConfig; bed_turnaround_profile: BedTurnaroundProfile; department_bed_turnaround_profiles: DepartmentBedTurnaroundProfile[] };
type Preview = {
  hospital_id: number; hospital_name: string; workspace_id: number; start_date: string; end_date: string;
  target_admissions: number; projected_admissions: number; target_occupancy_pct: number; scenario: ScenarioId; patient_profile: PatientProfile; arrival_profile: ArrivalProfile; length_of_stay_profile: LengthOfStayProfile; department_length_of_stay_profiles: DepartmentLengthOfStayProfile[]; projected_discharges: number; projected_ongoing_admissions: number; projected_assigned_admissions: number; projected_waiting_patients: number; projected_max_wait_exceeded: number; projected_unresolved_requests: number; projected_average_wait_minutes: number; projected_maximum_wait_minutes: number; projected_turnaround_events: number; projected_beds_cleaning_at_window_end: number; waiting_queue: WaitingQueueConfig; bed_turnaround_profile: BedTurnaroundProfile; department_bed_turnaround_profiles: DepartmentBedTurnaroundProfile[]; effective_admission_mix: { planned: number; emergency: number }; seed: number;
  departments: { department_id: number; department_name: string; operational_beds: number }[];
  total_operational_beds: number; planned_peak_occupied_beds: number; occupancy_snapshots_planned: number; preview_token: string;
};
type Run = {
  run_id: string; workspace_id: number; hospital_id: number; config: Record<string, unknown>; seed: number;
  status: "generating" | "completed" | "failed"; started_at: string; completed_at: string | null;
  patients_count: number; admissions_count: number; discharges_count: number; transfers_count: number; snapshots_count: number; waiting_queue_count: number | null; bed_turnaround_count: number | null; error_message: string | null;
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
const DEFAULT_ARRIVAL_PROFILE: ArrivalProfile = { planned_pct: 50, emergency_pct: 50, time_of_day: "uniform", day_of_week: "uniform" };
const DEFAULT_LOS_PROFILE: LengthOfStayProfile = { distribution: "triangular", minimum_days: 0.5, mode_days: 1.0, maximum_days: 2.0 };
const DEFAULT_WAITING_QUEUE: WaitingQueueConfig = { priority_policy: "emergency_first", maximum_wait_hours: 24 };
const DEFAULT_TURNAROUND: BedTurnaroundProfile = { distribution: "fixed", minimum_hours: 0.5, mode_hours: 0.5, maximum_hours: 0.5 };
const AGE_PROFILE_FIELDS: { key: keyof AgeDistribution; label: string; range: string }[] = [
  { key: "children_0_17", label: "Children", range: "0–17 years" },
  { key: "young_adults_18_35", label: "Young adults", range: "18–35 years" },
  { key: "middle_aged_adults_36_59", label: "Middle-aged adults", range: "36–59 years" },
  { key: "older_adults_60_79", label: "Older adults", range: "60–79 years" },
  { key: "elderly_80_plus", label: "Elderly", range: "80+ years" },
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

function copyDefaultLosProfile(): LengthOfStayProfile {
  return { ...DEFAULT_LOS_PROFILE };
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    credentials: "include",
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
  const [form, setForm] = useState<FormConfig>({ start_date: "", end_date: "", target_admissions: 50, target_occupancy_pct: 70, seed: 42, scenario: "normal_operations", patient_profile: copyDefaultPatientProfile(), arrival_profile: { ...DEFAULT_ARRIVAL_PROFILE }, department_demand_weights: [], length_of_stay_profile: copyDefaultLosProfile(), department_length_of_stay_profiles: [], waiting_queue: { ...DEFAULT_WAITING_QUEUE }, bed_turnaround_profile: { ...DEFAULT_TURNAROUND }, department_bed_turnaround_profiles: [] });
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
  const [completedRunId, setCompletedRunId] = useState<string | null>(null);
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
  const arrivalMixTotal = form.arrival_profile.planned_pct + form.arrival_profile.emergency_pct;
  const arrivalProfileValid = Number.isInteger(form.arrival_profile.planned_pct) && Number.isInteger(form.arrival_profile.emergency_pct)
    && form.arrival_profile.planned_pct >= 0 && form.arrival_profile.emergency_pct >= 0 && arrivalMixTotal === 100;
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
  const losProfiles = [form.length_of_stay_profile, ...form.department_length_of_stay_profiles];
  const lengthOfStayProfilesValid = losProfiles.every((profile) => Number.isFinite(profile.minimum_days) && Number.isFinite(profile.mode_days) && Number.isFinite(profile.maximum_days)
    && profile.minimum_days > 0 && profile.minimum_days <= profile.mode_days && profile.mode_days <= profile.maximum_days && profile.maximum_days <= 366
    && (profile.distribution !== "fixed" || profile.minimum_days === profile.mode_days && profile.mode_days === profile.maximum_days));

  async function loadHospitals(id: number) {
    setLoadingHospitals(true);
    setHospitals([]); setHospitalId(null); setSelectedDepartmentIds([]); setPreview(null); setHistory([]);
    setForm((current) => ({ ...current, department_length_of_stay_profiles: [] }));
    try {
      const entries = await api<Hospital[]>(`/api/v1/workspaces/${id}/hospitals`);
      setHospitals(entries);
      setHospitalId(entries[0]?.id ?? null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load hospitals.");
    } finally { setLoadingHospitals(false); }
  }

  useEffect(() => {
    let mounted = true;
    async function initialize() {
      try {
        const workspaceEntries = await api<Workspace[]>("/api/v1/workspaces");
        if (!mounted) return;
        setWorkspaces(workspaceEntries);
        if (workspaceEntries.length) {
          const targetWorkspaceId = workspaceEntries[0].id;
          setWorkspaceId(targetWorkspaceId);
          await loadHospitals(targetWorkspaceId);
        }
      } catch (cause) {
        if (!mounted) return;
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

  function updateLengthOfStayProfile(profile: LengthOfStayProfile) {
    updateForm("length_of_stay_profile", profile);
  }

  function updateDepartmentLengthOfStayProfile(departmentId: number, profile: LengthOfStayProfile | null) {
    const profiles = form.department_length_of_stay_profiles.filter((item) => item.department_id !== departmentId);
    if (profile) profiles.push({ ...profile, department_id: departmentId });
    updateForm("department_length_of_stay_profiles", profiles);
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
    if (!arrivalProfileValid) { setError(`Admission type percentages currently total ${arrivalMixTotal}%. Adjust them to exactly 100% before previewing.`); return; }
    if (!lengthOfStayProfilesValid) { setError("Correct the length-of-stay profile bounds before previewing."); return; }
    if (!Number.isFinite(form.waiting_queue.maximum_wait_hours) || form.waiting_queue.maximum_wait_hours < 0 || form.waiting_queue.maximum_wait_hours > 720) { setError("Maximum waiting duration must be between 0 and 720 hours."); return; }
    const turnaroundProfilesValid = [form.bed_turnaround_profile, ...form.department_bed_turnaround_profiles].every((profile) => profile.minimum_hours >= 0 && profile.minimum_hours <= profile.mode_hours && profile.mode_hours <= profile.maximum_hours && profile.maximum_hours <= 168 && (profile.distribution !== "fixed" || profile.minimum_hours === profile.mode_hours && profile.mode_hours === profile.maximum_hours));
    if (!turnaroundProfilesValid) { setError("Correct turnaround durations: values must be non-negative, ordered, and no more than 168 hours."); return; }
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
        department_demand_weights: form.department_demand_weights.filter((item) => effectiveDepartmentIds.includes(item.department_id)),
        department_length_of_stay_profiles: form.department_length_of_stay_profiles.filter((item) => effectiveDepartmentIds.includes(item.department_id)),
        department_bed_turnaround_profiles: form.department_bed_turnaround_profiles.filter((item) => effectiveDepartmentIds.includes(item.department_id)),
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
          arrival_profile: form.arrival_profile,
          department_demand_weights: form.department_demand_weights.filter((item) => effectiveDepartmentIds.includes(item.department_id)),
          length_of_stay_profile: form.length_of_stay_profile,
          department_length_of_stay_profiles: form.department_length_of_stay_profiles.filter((item) => effectiveDepartmentIds.includes(item.department_id)),
          waiting_queue: form.waiting_queue,
          bed_turnaround_profile: form.bed_turnaround_profile,
          department_bed_turnaround_profiles: form.department_bed_turnaround_profiles.filter((item) => effectiveDepartmentIds.includes(item.department_id)),
          department_ids: selectedDepartmentIds.length ? selectedDepartmentIds : null,
          idempotency_key: idempotencyKey,
          preview_token: preview.preview_token,
        }),
      });
      if (result.status === "failed") {
        setError(result.error_message ?? "Generation failed. No generated records were committed.");
        setPreview(null); setIdempotencyKey("");
      }
      else if (result.status === "completed") {
        setCompletedRunId(result.run_id);
        setSuccess(`Generation completed: ${result.patients_count} synthetic patients, ${result.admissions_count} assigned admissions, ${result.waiting_queue_count ?? 0} request outcomes, ${result.bed_turnaround_count ?? 0} turnaround events, ${result.transfers_count} transfers, and ${result.snapshots_count} occupancy snapshots.`);
      }
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
      </header>

      <div className="generator-content">
        <div className="generator-heading"><div><div className="generator-kicker"><FlaskConical size={14} /> SYNTHETIC OPERATIONS</div><h1>Synthetic Data Generator</h1><p>Build a reproducible, hospital-scoped operations dataset from your configured bed inventory.</p></div></div>

        {error && <div className="generator-alert generator-alert-error" role="alert"><CircleAlert size={18} /><span>{error}</span></div>}
        {success && <motion.section className="generator-completion" role="status" aria-labelledby="generation-success-title" initial={{ opacity: 0, y: 8, scale: 0.99 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.22 }}>
          <span className="generator-completion-icon"><Check size={23} /></span><div className="generator-completion-copy"><h2 id="generation-success-title">Dataset generated</h2><p>{success}</p></div>
          <div className="generator-completion-actions">{completedRunId && <Link className="generator-button generator-button-primary" href={`/datasets/${completedRunId}`}>View dataset and downloads</Link>}<Link className="generator-button generator-button-secondary" href="/datasets">Dataset library</Link></div>
        </motion.section>}
        {loading && <div className="generator-loading"><LoaderCircle className="generator-spin" size={22} /> Connecting to your workspace…</div>}
        {!loading && workspaces.length === 0 && <div className="generator-empty"><Building2Icon /><h2>No workspace found</h2><p>An administrator must configure a hospital with departments and operational beds before dataset generation is available.</p></div>}
        {!loading && workspaces.length > 0 && <>
          {!selectedHospital && !loadingHospitals && <div className="generator-empty"><Building2Icon /><h2>No active hospitals configured</h2><p>Generation requires an active hospital, at least one active department, and operational beds. Ask an administrator to configure the hospital inventory.</p></div>}
          <div className="generator-grid">
            <section className="generator-card" aria-labelledby="config-heading">
              <div className="generator-card-header"><span className="generator-section-icon"><FlaskConical size={18} /></span><div><h2 id="config-heading">Generation configuration</h2><p>Choose the scope and parameters for this deterministic run.</p></div></div>
              <form className="generator-form" onSubmit={makePreview}>
                {workspaces.length > 1 && <label>Workspace<select value={workspaceId ?? ""} disabled={generating} onChange={(event) => void changeWorkspace(Number(event.target.value))}>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select></label>}
                <label>Hospital<select required value={hospitalId ?? ""} disabled={loadingHospitals || generating || hospitals.length === 0} onChange={(event) => { setHospitalId(Number(event.target.value)); setSelectedDepartmentIds([]); setForm((current) => ({ ...current, department_length_of_stay_profiles: [] })); setPreview(null); setIdempotencyKey(""); }}>{hospitals.map((hospital) => <option key={hospital.id} value={hospital.id}>{hospital.name} · {hospital.code}</option>)}</select><small>Only active hospitals in the selected workspace are available.</small></label>
                <fieldset className="generator-fieldset"><legend>Generation period</legend><div className="generator-two-column"><label>Start date<input type="date" required disabled={generating} value={form.start_date} onChange={(event) => updateForm("start_date", event.target.value)} /></label><label>End date<input type="date" required disabled={generating} min={form.start_date} value={form.end_date} onChange={(event) => updateForm("end_date", event.target.value)} /></label></div></fieldset>
                <label>Number of synthetic admissions<input type="number" min={0} max={5000} required disabled={generating} value={form.target_admissions} onChange={(event) => updateForm("target_admissions", Number(event.target.value))} /><small>The selected scenario adjusts this volume; preview shows the projected count (maximum 5,000).</small></label>
                <fieldset className="generator-fieldset scenario-fieldset"><legend>Operational scenario</legend><p className="scenario-help">Presets adjust the fictional demand pattern and volume. They are simulation assumptions, not real hospital statistics. Select one before previewing.</p><div className="scenario-grid" role="radiogroup" aria-label="Operational scenario">{scenarios.map(({ id, name, description, Icon }) => <label key={id} className={`scenario-option ${form.scenario === id ? "is-selected" : ""}`}><input type="radio" name="scenario" value={id} checked={form.scenario === id} disabled={generating} onChange={() => updateForm("scenario", id)} /><span className="scenario-option-icon"><Icon size={17} /></span><span className="scenario-option-copy"><strong>{name}</strong><small>{description}</small></span><span className="scenario-radio-mark" aria-hidden="true" /></label>)}</div></fieldset>
                <details className="generator-advanced-settings">
                  <summary><span><strong>Advanced Settings</strong><small>Arrival patterns, patient profiles, bed operations, departments, and reproducibility.</small></span><span className="advanced-settings-indicator" aria-hidden="true">+</span></summary>
                  <div className="generator-advanced-body">
                    <div className="generator-two-column"><label className="generator-occupancy-label">Target occupancy <strong>{form.target_occupancy_pct}%</strong><input type="range" min={0} max={100} step={1} disabled={generating} value={form.target_occupancy_pct} onChange={(event) => updateForm("target_occupancy_pct", Number(event.target.value))} aria-label="Target occupancy percentage" /><small>A scheduling target for peak concurrent bed assignments; snapshots report calculated occupancy.</small></label><label>Random seed<input type="number" min={0} max={2147483647} required disabled={generating} value={form.seed} onChange={(event) => updateForm("seed", Number(event.target.value))} /><small>Reuse the same seed and configuration to reproduce records.</small></label></div>
                <details className="arrival-profile-details">
                  <summary><span><strong>Admission arrival profile</strong><small>Configure type mix and arrival timing patterns.</small></span></summary>
                  <div className="arrival-profile-body">
                    <fieldset className="generator-fieldset"><legend>Admission type mix</legend><p id="admission-type-guidance" className="arrival-guidance-copy">Planned admissions are scheduled or non-emergency; emergency admissions are unexpected. These percentages set the planned/emergency distribution in the generated dataset, and must add up to exactly 100%. Example: 70% planned + 30% emergency = 100%.</p><div className="generator-two-column">
                      <label>Planned admissions (%)<input type="number" min={0} max={100} step={1} value={form.arrival_profile.planned_pct} aria-invalid={!arrivalProfileValid} aria-describedby="admission-type-guidance admission-type-total" onChange={(event) => updateForm("arrival_profile", { ...form.arrival_profile, planned_pct: Number(event.target.value) })} /></label>
                      <label>Emergency admissions (%)<input type="number" min={0} max={100} step={1} value={form.arrival_profile.emergency_pct} aria-invalid={!arrivalProfileValid} aria-describedby="admission-type-guidance admission-type-total" onChange={(event) => updateForm("arrival_profile", { ...form.arrival_profile, emergency_pct: Number(event.target.value) })} /></label>
                    </div><output id="admission-type-total" className={`patient-profile-total ${arrivalProfileValid ? "is-valid" : "is-invalid"}`} aria-live="polite">{arrivalProfileValid ? `Admission type total: ${arrivalMixTotal}% ✓` : `Current total: ${arrivalMixTotal}%. Required total: 100%. Adjust the percentages to continue.`}</output></fieldset>
                    <div className="generator-two-column arrival-pattern-selects">
                      <label>Time-of-day pattern<select value={form.arrival_profile.time_of_day} onChange={(event) => updateForm("arrival_profile", { ...form.arrival_profile, time_of_day: event.target.value as ArrivalProfile["time_of_day"] })}><option value="uniform">Uniform across day</option><option value="daytime">Daytime weighted</option><option value="evening">Evening weighted</option><option value="overnight">Overnight weighted</option></select></label>
                      <label>Day-of-week pattern<select value={form.arrival_profile.day_of_week} onChange={(event) => updateForm("arrival_profile", { ...form.arrival_profile, day_of_week: event.target.value as ArrivalProfile["day_of_week"] })}><option value="uniform">Uniform across week</option><option value="weekdays">Weekday weighted</option><option value="weekends">Weekend weighted</option></select></label>
                    </div>
                    {activeDepartments.length > 0 && <fieldset className="generator-fieldset department-demand-fieldset"><legend>Optional department demand weights</legend><p id="department-demand-guidance" className="arrival-guidance-copy">Weights control each department’s relative share of synthetic patient demand: 1 is neutral, higher values mean relatively greater demand, and lower positive values mean relatively lower demand. They are relative weights, not percentages or exact patient counts. Without custom weights, scenario defaults or neutral weights apply. Example: Cardiology at 2 and Neurology at 1 gives Cardiology relatively greater demand.</p><div className="arrival-department-weights">{activeDepartments.filter((department) => effectiveDepartmentIds.includes(department.id)).map((department) => {
                      const currentWeight = form.department_demand_weights.find((entry) => entry.department_id === department.id)?.weight ?? 1;
                      return <label key={department.id}>{department.name}<input type="number" min={0.1} max={10} step={0.1} value={currentWeight} onChange={(event) => {
                        const weight = Number(event.target.value);
                        updateForm("department_demand_weights", [...form.department_demand_weights.filter((entry) => entry.department_id !== department.id), { department_id: department.id, weight }]);
                      }} /></label>;
                    })}</div><aside className="department-weight-tip" aria-label="Department weight tip">Not sure what to choose? Keep all weights at 1. You can customize them later.</aside></fieldset>}
                    <p className="arrival-profile-note">Patterns are configurable synthetic weights, not empirically calibrated hospital arrival rates. Bed placement uses an immediate-assignment baseline; no waiting queue is simulated.</p>
                  </div>
                </details>
                <details className="patient-profile-details">
                  <summary><span className="patient-profile-summary-copy"><strong>Patient Profile Configuration</strong><small>Configure fictional ages and gender shares for the generated patients.</small></span></summary>
                  <div className="patient-profile-body">
                    <div className="patient-profile-body-header"><p>Demographic settings affect fictional records only. Percentage allocations are rounded deterministically for the projected patient count.</p><button type="button" className="generator-button generator-button-secondary patient-profile-reset" disabled={generating} onClick={resetPatientProfile}>Reset to Defaults</button></div>
                    <div className="patient-profile-age-limits">
                      <label>Minimum age<input type="number" min={0} max={120} step={1} value={form.patient_profile.minimum_age} disabled={generating} aria-invalid={!ageLimitsValid} onChange={(event) => updatePatientProfile({ ...form.patient_profile, minimum_age: Number(event.target.value) })} /></label>
                      <label>Maximum age<input type="number" min={0} max={120} step={1} value={form.patient_profile.maximum_age} disabled={generating} aria-invalid={!ageLimitsValid} onChange={(event) => updatePatientProfile({ ...form.patient_profile, maximum_age: Number(event.target.value) })} /></label>
                      <small>Generated ages stay within these inclusive limits.</small>
                    </div>
                    <div className="patient-profile-distributions">
                      <fieldset className="patient-profile-group"><legend>Age distribution</legend><p>Use whole-number percentages. These defaults are a neutral synthetic mix, not population estimates.</p><div className="patient-age-card-grid">{AGE_PROFILE_FIELDS.map((field) => <article className="patient-profile-distribution-card" key={field.key}><div className="patient-profile-distribution-heading"><strong>{field.label}</strong><small>{field.range}</small></div><label className="patient-profile-percent-control" htmlFor={`age-share-${field.key}`}><input id={`age-share-${field.key}`} type="number" min={0} max={100} step={1} value={form.patient_profile.age_distribution[field.key]} disabled={generating} aria-invalid={ageTotal !== 100} aria-describedby="age-distribution-total" onChange={(event) => updatePatientProfile({ ...form.patient_profile, age_distribution: { ...form.patient_profile.age_distribution, [field.key]: Number(event.target.value) } })} /><span aria-hidden="true">%</span></label></article>)}</div><output id="age-distribution-total" className={`patient-profile-total ${ageTotal === 100 ? "is-valid" : "is-invalid"}`} aria-live="polite">Age total: {ageTotal}% {ageTotal === 100 ? "✓" : "· must equal 100%"}</output></fieldset>
                      <fieldset className="patient-profile-group"><legend>Gender distribution</legend><p>Gender shares use the same deterministic percentage allocation.</p><div className="patient-gender-card-grid">{GENDER_PROFILE_FIELDS.map((field) => <article className="patient-profile-distribution-card" key={field.key}><div className="patient-profile-distribution-heading"><strong>{field.label}</strong><small>Gender share</small></div><label className="patient-profile-percent-control" htmlFor={`gender-share-${field.key}`}><input id={`gender-share-${field.key}`} type="number" min={0} max={100} step={1} value={form.patient_profile.gender_distribution[field.key]} disabled={generating} aria-invalid={genderTotal !== 100} aria-describedby="gender-distribution-total" onChange={(event) => updatePatientProfile({ ...form.patient_profile, gender_distribution: { ...form.patient_profile.gender_distribution, [field.key]: Number(event.target.value) } })} /><span aria-hidden="true">%</span></label></article>)}</div><output id="gender-distribution-total" className={`patient-profile-total ${genderTotal === 100 ? "is-valid" : "is-invalid"}`} aria-live="polite">Gender total: {genderTotal}% {genderTotal === 100 ? "✓" : "· must equal 100%"}</output></fieldset>
                    </div>
                    {!ageLimitsValid && <p className="patient-profile-error" role="alert">Enter whole-number ages from 0 to 120, with maximum age on or above minimum age.</p>}
                    {selectedAgeGroupUnavailable && <p className="patient-profile-error" role="alert">An age group with a non-zero share does not overlap the configured age limits.</p>}
                  </div>
                </details>
                <details className="los-profile-details">
                  <summary><span><strong>Length of Stay Profiles</strong><small>Configure fixed or variable synthetic stays in days.</small></span></summary>
                  <div className="los-profile-body">
                    <div className="los-profile-header"><p>These are simulation assumptions, not clinical estimates. Stays that extend beyond the selected period remain ongoing in the dataset.</p><button type="button" className="generator-button generator-button-secondary" disabled={generating} onClick={() => { updateLengthOfStayProfile(copyDefaultLosProfile()); updateForm("department_length_of_stay_profiles", []); }}>Reset to Defaults</button></div>
                    <fieldset className="generator-fieldset"><legend>Global length-of-stay profile</legend><div className="los-profile-editor">
                      <label>Distribution<select value={form.length_of_stay_profile.distribution} disabled={generating} onChange={(event) => {
                        const distribution = event.target.value as LengthOfStayProfile["distribution"];
                        const mode = form.length_of_stay_profile.mode_days;
                        updateLengthOfStayProfile(distribution === "fixed" ? { distribution, minimum_days: mode, mode_days: mode, maximum_days: mode } : { ...form.length_of_stay_profile, distribution });
                      }}><option value="triangular">Variable (triangular)</option><option value="fixed">Fixed duration</option></select></label>
                      {(["minimum_days", "mode_days", "maximum_days"] as const).map((key) => <label key={key}>{key === "minimum_days" ? "Minimum stay (days)" : key === "mode_days" ? (form.length_of_stay_profile.distribution === "fixed" ? "Fixed stay (days)" : "Most likely stay (days)") : "Maximum stay (days)"}<input type="number" min={0.01} max={366} step="any" value={form.length_of_stay_profile[key]} disabled={generating || form.length_of_stay_profile.distribution === "fixed" && key !== "mode_days"} aria-invalid={!lengthOfStayProfilesValid} onChange={(event) => {
                        const value = Number(event.target.value);
                        const next = form.length_of_stay_profile.distribution === "fixed" ? { ...form.length_of_stay_profile, minimum_days: value, mode_days: value, maximum_days: value } : { ...form.length_of_stay_profile, [key]: value };
                        updateLengthOfStayProfile(next);
                      }} /></label>)}
                    </div><p className="los-profile-hint">Variable stays use a seeded triangular distribution. Minimum, most likely, and maximum values are bounded to this profile.</p></fieldset>
                    {activeDepartments.some((department) => effectiveDepartmentIds.includes(department.id)) && <fieldset className="generator-fieldset"><legend>Optional department-specific profiles</legend><p>Overrides apply only to selected departments. All others use the global profile.</p><div className="los-department-profiles">{activeDepartments.filter((department) => effectiveDepartmentIds.includes(department.id)).map((department) => {
                      const override = form.department_length_of_stay_profiles.find((item) => item.department_id === department.id);
                      const profile = override ?? form.length_of_stay_profile;
                      return <div className="los-department-profile" key={department.id}>
                        <label className="los-department-toggle"><input type="checkbox" checked={Boolean(override)} disabled={generating} onChange={(event) => updateDepartmentLengthOfStayProfile(department.id, event.target.checked ? { ...form.length_of_stay_profile } : null)} /><span>{department.name}</span></label>
                        {override && <div className="los-profile-editor los-profile-editor-compact">
                          <label>{department.name} distribution<select value={profile.distribution} disabled={generating} onChange={(event) => {
                            const distribution = event.target.value as LengthOfStayProfile["distribution"];
                            updateDepartmentLengthOfStayProfile(department.id, distribution === "fixed" ? { distribution, minimum_days: profile.mode_days, mode_days: profile.mode_days, maximum_days: profile.mode_days } : { distribution, minimum_days: profile.minimum_days, mode_days: profile.mode_days, maximum_days: profile.maximum_days });
                          }}><option value="triangular">Variable</option><option value="fixed">Fixed</option></select></label>
                          {(["minimum_days", "mode_days", "maximum_days"] as const).map((key) => <label key={key}>{key === "minimum_days" ? "Minimum days" : key === "mode_days" ? "Most likely / fixed days" : "Maximum days"}<input type="number" min={0.01} max={366} step="any" value={profile[key]} disabled={generating || profile.distribution === "fixed" && key !== "mode_days"} aria-invalid={!lengthOfStayProfilesValid} onChange={(event) => {
                            const value = Number(event.target.value);
                            const next = profile.distribution === "fixed" ? { ...profile, minimum_days: value, mode_days: value, maximum_days: value } : { ...profile, [key]: value };
                            updateDepartmentLengthOfStayProfile(department.id, next);
                          }} /></label>)}
                        </div>}
                      </div>;
                    })}</div></fieldset>}
                    {!lengthOfStayProfilesValid && <p className="patient-profile-error" role="alert">Set positive stay durations up to 366 days, with minimum ≤ most likely ≤ maximum. Fixed profiles require equal values.</p>}
                    <p className="arrival-profile-note">Requests may wait for an eligible operational bed. Maximum-wait outcomes are recorded explicitly; preview does not create records.</p>
                  </div>
                </details>
                <details className="los-profile-details">
                  <summary><span><strong>Waiting Queue & Bed Turnaround</strong><small>Configure queue priority, maximum wait, and bed cleaning time.</small></span></summary>
                  <div className="los-profile-body">
                    <fieldset className="generator-fieldset"><legend>Waiting queue</legend><div className="generator-two-column">
                      <label>Priority policy<select value={form.waiting_queue.priority_policy} disabled={generating} onChange={(event) => updateForm("waiting_queue", { ...form.waiting_queue, priority_policy: event.target.value as WaitingQueueConfig["priority_policy"] })}><option value="emergency_first">Emergency first</option><option value="planned_first">Planned first</option><option value="arrival_order">Arrival order</option></select><small>Requests within equal priority are ordered by request time, then stable request number.</small></label>
                      <label>Maximum wait (hours)<input type="number" min={0} max={720} step={1} value={form.waiting_queue.maximum_wait_hours} disabled={generating} onChange={(event) => updateForm("waiting_queue", { ...form.waiting_queue, maximum_wait_hours: Number(event.target.value) })} /><small>At expiry, an unassigned request is recorded as max wait exceeded.</small></label>
                    </div></fieldset>
                    <fieldset className="generator-fieldset"><legend>Global bed turnaround</legend><div className="los-profile-editor">
                      <label>Distribution<select value={form.bed_turnaround_profile.distribution} disabled={generating} onChange={(event) => { const distribution = event.target.value as BedTurnaroundProfile["distribution"]; const profile = form.bed_turnaround_profile; updateForm("bed_turnaround_profile", distribution === "fixed" ? { distribution, minimum_hours: profile.mode_hours, mode_hours: profile.mode_hours, maximum_hours: profile.mode_hours } : { ...profile, distribution }); }}><option value="fixed">Fixed duration</option><option value="triangular">Variable (triangular)</option></select></label>
                      {(["minimum_hours", "mode_hours", "maximum_hours"] as const).map((key) => <label key={key}>{key === "minimum_hours" ? "Minimum hours" : key === "mode_hours" ? "Most likely / fixed hours" : "Maximum hours"}<input type="number" min={0} max={168} step={0.25} value={form.bed_turnaround_profile[key]} disabled={generating || form.bed_turnaround_profile.distribution === "fixed" && key !== "mode_hours"} onChange={(event) => { const value = Number(event.target.value); const profile = form.bed_turnaround_profile; updateForm("bed_turnaround_profile", profile.distribution === "fixed" ? { ...profile, minimum_hours: value, mode_hours: value, maximum_hours: value } : { ...profile, [key]: value }); }} /></label>)}
                    </div><p>Default is a fixed 0.5-hour simulator assumption, not a measured hospital standard. Cleaning time begins when a bed assignment ends and does not extend patient length of stay.</p></fieldset>
                    {activeDepartments.filter((department) => effectiveDepartmentIds.includes(department.id)).length > 0 && <fieldset className="generator-fieldset"><legend>Department turnaround overrides</legend><p>Optional fixed duration overrides; departments without an override use the global profile.</p><div className="los-department-profiles">{activeDepartments.filter((department) => effectiveDepartmentIds.includes(department.id)).map((department) => { const override = form.department_bed_turnaround_profiles.find((item) => item.department_id === department.id); return <div className="los-department-profile" key={department.id}><label className="los-department-toggle"><input type="checkbox" checked={Boolean(override)} disabled={generating} onChange={(event) => updateForm("department_bed_turnaround_profiles", event.target.checked ? [...form.department_bed_turnaround_profiles, { department_id: department.id, ...DEFAULT_TURNAROUND }] : form.department_bed_turnaround_profiles.filter((item) => item.department_id !== department.id))} /><span>{department.name}</span></label>{override && <label>Fixed turnaround (hours)<input type="number" min={0} max={168} step={0.25} value={override.mode_hours} disabled={generating} onChange={(event) => updateForm("department_bed_turnaround_profiles", form.department_bed_turnaround_profiles.map((item) => item.department_id === department.id ? { ...item, minimum_hours: Number(event.target.value), mode_hours: Number(event.target.value), maximum_hours: Number(event.target.value) } : item))} /></label>}</div>; })}</div></fieldset>}
                  </div>
                </details>
                {hasDepartments && <fieldset className="generator-fieldset"><legend>Departments <span>(all active departments by default)</span></legend><div className="generator-department-list">{activeDepartments.map((department) => {
                  const operationalBeds = department.beds.filter((bed) => bed.status === "operational").length;
                  const checked = selectedDepartmentIds.length === 0 || selectedDepartmentIds.includes(department.id);
                  return <label key={department.id} className="generator-department-option"><input type="checkbox" checked={checked} disabled={generating} onChange={() => toggleDepartment(department.id)} /><span><strong>{department.name}</strong><small>{department.code} · {operationalBeds} operational beds</small></span></label>;
                })}</div></fieldset>}
                  </div>
                </details>
                <div className="generator-privacy"><ShieldCheck size={17} /><span>Records are fictional. This generator does not accept or store real patient information.</span></div>
                <div className="generator-form-actions"><button className="generator-button generator-button-primary" disabled={!selectedHospital || previewing || generating || loadingHospitals}>{previewing ? <LoaderCircle className="generator-spin" size={16} /> : <RefreshCw size={16} />} {previewing ? "Preparing preview…" : "Preview generation"}</button></div>
              </form>
            </section>

            <aside className="generator-side-column">
              <section className="generator-card generator-summary-card" aria-labelledby="preview-heading">
                <div className="generator-card-header"><span className="generator-section-icon"><BedDouble size={18} /></span><div><h2 id="preview-heading">Generation preview</h2><p>Server-calculated scope and bed availability.</p></div></div>
                {!preview ? <div className="generator-summary-empty"><FlaskConical size={24} /><p>Configure a run and preview it to see the selected hospital, bed inventory, and expected record counts.</p></div> : <>
                  <div className="generator-summary-facts"><div><span>Hospital</span><strong>{preview.hospital_name}</strong></div><div><span>Operational scenario</span><strong>{scenarios.find((scenario) => scenario.id === preview.scenario)?.name ?? "Normal Operations"}</strong></div><div><span>Period</span><strong>{preview.start_date} – {preview.end_date}</strong></div><div><span>Base admissions</span><strong>{preview.target_admissions.toLocaleString()}</strong></div><div><span>Projected requests</span><strong>{preview.projected_admissions.toLocaleString()}</strong></div><div><span>Target occupancy</span><strong>{preview.target_occupancy_pct}%</strong></div><div><span>Random seed</span><strong className="generator-mono">{preview.seed}</strong></div><div><span>Projected discharges</span><strong>{preview.projected_discharges.toLocaleString()}</strong></div><div><span>Ongoing at period end</span><strong>{preview.projected_ongoing_admissions.toLocaleString()}</strong></div></div>
                  <section className="patient-profile-preview" aria-label="Preview admission arrival profile"><h3>Admission arrivals</h3><p>Base mix: planned {preview.arrival_profile.planned_pct}% · emergency {preview.arrival_profile.emergency_pct}%</p><strong>Effective scenario mix</strong><div className="patient-preview-chips"><span>Planned: {preview.effective_admission_mix.planned}%</span><span>Emergency: {preview.effective_admission_mix.emergency}%</span></div><strong>Timing profile</strong><div className="patient-preview-chips"><span>{preview.arrival_profile.time_of_day}</span><span>{preview.arrival_profile.day_of_week}</span></div></section><section className="patient-profile-preview" aria-label="Preview patient profile"><h3>Patient profile</h3><p>Projected patients: {preview.projected_admissions.toLocaleString()} · Age limits: {preview.patient_profile.minimum_age}–{preview.patient_profile.maximum_age} years</p><strong>Age distribution</strong><div className="patient-preview-chips">{AGE_PROFILE_FIELDS.map((field) => <span key={field.key}>{field.label}: {preview.patient_profile.age_distribution[field.key]}%</span>)}</div><strong>Gender distribution</strong><div className="patient-preview-chips">{GENDER_PROFILE_FIELDS.map((field) => <span key={field.key}>{field.label}: {preview.patient_profile.gender_distribution[field.key]}%</span>)}</div></section>
                  <section className="patient-profile-preview" aria-label="Preview length-of-stay profiles"><h3>Length of stay</h3><p>Days · {preview.length_of_stay_profile.distribution === "fixed" ? `fixed at ${preview.length_of_stay_profile.mode_days}` : `triangular ${preview.length_of_stay_profile.minimum_days} / ${preview.length_of_stay_profile.mode_days} / ${preview.length_of_stay_profile.maximum_days}`}</p><strong>Department overrides</strong><div className="patient-preview-chips">{preview.department_length_of_stay_profiles.length ? preview.department_length_of_stay_profiles.map((profile) => <span key={profile.department_id}>{preview.departments.find((department) => department.department_id === profile.department_id)?.department_name ?? `Department ${profile.department_id}`}: {profile.distribution === "fixed" ? `${profile.mode_days} d fixed` : `${profile.minimum_days}–${profile.maximum_days} d variable`}</span>) : <span>Global profile applies to all included departments</span>}</div><strong>Observation window</strong><div className="patient-preview-chips"><span>{preview.projected_discharges} projected discharges</span><span>{preview.projected_ongoing_admissions} ongoing at end</span></div></section>
                  <section className="patient-profile-preview" aria-label="Preview patient profile"><h3>Patient profile</h3><p>Projected patients: {preview.projected_admissions.toLocaleString()} · Age limits: {preview.patient_profile.minimum_age}–{preview.patient_profile.maximum_age} years</p><strong>Age distribution</strong><div className="patient-preview-chips">{AGE_PROFILE_FIELDS.map((field) => <span key={field.key}>{field.label} ({field.range}): {preview.patient_profile.age_distribution[field.key]}%</span>)}</div><strong>Gender distribution</strong><div className="patient-preview-chips">{GENDER_PROFILE_FIELDS.map((field) => <span key={field.key}>{field.label}: {preview.patient_profile.gender_distribution[field.key]}%</span>)}</div></section>
                  <section className="patient-profile-preview" aria-label="Preview waiting and turnaround"><h3>Waiting & bed turnaround</h3><p>{preview.projected_assigned_admissions} assigned · {preview.projected_waiting_patients} waiting at window end · {preview.projected_max_wait_exceeded} exceeded maximum wait</p><div className="patient-preview-chips"><span>Unresolved requests: {preview.projected_unresolved_requests}</span><span>Average wait: {preview.projected_average_wait_minutes.toFixed(1)} min</span><span>Maximum wait: {preview.projected_maximum_wait_minutes.toFixed(1)} min</span><span>Turnaround events: {preview.projected_turnaround_events}</span><span>Cleaning at window end: {preview.projected_beds_cleaning_at_window_end}</span></div></section>
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
        <div className="generator-dialog-summary"><span>{scenarios.find((scenario) => scenario.id === preview?.scenario)?.name ?? "Normal Operations"}</span><span>{preview?.projected_admissions.toLocaleString()} projected requests</span><span>{preview?.projected_assigned_admissions.toLocaleString()} projected assigned admissions</span><span>{preview?.departments.length} departments</span><span>Seed {preview?.seed}</span></div>
        <div className="generator-form-actions"><button type="button" className="generator-button generator-button-secondary" onClick={() => setConfirmOpen(false)}>Cancel</button><button type="button" className="generator-button generator-button-primary" disabled={generating} onClick={() => void runGeneration()}>{generating ? <LoaderCircle className="generator-spin" size={16} /> : <Check size={16} />} Confirm generation</button></div>
      </dialog>
      {generating && <div className="generator-progress" role="status"><LoaderCircle className="generator-spin" size={16} /> Creating synthetic records and validating event sequences…</div>}
    </main>
  );
}

function Building2Icon() {
  return <span className="generator-empty-icon"><BedDouble size={23} /></span>;
}
