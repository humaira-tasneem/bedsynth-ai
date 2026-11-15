"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Bot, Check, CircleAlert, LoaderCircle, MessageCircle, RotateCcw, Send, Sparkles } from "lucide-react";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const suggestions = [
  "Generate 200 admissions for Sunrise General Hospital from January 1 to March 31, 2027, with 75% target occupancy.",
  "Create a 30-day dataset for Sunrise General Hospital with 70% target occupancy and 100 admissions.",
  "Generate 80 admissions for the Cardiology and Neurology departments at Sunrise General Hospital from June 1 to June 30, 2027, with 70% occupancy.",
  "Help me configure a synthetic hospital dataset.",
];
type Workspace = { id: number; name: string };
type Department = { id: number; code: string; name: string; is_archived: boolean };
type Hospital = { id: number; workspace_id: number; name: string; code: string; is_archived: boolean; departments: Department[] };
type Role = "user" | "assistant";
type Message = { role: Role; content: string; questions?: string[]; errors?: { field: string; message: string }[] };
type Config = {
  workspace_id: number; hospital_id: number; hospital_name: string; start_date: string; end_date: string;
  target_admissions: number; target_occupancy_pct: number; seed: number; department_ids: number[] | null;
  department_names: string[] | null;
};
type PendingProposal = { configuration: Config; seedAssignedByApplication: boolean };
type ChatResult = { status: "needs_clarification" | "ready" | "invalid"; assistant_message: string; questions: string[]; field_errors: { field: string; message: string }[]; configuration: Config | null; seed_assigned_by_application: boolean };

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, { ...options, headers: { "Content-Type": "application/json", ...options.headers }, cache: "no-store" });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    if (typeof detail === "string") throw new Error(detail);
    if (typeof detail?.category === "string") {
      const categoryMessages: Record<string, string> = {
        authentication: "Gemini authentication failed. The backend API key or its access may need attention.",
        quota: "Gemini has reached a temporary quota or rate limit. Please try again later.",
        model_not_found: "The configured Gemini model could not be found. Please contact the administrator.",
        timeout: "Gemini took too long to respond. Please try again.",
        provider_unavailable: "Gemini is temporarily unavailable. Please try again in a few minutes.",
        network_error: "The backend could not connect to Gemini. Please check backend connectivity and try again.",
        provider_error: "Gemini could not process this request. Please try again or use the standard generator.",
      };
      throw new Error(categoryMessages[detail.category] ?? "The assistant is temporarily unavailable. Please try again.");
    }
    if (detail?.field_errors) throw new Error(detail.field_errors.map((item: { field: string; message: string }) => `${item.field}: ${item.message}`).join(" "));
    if (Array.isArray(detail)) throw new Error(detail.map((item: { loc?: (string | number)[]; msg?: string }) => `${item.loc?.at(-1) ?? "configuration"}: ${item.msg ?? "Invalid value"}`).join(" "));
    throw new Error(`Request failed (${response.status}).`);
  }
  return body as T;
}

function generationFields(config: Config) {
  return {
    start_date: config.start_date, end_date: config.end_date, target_admissions: Number(config.target_admissions),
    target_occupancy_pct: Number(config.target_occupancy_pct), seed: Number(config.seed), department_ids: config.department_ids,
  };
}

export default function AssistantPage() {
  const router = useRouter();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [hospitals, setHospitals] = useState<Hospital[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [config, setConfig] = useState<Config | null>(null);
  const [pendingConfiguration, setPendingConfiguration] = useState<PendingProposal | null>(null);
  const [seedAssignedByApplication, setSeedAssignedByApplication] = useState(false);
  const [validated, setValidated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = window.localStorage.getItem("bedsynth-theme");
    const useDark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = useDark ? "dark" : "light";
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const rows = await api<Workspace[]>("/workspaces", { signal: controller.signal });
        if (controller.signal.aborted) return;
        setWorkspaces(rows);
        setWorkspaceId(rows[0]?.id ?? null);
      } catch (cause) { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Workspaces could not be loaded."); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!workspaceId) { setHospitals([]); return; }
    const controller = new AbortController();
    api<Hospital[]>(`/workspaces/${workspaceId}/hospitals`, { signal: controller.signal }).then((rows) => {
      if (!controller.signal.aborted) setHospitals(rows.filter((hospital) => !hospital.is_archived));
    }).catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Hospitals could not be loaded."); });
    return () => controller.abort();
  }, [workspaceId]);

  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [messages, sending]);

  const activeHospitals = useMemo(() => hospitals.filter((hospital) => !hospital.is_archived), [hospitals]);
  const selectedHospital = config ? hospitals.find((hospital) => hospital.id === config.hospital_id) : undefined;
  const activeDepartments = selectedHospital?.departments.filter((department) => !department.is_archived) ?? [];

  async function sendMessage(event?: FormEvent, suggested?: string) {
    event?.preventDefault();
    const message = (suggested ?? input).trim();
    if (!message || workspaceId === null || sending) return;
    const priorMessages = messages;
    setInput(""); setError(""); setSending(true);
    if (config) setValidated(false);
    setPendingConfiguration(null);
    setMessages((current) => [...current, { role: "user", content: message }]);
    try {
      const result = await api<ChatResult>("/assistant/chat", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspaceId, message, history: priorMessages.map(({ role, content }) => ({ role, content })) }),
      });
      setMessages((current) => [...current, { role: "assistant", content: result.assistant_message, questions: result.questions, errors: result.field_errors }]);
      if (result.configuration && result.status === "ready") {
        if (config) setPendingConfiguration({ configuration: result.configuration, seedAssignedByApplication: result.seed_assigned_by_application });
        else { setConfig(result.configuration); setValidated(true); setSeedAssignedByApplication(result.seed_assigned_by_application); }
      }
      else setValidated(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The assistant request failed.");
      setMessages((current) => [...current, { role: "assistant", content: "I couldn't process that request. Review the message and try again." }]);
    } finally { setSending(false); }
  }

  function changeConfig<K extends keyof Config>(key: K, value: Config[K]) {
    setConfig((current) => current ? { ...current, [key]: value } : current);
    if (key === "seed") setSeedAssignedByApplication(false);
    setValidated(false); setPendingConfiguration(null); setError("");
  }

  async function validateConfig() {
    if (!config) return;
    setValidating(true); setError("");
    try {
      const result = await api<{ valid: true; configuration: Config }>("/assistant/validate-config", {
        method: "POST", body: JSON.stringify({ workspace_id: config.workspace_id, hospital_id: config.hospital_id, configuration: generationFields(config) }),
      });
      setConfig({ ...config, ...result.configuration });
      setValidated(result.valid);
    } catch (cause) { setValidated(false); setError(cause instanceof Error ? cause.message : "Configuration validation failed."); }
    finally { setValidating(false); }
  }

  function continueToGenerator() {
    if (!config || !validated) return;
    const approved = { workspace_id: config.workspace_id, hospital_id: config.hospital_id, ...generationFields(config) };
    window.sessionStorage.setItem("bedsynth-approved-assistant-config", JSON.stringify(approved));
    router.push("/generate");
  }

  function resetConversation() {
    setMessages([]); setInput(""); setConfig(null); setPendingConfiguration(null); setSeedAssignedByApplication(false); setValidated(false); setError("");
  }

  function toggleDepartment(id: number) {
    if (!config) return;
    const selected = config.department_ids === null ? activeDepartments.map((department) => department.id) : config.department_ids;
    const next = selected.includes(id) ? selected.filter((departmentId) => departmentId !== id) : [...selected, id];
    const effective = next.length === activeDepartments.length ? null : next;
    const names = effective === null ? null : activeDepartments.filter((department) => effective.includes(department.id)).map((department) => department.name);
    setConfig({ ...config, department_ids: effective, department_names: names }); setValidated(false); setPendingConfiguration(null);
  }

  return <main className="generator-page assistant-page" id="main-content">
    <header className="generator-topbar"><Link href="/" className="generator-brand"><span className="generator-brand-mark"><Sparkles size={18} /></span><span>BedSynth <strong>AI</strong></span></Link><nav aria-label="Assistant navigation"><Link href="/" className="generator-nav-link"><ArrowLeft size={14} /> Overview</Link><Link href="/generate" className="generator-nav-link">Generator</Link></nav></header>
    <div className="assistant-content">
      <div className="assistant-heading"><div><span className="generator-kicker"><Bot size={14} /> GENERATION ASSISTANT</span><h1>Describe your dataset</h1><p>Turn a request into a validated configuration. The assistant never creates records.</p></div><div className="assistant-heading-actions"><label htmlFor="assistant-workspace">Workspace</label><select id="assistant-workspace" value={workspaceId ?? ""} disabled={loading || sending || !workspaces.length} onChange={(event) => { setWorkspaceId(Number(event.target.value)); resetConversation(); }}><option value="">Select workspace</option>{workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select></div></div>

      {error && <div className="generator-alert generator-alert-error" role="alert"><CircleAlert size={17} /><span>{error}</span></div>}
      {loading ? <div className="generator-loading"><LoaderCircle className="generator-spin" />Loading workspace…</div> : !workspaces.length ? <div className="generator-empty"><span className="generator-empty-icon"><MessageCircle size={19} /></span><h2>No workspace found</h2><p>Create a workspace and configure at least one active hospital before using the assistant.</p><Link className="generator-button generator-button-primary" href="/hospitals">Open Hospital Studio</Link></div> : <div className="assistant-layout">
        <section className="generator-card assistant-chat-card" aria-label="Assistant conversation">
          <div className="assistant-chat-header"><div><span className="assistant-avatar"><Bot size={18} /></span><div><strong>BedSynth Assistant</strong><small>Configuration support only</small></div></div><button type="button" className="assistant-reset" onClick={resetConversation} disabled={sending || validating}><RotateCcw size={14} /> New conversation</button></div>
          <div className="assistant-messages" ref={scrollRef} aria-live="polite" aria-label="Conversation messages">
            {!messages.length && <div className="assistant-welcome"><span><Sparkles size={19} /></span><h2>What would you like to generate?</h2><p>Use fictional operations requirements only. Do not enter patient names, identifiers, or clinical details.</p><div className="assistant-suggestions">{suggestions.map((suggestion) => <button key={suggestion} type="button" disabled={!workspaceId || sending} onClick={() => void sendMessage(undefined, suggestion)}>{suggestion}</button>)}</div></div>}
            {messages.map((message, index) => <article key={`${index}-${message.role}`} className={`assistant-message assistant-message-${message.role}`}><span className="assistant-message-avatar" aria-hidden="true">{message.role === "assistant" ? <Bot size={14} /> : "You"}</span><div className="assistant-message-body"><p>{message.content}</p>{message.questions?.length ? <ul>{message.questions.map((question) => <li key={question}>{question}</li>)}</ul> : null}{message.errors?.length ? <ul className="assistant-message-errors">{message.errors.map((item, errorIndex) => <li key={`${item.field}-${errorIndex}`}><strong>{item.field}:</strong> {item.message}</li>)}</ul> : null}</div></article>)}
            {sending && <div className="assistant-typing" role="status"><LoaderCircle className="generator-spin" size={15} /> Interpreting configuration…</div>}
          </div>
          <form className="assistant-composer" onSubmit={(event) => void sendMessage(event)}><label htmlFor="assistant-message">Message</label><div><textarea id="assistant-message" value={input} onChange={(event) => setInput(event.target.value)} placeholder="Describe hospital, dates, admissions, and occupancy…" maxLength={2000} rows={3} disabled={sending || !workspaceId} /><button type="submit" className="generator-button generator-button-primary" disabled={!input.trim() || !workspaceId || sending} aria-label="Send message">{sending ? <LoaderCircle className="generator-spin" size={16} /> : <Send size={16} />}<span>Send</span></button></div><small>Requests and recent conversation turns are sent to Gemini. Do not include patient information.</small></form>
        </section>

        <aside className="assistant-config-column">
          <section className="generator-card assistant-config-card" aria-labelledby="assistant-config-title"><div className="generator-card-header"><span className="generator-section-icon"><Check size={17} /></span><div><h2 id="assistant-config-title">Proposed configuration</h2><p>Review and edit before approval.</p></div></div>
            {!config ? <div className="assistant-config-empty"><MessageCircle size={23} /><p>Complete the required details in chat to see a structured proposal.</p></div> : <div className="assistant-config-form">
              {pendingConfiguration && <div className="assistant-pending-proposal" role="status"><strong>New assistant proposal</strong><span>Your current configuration was kept unchanged.</span><div><button type="button" onClick={() => { setConfig(pendingConfiguration.configuration); setSeedAssignedByApplication(pendingConfiguration.seedAssignedByApplication); setPendingConfiguration(null); setValidated(true); }}>Apply proposal</button><button type="button" onClick={() => setPendingConfiguration(null)}>Keep current</button></div></div>}
              <label>Hospital<select disabled={sending || validating} value={config.hospital_id} onChange={(event) => { const hospital = hospitals.find((item) => item.id === Number(event.target.value)); if (hospital) { setConfig({ ...config, hospital_id: hospital.id, hospital_name: hospital.name, department_ids: null, department_names: null }); setValidated(false); } }}>{activeHospitals.map((hospital) => <option key={hospital.id} value={hospital.id}>{hospital.name}</option>)}</select></label>
              <div className="generator-two-column"><label>Start date<input disabled={sending || validating} type="date" value={config.start_date} onChange={(event) => changeConfig("start_date", event.target.value)} /></label><label>End date<input disabled={sending || validating} type="date" value={config.end_date} onChange={(event) => changeConfig("end_date", event.target.value)} /></label></div>
              <div className="generator-two-column"><label>Admissions<input disabled={sending || validating} type="number" min={0} max={5000} value={config.target_admissions} onChange={(event) => changeConfig("target_admissions", Number(event.target.value))} /></label><label>Seed<input disabled={sending || validating} type="number" min={0} max={2147483647} value={config.seed} onChange={(event) => changeConfig("seed", Number(event.target.value))} /></label></div>
              <label>Target occupancy <strong>{config.target_occupancy_pct}%</strong><input disabled={sending || validating} type="range" min={0} max={100} step={1} value={config.target_occupancy_pct} onChange={(event) => changeConfig("target_occupancy_pct", Number(event.target.value))} /></label>
              <fieldset className="assistant-departments"><legend>Departments <span>(all active by default)</span></legend>{activeDepartments.map((department) => { const checked = config.department_ids === null || config.department_ids.includes(department.id); return <label key={department.id}><input type="checkbox" disabled={sending || validating} checked={checked} onChange={() => toggleDepartment(department.id)} /><span>{department.name}<small>{department.code}</small></span></label>; })}</fieldset>
              <div className="assistant-seed-note">Seed {config.seed} is {seedAssignedByApplication ? "assigned by the application" : "editable for reproducibility"}.</div>
              <button type="button" className="generator-button generator-button-secondary assistant-validate-button" onClick={() => void validateConfig()} disabled={validating || sending}>{validating ? <LoaderCircle className="generator-spin" size={15} /> : <Check size={15} />} Validate configuration</button>
              {validated && <p className="assistant-valid-state" role="status"><Check size={14} /> Configuration is valid. Review it and continue to the generation preview.</p>}
              <button type="button" className="generator-button generator-button-primary assistant-approve-button" disabled={!validated || validating || sending} onClick={continueToGenerator}>Approve and continue to preview</button>
            </div>}
          </section>
          <p className="assistant-safety-note">Your explicit approval opens the existing generator preview. Creating records still requires a separate confirmation and uses its preview token and idempotency key.</p>
        </aside>
      </div>}
      <footer className="assistant-footer">Conversation stays in this browser session and is not saved as a permanent conversation record.</footer>
    </div>
  </main>;
}
