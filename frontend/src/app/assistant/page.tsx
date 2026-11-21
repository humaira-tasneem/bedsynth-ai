"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Bot, Check, CircleAlert, LoaderCircle, MessageCircle, RotateCcw, Send, Sparkles } from "lucide-react";
import { assistantSourceLabel, geminiStatusFromCategory, geminiStatusFromKeyConfiguration, geminiStatusFromResponse, geminiStatusLabel, groqStatusFromKeyConfiguration, groqStatusFromResponse, groqStatusLabel } from "@/lib/assistant-status.mjs";
import type { GeminiUiStatus, GroqUiStatus } from "@/lib/assistant-status.mjs";

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
type Message = { role: Role; content: string; source?: "gemini" | "groq" | "local" | "not_checked"; questions?: string[]; errors?: { field: string; message: string }[] };
type Config = {
  workspace_id: number; hospital_id: number; hospital_name: string; start_date: string; end_date: string;
  target_admissions: number; target_occupancy_pct: number; seed: number; department_ids: number[] | null;
  department_names: string[] | null;
};
type PendingProposal = { configuration: Config; seedAssignedByApplication: boolean };
type ChatResult = { status: "needs_clarification" | "ready" | "invalid"; assistant_message: string; assistant_source: "gemini" | "groq" | "local" | "not_checked"; gemini_status: string; groq_status: string; provider_category: string | null; retry_after_seconds: number | null; questions: string[]; field_errors: { field: string; message: string }[]; configuration: Config | null; seed_assigned_by_application: boolean };

type RetryRequest = { message: string; history: Message[] };

class AssistantApiError extends Error {
  category: string | null;
  retryAfterSeconds: number | null;

  constructor(message: string, category: string | null = null, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = "AssistantApiError";
    this.category = category;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

const retryableGeminiCategories = new Set(["quota", "timeout", "provider_unavailable", "network_error"]);

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}/api/v1${path}`, { ...options, credentials: "include", headers: { "Content-Type": "application/json", ...options.headers }, cache: "no-store" });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    if (typeof detail === "string") throw new AssistantApiError(detail);
    if (typeof detail?.category === "string") {
      const categoryMessages: Record<string, string> = {
        not_configured: "Gemini API key is not configured on the backend.",
        authentication: "Gemini authentication failed. The backend API key or its access may need attention.",
        quota: "Gemini has reached a temporary quota or rate limit. Please try again later.",
        model_not_found: "The configured Gemini model could not be found. Please contact the administrator.",
        timeout: "Gemini took too long to respond. Please try again.",
        provider_unavailable: "Gemini is temporarily unavailable. Please try again in a few minutes.",
        network_error: "The backend could not connect to Gemini. Please check backend connectivity and try again.",
        provider_error: "Gemini could not process this request. Please try again or use the standard generator.",
      };
      const retryAfter = Number(detail.retry_after_seconds ?? response.headers.get("Retry-After"));
      throw new AssistantApiError(
        categoryMessages[detail.category] ?? "The assistant is temporarily unavailable. Please try again.",
        detail.category,
        Number.isFinite(retryAfter) && retryAfter > 0 ? Math.ceil(retryAfter) : null,
      );
    }
    if (detail?.field_errors) throw new AssistantApiError(detail.field_errors.map((item: { field: string; message: string }) => `${item.field}: ${item.message}`).join(" "));
    if (Array.isArray(detail)) throw new AssistantApiError(detail.map((item: { loc?: (string | number)[]; msg?: string }) => `${item.loc?.at(-1) ?? "configuration"}: ${item.msg ?? "Invalid value"}`).join(" "));
    throw new AssistantApiError(`Request failed (${response.status}).`, response.status >= 500 ? "provider_unavailable" : null);
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
  const [geminiStatus, setGeminiStatus] = useState<GeminiUiStatus>("checking");
  const [groqStatus, setGroqStatus] = useState<GroqUiStatus>("checking");
  const [backendStatus, setBackendStatus] = useState<"checking" | "online" | "offline">("checking");
  const [retryRequest, setRetryRequest] = useState<RetryRequest | null>(null);
  const [retryNotBefore, setRetryNotBefore] = useState<number | null>(null);
  const [retryWaitSeconds, setRetryWaitSeconds] = useState(0);
  const [localFallbackOnly, setLocalFallbackOnly] = useState(false);
  const [localFallbackCategory, setLocalFallbackCategory] = useState<string | null>(null);
  const localFallbackRef = useRef(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = window.localStorage.getItem("bedsynth-theme");
    const useDark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = useDark ? "dark" : "light";
  }, []);

  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem("bedsynth-assistant-local-mode");
      if (saved) {
        const value = JSON.parse(saved) as { category?: string; retryNotBefore?: number; geminiStatus?: GeminiUiStatus; groqStatus?: GroqUiStatus };
        localFallbackRef.current = true;
        setLocalFallbackOnly(true);
        setLocalFallbackCategory(value.category ?? "provider_unavailable");
        setGeminiStatus(geminiStatusFromCategory(value.category ?? "provider_unavailable"));
        if (value.geminiStatus) setGeminiStatus(value.geminiStatus);
        if (value.groqStatus) setGroqStatus(value.groqStatus);
        if (value.retryNotBefore && value.retryNotBefore > Date.now()) setRetryNotBefore(value.retryNotBefore);
      }
    } catch {
      window.sessionStorage.removeItem("bedsynth-assistant-local-mode");
    }
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
    const controller = new AbortController();
    api<{ gemini_key_configured: boolean; groq_key_configured: boolean }>("/assistant/status", { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) {
          setBackendStatus("online");
          if (!localFallbackRef.current) {
            setGeminiStatus(geminiStatusFromKeyConfiguration(result.gemini_key_configured));
            setGroqStatus(groqStatusFromKeyConfiguration(result.groq_key_configured));
          }
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) { setBackendStatus("offline"); setGeminiStatus("backend_offline"); setGroqStatus("backend_offline"); }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (retryNotBefore === null) { setRetryWaitSeconds(0); return; }
    const update = () => setRetryWaitSeconds(Math.max(0, Math.ceil((retryNotBefore - Date.now()) / 1000)));
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [retryNotBefore]);

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

  async function sendMessage(event?: FormEvent, suggested?: string, retry?: RetryRequest) {
    event?.preventDefault();
    const message = (retry?.message ?? suggested ?? input).trim();
    if (!message || workspaceId === null || sending) return;
    const priorMessages = retry?.history ?? messages;
    setInput(""); setError(""); setSending(true);
    if (retry) setRetryNotBefore(null);
    if (!retry) setRetryRequest(null);
    if (config) setValidated(false);
    setPendingConfiguration(null);
    if (!retry) setMessages((current) => [...current, { role: "user", content: message }]);
    try {
      const result = await api<ChatResult>("/assistant/chat", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspaceId, message, history: priorMessages.map(({ role, content }) => ({ role, content })), local_fallback_only: localFallbackOnly && !retry }),
      });
      setBackendStatus("online");
      setMessages((current) => [...current, { role: "assistant", content: result.assistant_message, source: result.assistant_source, questions: result.questions, errors: result.field_errors }]);
      const responseStatus = geminiStatusFromResponse(result);
      if (responseStatus) setGeminiStatus(responseStatus);
      const backupStatus = groqStatusFromResponse(result);
      if (backupStatus) setGroqStatus(backupStatus);
      if (result.assistant_source === "local") {
        const category = result.provider_category === "local_only" ? localFallbackCategory : result.provider_category;
        const retryDeadline = result.provider_category === "local_only"
          ? retryNotBefore
          : result.retry_after_seconds ? Date.now() + result.retry_after_seconds * 1000 : null;
        localFallbackRef.current = true;
        setLocalFallbackOnly(true);
        setLocalFallbackCategory(category ?? null);
        window.sessionStorage.setItem("bedsynth-assistant-local-mode", JSON.stringify({ category: category ?? "provider_unavailable", retryNotBefore: retryDeadline, geminiStatus: result.gemini_status, groqStatus: result.groq_status }));
        setRetryRequest({ message, history: priorMessages });
        if (result.provider_category !== "local_only") setRetryNotBefore(retryDeadline);
      } else {
        setRetryRequest(null);
        localFallbackRef.current = false;
        setLocalFallbackOnly(false);
        setLocalFallbackCategory(null);
        window.sessionStorage.removeItem("bedsynth-assistant-local-mode");
        setRetryNotBefore(null);
      }
      if (result.configuration && result.status === "ready") {
        if (config) setPendingConfiguration({ configuration: result.configuration, seedAssignedByApplication: result.seed_assigned_by_application });
        else { setConfig(result.configuration); setValidated(true); setSeedAssignedByApplication(result.seed_assigned_by_application); }
      }
      else setValidated(false);
    } catch (cause) {
      const requestError = cause instanceof AssistantApiError ? cause : null;
      setError(cause instanceof Error ? cause.message : "The assistant request failed.");
      if (requestError?.category) setGeminiStatus(geminiStatusFromCategory(requestError.category));
      else if (!requestError && cause instanceof TypeError) { setBackendStatus("offline"); setGeminiStatus("backend_offline"); setGroqStatus("backend_offline"); }
      const canRetry = (requestError?.category && retryableGeminiCategories.has(requestError.category)) || (!requestError && cause instanceof TypeError);
      setRetryRequest(canRetry ? { message, history: priorMessages } : null);
      setRetryNotBefore(requestError?.retryAfterSeconds ? Date.now() + requestError.retryAfterSeconds * 1000 : null);
      if (!retry) setMessages((current) => [...current, { role: "assistant", content: "I couldn't process that request. Use Retry after the displayed service limit clears." }]);
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
    setMessages([]); setInput(""); setConfig(null); setPendingConfiguration(null); setSeedAssignedByApplication(false); setValidated(false); setError(""); setRetryRequest(null); setRetryNotBefore(null);
  }

  function useGeminiForNextMessage() {
    localFallbackRef.current = false;
    setLocalFallbackOnly(false);
    setLocalFallbackCategory(null);
    window.sessionStorage.removeItem("bedsynth-assistant-local-mode");
    setError("Gemini is enabled for your next message. No request was sent yet.");
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

      <div className="assistant-provider-overview" role="status" aria-live="polite">
        <span className={`assistant-provider-pill assistant-provider-${backendStatus}`}><i aria-hidden="true" />Backend {backendStatus === "online" ? "connected" : backendStatus === "offline" ? "unavailable" : "checking"}</span>
        <span className={`assistant-provider-pill assistant-provider-${geminiStatus}`}><i aria-hidden="true" />{geminiStatusLabel(geminiStatus)}</span>
        <span className={`assistant-provider-pill assistant-provider-${groqStatus}`}><i aria-hidden="true" />{groqStatusLabel(groqStatus)}</span>
      </div>
      {localFallbackOnly && <div className="assistant-local-mode" role="status" aria-live="polite">
        <span className="assistant-local-mode-mark"><Bot size={14} /></span>
        <span className="assistant-local-mode-copy"><strong>Local mode active</strong><small className="assistant-local-provider-status">{backendStatus === "offline" ? "The backend is disconnected, so local parsing cannot run until it reconnects." : "The latest response used explicit local parsing because AI providers were unavailable or local-only mode was selected."}</small><small>Review the proposal before validation and preview; this assistant never creates records.</small></span>
        {retryRequest ? <button type="button" className="assistant-gemini-retry" onClick={() => void sendMessage(undefined, undefined, retryRequest)} disabled={sending || retryWaitSeconds > 0}>{sending ? "Retrying providers…" : retryWaitSeconds > 0 ? `Retry in ${retryWaitSeconds}s` : "Retry AI providers"}</button> : <button type="button" className="assistant-gemini-retry" onClick={useGeminiForNextMessage} disabled={retryWaitSeconds > 0}>Use AI providers for next message</button>}
      </div>}

      {error && <div className="generator-alert generator-alert-error" role="alert"><CircleAlert size={17} /><span>{error}{retryRequest && retryWaitSeconds > 0 ? ` Retry is available in ${retryWaitSeconds} seconds.` : ""}</span></div>}
      {loading ? <div className="generator-loading"><LoaderCircle className="generator-spin" />Loading workspace…</div> : !workspaces.length ? <div className="generator-empty"><span className="generator-empty-icon"><MessageCircle size={19} /></span><h2>No workspace found</h2><p>Create a workspace and configure at least one active hospital before using the assistant.</p><Link className="generator-button generator-button-primary" href="/hospitals">Open Hospital Studio</Link></div> : <div className="assistant-layout">
        <section className="generator-card assistant-chat-card" aria-label="Assistant conversation">
          <div className="assistant-chat-header"><div><span className="assistant-avatar"><Bot size={18} /></span><div><strong>BedSynth Assistant</strong><small>Configuration support only</small></div></div><button type="button" className="assistant-reset" onClick={resetConversation} disabled={sending || validating}><RotateCcw size={14} /> New conversation</button></div>
          <div className="assistant-messages" ref={scrollRef} aria-live="polite" aria-label="Conversation messages">
            {!messages.length && <div className="assistant-welcome"><span><Sparkles size={19} /></span><h2>What would you like to generate?</h2><p>Use fictional operations requirements only. Do not enter patient names, identifiers, or clinical details.</p><div className="assistant-suggestions">{suggestions.map((suggestion) => <button key={suggestion} type="button" disabled={!workspaceId || sending} onClick={() => void sendMessage(undefined, suggestion)}>{suggestion}</button>)}</div></div>}
            {messages.map((message, index) => <article key={`${index}-${message.role}`} className={`assistant-message assistant-message-${message.role}`}><span className="assistant-message-avatar" aria-hidden="true">{message.role === "assistant" ? <Bot size={14} /> : "You"}</span><div className="assistant-message-body">{message.role === "assistant" && message.source && <small className={`assistant-message-source assistant-message-source-${message.source}`}>{assistantSourceLabel(message.source)}</small>}<p>{message.content}</p>{message.questions?.length ? <ul>{message.questions.map((question) => <li key={question}>{question}</li>)}</ul> : null}{message.errors?.length ? <ul className="assistant-message-errors">{message.errors.map((item, errorIndex) => <li key={`${item.field}-${errorIndex}`}><strong>{item.field}:</strong> {item.message}</li>)}</ul> : null}</div></article>)}
            {sending && <div className="assistant-typing" role="status"><LoaderCircle className="generator-spin" size={15} /> Interpreting configuration…</div>}
          </div>
          <form className="assistant-composer" onSubmit={(event) => void sendMessage(event)}><label htmlFor="assistant-message">Message</label><div><textarea id="assistant-message" value={input} onChange={(event) => setInput(event.target.value)} placeholder="Describe hospital, dates, admissions, and occupancy…" maxLength={2000} rows={3} disabled={sending || !workspaceId} /><button type="submit" className="generator-button generator-button-primary" disabled={!input.trim() || !workspaceId || sending} aria-label="Send message">{sending ? <LoaderCircle className="generator-spin" size={16} /> : <Send size={16} />}<span>Send</span></button></div><small>{localFallbackOnly ? "Messages are parsed locally; neither provider is called until you explicitly retry. Do not include patient information." : "Requests and recent conversation turns are sent to Gemini, with Groq as its configured backup. Do not include patient information."}</small></form>
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
