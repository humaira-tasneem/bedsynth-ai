"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ArrowLeft,
  BedDouble,
  Building2,
  Check,
  ChevronDown,
  CircleAlert,
  CirclePlus,
  Edit3,
  Layers3,
  LoaderCircle,
  Network,
  Plus,
  RotateCcw,
  X,
} from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

type Workspace = { id: number; name: string };
type HospitalNetwork = { id: number; workspace_id: number; name: string; is_archived: boolean };
type Bed = { id: number; hospital_id: number; department_id: number; code: string; category: string; status: BedStatus };
type BedStatus = "planned" | "operational" | "out_of_service" | "retired";
type Department = { id: number; hospital_id: number; code: string; name: string; bed_capacity: number | null; is_archived: boolean; beds: Bed[] };
type Hospital = { id: number; workspace_id: number; network_id: number | null; name: string; code: string; is_archived: boolean; departments: Department[] };
type BedGenerationPreview = { hospital_id: number; total_to_create: number; preview_token: string; departments: { department_id: number; department_name: string; department_code: string; capacity: number | null; existing_beds: number; beds_to_create: number; first_bed_code: string | null; last_bed_code: string | null; note: string | null }[] };
type DialogState =
  | { type: "hospital"; item?: Hospital }
  | { type: "department"; hospital: Hospital; item?: Department }
  | { type: "bed"; hospital: Hospital; department: Department; item?: Bed }
  | { type: "generation"; hospital: Hospital; departmentIds: number[] | null; preview: BedGenerationPreview }
  | { type: "network" }
  | null;

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
    cache: "no-store",
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((issue: { msg?: string; loc?: (string | number)[] }) => `${issue.loc?.slice(-1)[0] ?? "Input"}: ${issue.msg ?? "Invalid value"}`).join(" ")
      : typeof detail === "string" ? detail : `Request failed (${response.status}).`;
    throw new Error(message);
  }
  return body as T;
}

function ModalFrame({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  const modalRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    modalRef.current?.querySelector<HTMLElement>("input:not([disabled]), select:not([disabled]), button:not([disabled])")?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab" && modalRef.current) {
        const focusable = Array.from(modalRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]"));
        if (focusable.length === 0) return;
        const first = focusable[0]; const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => { window.removeEventListener("keydown", onKeyDown); previousFocus?.focus(); };
  }, [onClose]);

  return (
    <div className="studio-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section ref={modalRef} className="studio-modal" role="dialog" aria-modal="true" aria-labelledby="studio-modal-title">
        <div className="studio-modal-heading"><div><span className="studio-eyebrow">HOSPITAL STUDIO</span><h2 id="studio-modal-title">{title}</h2></div><button className="studio-icon-button" type="button" onClick={onClose} aria-label="Close dialog"><X size={19} /></button></div>
        {children}
      </section>
    </div>
  );
}

function FormError({ message }: { message: string }) {
  return message ? <div className="studio-form-error" role="alert"><CircleAlert size={16} /><span>{message}</span></div> : null;
}

function HospitalForm({ item, networks, onClose, onSave }: { item?: Hospital; networks: HospitalNetwork[]; onClose: () => void; onSave: (data: Record<string, unknown>) => Promise<void> }) {
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setSaving(true);
    const form = new FormData(event.currentTarget);
    try {
      await onSave({ name: String(form.get("name") ?? ""), code: String(form.get("code") ?? ""), network_id: form.get("network_id") ? Number(form.get("network_id")) : null });
      onClose();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save the hospital."); }
    finally { setSaving(false); }
  }
  return <form className="studio-form" onSubmit={submit}>
    <p className="studio-form-intro">Use fictional facility details. Do not enter real patient or hospital information.</p>
    <label>Hospital name<input autoFocus name="name" required minLength={1} maxLength={160} defaultValue={item?.name ?? ""} placeholder="e.g. Harborview Simulation Hospital" /></label>
    <label>Hospital code<input name="code" required pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,39}" maxLength={40} defaultValue={item?.code ?? ""} placeholder="e.g. HARBOR-01" aria-describedby="hospital-code-help" /><small id="hospital-code-help">Unique within this workspace. Letters, numbers, hyphens, and underscores.</small></label>
    <label>Hospital network <span className="field-optional">OPTIONAL</span><select name="network_id" defaultValue={item?.network_id ?? ""}><option value="">Independent hospital</option>{networks.filter((network) => !network.is_archived).map((network) => <option key={network.id} value={network.id}>{network.name}</option>)}</select><small>A hospital can belong to one active network, or remain independent.</small></label>
    <FormError message={error} />
    <div className="studio-form-actions"><button type="button" className="studio-button studio-button-secondary" onClick={onClose}>Cancel</button><button disabled={saving} className="studio-button studio-button-primary">{saving && <LoaderCircle className="spin" size={16} />}{item ? "Save hospital" : "Create hospital"}</button></div>
  </form>;
}

function NetworkForm({ onClose, onSave }: { onClose: () => void; onSave: (name: string) => Promise<void> }) {
  const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setSaving(true); setError(""); const data = new FormData(event.currentTarget); try { await onSave(String(data.get("name") ?? "")); onClose(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not create the network."); } finally { setSaving(false); } }
  return <form className="studio-form" onSubmit={submit}><p className="studio-form-intro">Create a workspace-scoped grouping. Hospitals remain individually owned and managed.</p><label>Network name<input autoFocus name="name" required minLength={1} maxLength={120} placeholder="e.g. North Coast Network" /></label><FormError message={error} /><div className="studio-form-actions"><button type="button" className="studio-button studio-button-secondary" onClick={onClose}>Cancel</button><button disabled={saving} className="studio-button studio-button-primary">{saving && <LoaderCircle className="spin" size={16} />}Create network</button></div></form>;
}

function DepartmentForm({ item, onClose, onSave }: { item?: Department; onClose: () => void; onSave: (data: Record<string, unknown>) => Promise<void> }) {
  const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setSaving(true); setError(""); const data = new FormData(event.currentTarget); try { await onSave({ code: String(data.get("code") ?? ""), name: String(data.get("name") ?? ""), bed_capacity: Number(data.get("bed_capacity")), ...(item ? { is_archived: data.get("is_archived") === "on" } : {}) }); onClose(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save the department."); } finally { setSaving(false); } }
  return <form className="studio-form" onSubmit={submit}><p className="studio-form-intro">Department identifiers are unique within their hospital. Capacity is the maximum non-retired bed inventory.</p><label>Department name<input autoFocus name="name" required minLength={1} maxLength={120} defaultValue={item?.name ?? ""} placeholder="e.g. General Medicine" /></label><label>Department code<input name="code" required pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,39}" maxLength={40} defaultValue={item?.code ?? ""} placeholder="e.g. MED-01" /></label><label>Bed capacity<input type="number" name="bed_capacity" required min={Math.max(1, item?.beds.filter((bed) => bed.status !== "retired").length ?? 1)} max={10000} defaultValue={item?.bed_capacity ?? ""} /><small>Cannot be set below the number of beds currently in inventory.</small></label>{item && <label className="studio-checkbox"><input type="checkbox" name="is_archived" defaultChecked={item.is_archived} /> Archive this department</label>}<FormError message={error} /><div className="studio-form-actions"><button type="button" className="studio-button studio-button-secondary" onClick={onClose}>Cancel</button><button disabled={saving} className="studio-button studio-button-primary">{saving && <LoaderCircle className="spin" size={16} />}{item ? "Save department" : "Add department"}</button></div></form>;
}

function BedForm({ item, department, departments, onClose, onSave }: { item?: Bed; department: Department; departments: Department[]; onClose: () => void; onSave: (data: Record<string, unknown>) => Promise<void> }) {
  const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setSaving(true); setError(""); const data = new FormData(event.currentTarget); try { await onSave({ code: String(data.get("code") ?? ""), category: String(data.get("category") ?? ""), status: String(data.get("status") ?? "operational"), ...(item ? { department_id: Number(data.get("department_id")) } : {}) }); onClose(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save the bed."); } finally { setSaving(false); } }
  return <form className="studio-form" onSubmit={submit}><p className="studio-form-intro">Bed codes are unique across their hospital. Retired beds no longer use department inventory capacity.</p><label>Bed identifier<input autoFocus name="code" required pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,39}" maxLength={40} defaultValue={item?.code ?? ""} placeholder="e.g. B-101" /></label><label>Category<input name="category" required minLength={1} maxLength={60} defaultValue={item?.category ?? "general"} /></label>{item ? <><label>Department<select name="department_id" defaultValue={department.id}>{departments.filter((entry) => !entry.is_archived).map((entry) => <option key={entry.id} value={entry.id}>{entry.name} · {entry.code}</option>)}</select></label><label>Status<select name="status" defaultValue={item.status}><option value="planned">Planned</option><option value="operational">Operational</option><option value="out_of_service">Out of service</option><option value="retired">Retired</option></select></label></> : <label>Status<select name="status" defaultValue="operational"><option value="operational">Operational</option><option value="planned">Planned</option><option value="out_of_service">Out of service</option></select></label>}<FormError message={error} /><div className="studio-form-actions"><button type="button" className="studio-button studio-button-secondary" onClick={onClose}>Cancel</button><button disabled={saving} className="studio-button studio-button-primary">{saving && <LoaderCircle className="spin" size={16} />}{item ? "Save bed" : "Add bed"}</button></div></form>;
}

export default function HospitalStudioPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [networks, setNetworks] = useState<HospitalNetwork[]>([]);
  const [hospitals, setHospitals] = useState<Hospital[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [success, setSuccess] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [working, setWorking] = useState(false);
  const closeDialog = useCallback(() => setDialog(null), []);

  const loadWorkspaceData = useCallback(async (id: number) => {
    setLoadError("");
    const [networkData, hospitalData] = await Promise.all([
      api<HospitalNetwork[]>(`/workspaces/${id}/networks?include_archived=true`),
      api<Hospital[]>(`/workspaces/${id}/hospitals?include_archived=true`),
    ]);
    setNetworks(networkData); setHospitals(hospitalData);
    setSelectedId((current) => current && hospitalData.some((hospital) => hospital.id === current) ? current : hospitalData.find((hospital) => !hospital.is_archived)?.id ?? hospitalData[0]?.id ?? null);
  }, []);

  useEffect(() => {
    let mounted = true;
    async function initialize() {
      try {
        let currentWorkspaces = await api<Workspace[]>("/workspaces");
        if (currentWorkspaces.length === 0) {
          await api<Workspace>("/workspaces", { method: "POST", body: JSON.stringify({ name: "My workspace" }) });
          currentWorkspaces = await api<Workspace[]>("/workspaces");
        }
        if (!mounted) return;
        setWorkspaces(currentWorkspaces);
        const chosen = currentWorkspaces[0];
        setWorkspaceId(chosen.id);
        await loadWorkspaceData(chosen.id);
      } catch (cause) {
        if (mounted) setLoadError(cause instanceof Error ? cause.message : "Could not connect to Hospital Studio.");
      } finally { if (mounted) setLoading(false); }
    }
    void initialize();
    return () => { mounted = false; };
  }, [loadWorkspaceData]);

  const selectedHospital = useMemo(() => hospitals.find((hospital) => hospital.id === selectedId) ?? null, [hospitals, selectedId]);
  const visibleHospitals = useMemo(() => hospitals.filter((hospital) => showArchived || !hospital.is_archived), [hospitals, showArchived]);
  const selectedNetwork = (id: number | null) => networks.find((network) => network.id === id)?.name ?? "Independent hospital";

  async function refresh(message?: string) {
    if (!workspaceId) return;
    setWorking(true); setLoadError("");
    try { await loadWorkspaceData(workspaceId); if (message) setSuccess(message); }
    catch (cause) { setLoadError(cause instanceof Error ? cause.message : "The update was saved, but the latest data could not be loaded."); }
    finally { setWorking(false); window.setTimeout(() => setSuccess(""), 4500); }
  }

  async function changeWorkspace(value: number) {
    setWorkspaceId(value); setSelectedId(null); setLoading(true);
    try { await loadWorkspaceData(value); } catch (cause) { setLoadError(cause instanceof Error ? cause.message : "Could not load this workspace."); }
    finally { setLoading(false); }
  }

  async function saveHospital(data: Record<string, unknown>, item?: Hospital) {
    if (!workspaceId) throw new Error("A workspace is required.");
    const path = item ? `/workspaces/${workspaceId}/hospitals/${item.id}` : `/workspaces/${workspaceId}/hospitals`;
    const saved = await api<Hospital>(path, { method: item ? "PATCH" : "POST", body: JSON.stringify(data) });
    setSelectedId(saved.id); await refresh(item ? "Hospital details saved." : "Hospital created.");
  }

  async function saveNetwork(name: string) {
    if (!workspaceId) throw new Error("A workspace is required.");
    await api<HospitalNetwork>(`/workspaces/${workspaceId}/networks`, { method: "POST", body: JSON.stringify({ name }) });
    await refresh("Network created.");
  }

  async function saveDepartment(hospital: Hospital, data: Record<string, unknown>, item?: Department) {
    const path = item ? `/hospitals/${hospital.id}/departments/${item.id}` : `/hospitals/${hospital.id}/departments`;
    await api<Department>(path, { method: item ? "PATCH" : "POST", body: JSON.stringify(data) });
    await refresh(item ? "Department details saved." : "Department added.");
  }

  async function saveBed(hospital: Hospital, department: Department, data: Record<string, unknown>, item?: Bed) {
    const path = item ? `/hospitals/${hospital.id}/beds/${item.id}` : `/hospitals/${hospital.id}/departments/${department.id}/beds`;
    await api<Bed>(path, { method: item ? "PATCH" : "POST", body: JSON.stringify(data) });
    await refresh(item ? "Bed details saved." : "Bed added.");
  }

  async function previewBedGeneration(hospital: Hospital, department?: Department) {
    setWorking(true); setLoadError(""); setSuccess("");
    const departmentIds = department ? [department.id] : null;
    try {
      const preview = await api<BedGenerationPreview>(`/hospitals/${hospital.id}/beds/generation-preview`, {
        method: "POST", body: JSON.stringify(departmentIds ? { department_ids: departmentIds } : {}),
      });
      setDialog({ type: "generation", hospital, departmentIds, preview });
    } catch (cause) {
      setLoadError(cause instanceof Error ? cause.message : "Could not preview bed generation.");
    } finally { setWorking(false); }
  }

  async function confirmBedGeneration() {
    if (dialog?.type !== "generation") return;
    const { hospital, departmentIds, preview } = dialog;
    setWorking(true); setLoadError("");
    try {
      const result = await api<{ beds_created: number }>(`/hospitals/${hospital.id}/beds/generate`, {
        method: "POST",
        body: JSON.stringify({ ...(departmentIds ? { department_ids: departmentIds } : {}), preview_token: preview.preview_token, confirmed: true }),
      });
      setDialog(null);
      await refresh(`${result.beds_created} ${result.beds_created === 1 ? "bed" : "beds"} created.`);
    } catch (cause) {
      setLoadError(cause instanceof Error ? cause.message : "Could not generate beds.");
      if (cause instanceof Error && cause.message.includes("preview")) setDialog(null);
    } finally { setWorking(false); }
  }

  async function toggleArchive(hospital: Hospital) {
    const verb = hospital.is_archived ? "restore" : "archive";
    if (!window.confirm(`${hospital.is_archived ? "Restore" : "Archive"} ${hospital.name}? This keeps its records in the workspace.`)) return;
    try {
      await api<Hospital>(`/workspaces/${hospital.workspace_id}/hospitals/${hospital.id}`, { method: "PATCH", body: JSON.stringify({ is_archived: !hospital.is_archived }) });
      await refresh(hospital.is_archived ? "Hospital restored." : "Hospital archived; its records were retained.");
    } catch (cause) { setLoadError(cause instanceof Error ? cause.message : `Could not ${verb} the hospital.`); }
  }

  return (
    <main className="studio-page" id="main-content">
      <div className="studio-topline"><a href="/" className="studio-back"><ArrowLeft size={16} /> Overview</a><span className="studio-topline-label">CONFIGURATION · HOSPITAL STUDIO</span></div>
      <div className="studio-heading"><div><div className="page-kicker"><span className="kicker-line" /> FACILITY CONFIGURATION</div><h1>Hospital Studio</h1><p>Organize hospitals, departments, and bed inventory in your workspace.</p></div><div className="studio-workspace-select"><label htmlFor="workspace-select">WORKSPACE</label><select id="workspace-select" value={workspaceId ?? ""} onChange={(event) => void changeWorkspace(Number(event.target.value))} disabled={workspaces.length < 2}>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select><ChevronDown className="select-chevron" size={15} aria-hidden="true" /></div></div>
      {success && <div className="studio-success" role="status"><Check size={17} />{success}</div>}
      {loadError && <div className="studio-load-error" role="alert"><CircleAlert size={17} /><span>{loadError}</span><button onClick={() => workspaceId && void refresh()} className="studio-retry">Retry</button></div>}

      <div className="studio-layout">
        <section className="hospital-list-panel" aria-labelledby="hospital-list-title">
          <div className="studio-panel-heading"><div><h2 id="hospital-list-title">Hospitals</h2><p>{visibleHospitals.length} {visibleHospitals.length === 1 ? "facility" : "facilities"} in this workspace</p></div><button className="studio-square-add" onClick={() => setDialog({ type: "hospital" })} aria-label="Create hospital" title="Create hospital"><Plus size={18} /></button></div>
          <div className="hospital-list-toolbar"><label className="studio-archived-filter"><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} /> Show archived</label><button onClick={() => setDialog({ type: "network" })} className="studio-text-action"><Network size={14} /> New network</button></div>
          {loading ? <div className="studio-state"><LoaderCircle className="spin" size={22} /><span>Loading workspace facilities…</span></div> : visibleHospitals.length === 0 ? <div className="studio-empty"><span className="empty-icon"><Building2 size={21} /></span><h3>No hospitals yet</h3><p>Create a fictional hospital to start configuring its departments and bed inventory.</p><button className="studio-button studio-button-primary" onClick={() => setDialog({ type: "hospital" })}><Plus size={16} /> Create first hospital</button></div> : <div className="hospital-card-list">{visibleHospitals.map((hospital) => {
            const bedCount = hospital.departments.flatMap((department) => department.beds).filter((bed) => bed.status !== "retired").length;
            return <button key={hospital.id} className={`hospital-card ${selectedId === hospital.id ? "hospital-card-selected" : ""} ${hospital.is_archived ? "hospital-card-archived" : ""}`} onClick={() => setSelectedId(hospital.id)} aria-pressed={selectedId === hospital.id}>
              <span className="hospital-card-icon"><Building2 size={18} /></span><span className="hospital-card-main"><span className="hospital-card-title">{hospital.name}</span><span className="hospital-card-code">{hospital.code} <span>·</span> {selectedNetwork(hospital.network_id)}</span><span className="hospital-card-meta"><span>{hospital.departments.filter((department) => !department.is_archived).length} departments</span><span>{bedCount} beds</span></span></span><span className={`hospital-state-tag ${hospital.is_archived ? "tag-archived" : "tag-active"}`}>{hospital.is_archived ? "Archived" : "Active"}</span>
            </button>;
          })}</div>}
        </section>

        <section className="hospital-detail-panel" aria-label="Selected hospital details">
          {loading ? <div className="studio-state studio-detail-loading"><LoaderCircle className="spin" size={22} /><span>Loading hospital details…</span></div> : !selectedHospital ? <div className="studio-detail-empty"><Building2 size={28} /><h2>Select a hospital</h2><p>Choose a hospital from the list, or create one to configure departments and beds.</p></div> : <>
            <div className="detail-header"><div className="detail-heading-left"><span className="detail-hospital-icon"><Building2 size={21} /></span><div><div className="detail-name-row"><h2>{selectedHospital.name}</h2><span className={`hospital-state-tag ${selectedHospital.is_archived ? "tag-archived" : "tag-active"}`}>{selectedHospital.is_archived ? "Archived" : "Active"}</span></div><p>{selectedHospital.code} <span>·</span> {selectedNetwork(selectedHospital.network_id)}</p></div></div><div className="detail-actions"><button disabled={selectedHospital.is_archived} className="studio-button studio-button-secondary studio-small-button" onClick={() => void previewBedGeneration(selectedHospital)}><BedDouble size={14} /> Generate beds</button><button disabled={selectedHospital.is_archived} className="studio-button studio-button-secondary studio-small-button" onClick={() => setDialog({ type: "hospital", item: selectedHospital })}><Edit3 size={14} /> Edit</button><button className="studio-icon-button" onClick={() => void toggleArchive(selectedHospital)} aria-label={selectedHospital.is_archived ? "Restore hospital" : "Archive hospital"} title={selectedHospital.is_archived ? "Restore hospital" : "Archive hospital"}>{selectedHospital.is_archived ? <RotateCcw size={16} /> : <Archive size={16} />}</button></div></div>
            {selectedHospital.is_archived && <div className="archived-notice"><Archive size={15} /> This hospital is archived. Configuration is read-only until it is restored.</div>}
            <div className="detail-stat-row"><div><span className="detail-stat-icon"><Layers3 size={16} /></span><span><strong>{selectedHospital.departments.filter((department) => !department.is_archived).length}</strong><small>Departments</small></span></div><div><span className="detail-stat-icon"><BedDouble size={16} /></span><span><strong>{selectedHospital.departments.flatMap((department) => department.beds).filter((bed) => bed.status !== "retired").length}</strong><small>Non-retired beds</small></span></div><button className="studio-button studio-button-primary studio-small-button" onClick={() => setDialog({ type: "department", hospital: selectedHospital })} disabled={selectedHospital.is_archived}><Plus size={15} /> Add department</button></div>
            <div className="department-list-heading"><div><h3>Departments & beds</h3><p>Each bed is assigned to one department in this hospital.</p></div></div>
            {selectedHospital.departments.length === 0 ? <div className="department-empty"><Layers3 size={21} /><strong>No departments configured</strong><span>Add a department and its bed capacity to begin.</span></div> : <div className="department-list">{selectedHospital.departments.map((department) => {
              const activeBeds = department.beds.filter((bed) => bed.status !== "retired");
              return <article key={department.id} className={`department-card ${department.is_archived ? "department-card-archived" : ""}`}>
                <div className="department-card-heading"><span className="department-icon"><Layers3 size={17} /></span><div className="department-title"><strong>{department.name}</strong><small>{department.code}{department.is_archived ? " · Archived" : ""}</small></div><span className="capacity-chip">{activeBeds.length} / {department.bed_capacity ?? "—"} beds</span><button disabled={selectedHospital.is_archived} className="studio-icon-button" onClick={() => setDialog({ type: "department", hospital: selectedHospital, item: department })} aria-label={`Edit ${department.name}`} title="Edit department"><Edit3 size={15} /></button></div>
                <div className="bed-list-heading"><span>BED INVENTORY</span><span className="bed-actions"><button className="studio-text-action" disabled={selectedHospital.is_archived || department.is_archived || department.bed_capacity === null || activeBeds.length >= department.bed_capacity} onClick={() => void previewBedGeneration(selectedHospital, department)}><BedDouble size={13} /> Generate missing</button><button className="studio-text-action" disabled={selectedHospital.is_archived || department.is_archived || (department.bed_capacity !== null && activeBeds.length >= department.bed_capacity)} onClick={() => setDialog({ type: "bed", hospital: selectedHospital, department })}><Plus size={14} /> Add bed</button></span></div>
                {department.beds.length === 0 ? <p className="bed-empty">No beds configured.</p> : <div className="bed-list">{department.beds.map((bed) => <div key={bed.id} className={`bed-row ${bed.status === "retired" ? "bed-row-retired" : ""}`}><span className="bed-row-icon"><BedDouble size={15} /></span><span className="bed-row-code">{bed.code}</span><span className="bed-category">{bed.category}</span><span className={`bed-status bed-status-${bed.status}`}>{bed.status.replaceAll("_", " ")}</span><button disabled={selectedHospital.is_archived || department.is_archived} className="studio-icon-button bed-edit-button" onClick={() => setDialog({ type: "bed", hospital: selectedHospital, department, item: bed })} aria-label={`Edit bed ${bed.code}`} title="Edit bed"><Edit3 size={14} /></button></div>)}</div>}
              </article>;
            })}</div>}
          </>}
        </section>
      </div>
      <footer className="studio-footer">Hospital records are workspace-owned. Bed capacity and department relationships are validated by the API.</footer>

      {dialog?.type === "hospital" && <ModalFrame title={dialog.item ? "Edit hospital" : "Create hospital"} onClose={closeDialog}><HospitalForm item={dialog.item} networks={networks} onClose={closeDialog} onSave={(data) => saveHospital(data, dialog.item)} /></ModalFrame>}
      {dialog?.type === "network" && <ModalFrame title="Create network" onClose={closeDialog}><NetworkForm onClose={closeDialog} onSave={saveNetwork} /></ModalFrame>}
      {dialog?.type === "department" && <ModalFrame title={dialog.item ? "Edit department" : "Add department"} onClose={closeDialog}><DepartmentForm item={dialog.item} onClose={closeDialog} onSave={(data) => saveDepartment(dialog.hospital, data, dialog.item)} /></ModalFrame>}
      {dialog?.type === "bed" && <ModalFrame title={dialog.item ? "Edit bed" : "Add bed"} onClose={closeDialog}><BedForm item={dialog.item} department={dialog.department} departments={dialog.hospital.departments} onClose={closeDialog} onSave={(data) => saveBed(dialog.hospital, dialog.department, data, dialog.item)} /></ModalFrame>}
      {dialog?.type === "generation" && <ModalFrame title="Review bed generation" onClose={closeDialog}><div className="studio-form"><p className="studio-form-intro">Review the missing bed inventory before creation. New beds use the operational status and general category.</p><div className="generation-table-wrap"><table className="generation-table"><thead><tr><th>Department</th><th>Capacity</th><th>Create</th><th>Identifiers</th></tr></thead><tbody>{dialog.preview.departments.map((row) => <tr key={row.department_id}><td><strong>{row.department_name}</strong><small>{row.department_code}</small></td><td>{row.existing_beds} / {row.capacity ?? "Not set"}</td><td>{row.beds_to_create}{row.note && row.beds_to_create === 0 && <small>{row.note}</small>}</td><td className="generation-codes">{row.first_bed_code ? `${row.first_bed_code} – ${row.last_bed_code}` : "—"}</td></tr>)}</tbody></table></div><div className="generation-total"><span>Total beds to create</span><strong>{dialog.preview.total_to_create}</strong></div><FormError message={loadError} /><div className="studio-form-actions"><button type="button" className="studio-button studio-button-secondary" onClick={closeDialog}>Cancel</button><button disabled={working || dialog.preview.total_to_create === 0} className="studio-button studio-button-primary" onClick={() => void confirmBedGeneration()}>{working && <LoaderCircle className="spin" size={16} />}Create {dialog.preview.total_to_create} beds</button></div></div></ModalFrame>}
      {working && <div className="studio-saving-indicator" role="status"><LoaderCircle className="spin" size={15} /> Syncing with workspace…</div>}
    </main>
  );
}
