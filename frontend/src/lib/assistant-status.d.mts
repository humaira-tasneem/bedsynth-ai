export type GeminiUiStatus =
  | "checking"
  | "backend_offline"
  | "not_configured"
  | "configured"
  | "ready"
  | "quota"
  | "unavailable"
  | "authentication"
  | "model_error";
export type GroqUiStatus = GeminiUiStatus | "not_used";

export const GEMINI_STATUS_LABELS: Readonly<Record<GeminiUiStatus, string>>;
export const GROQ_STATUS_LABELS: Readonly<Record<GroqUiStatus, string>>;
export function geminiStatusFromKeyConfiguration(keyConfigured: boolean): "configured" | "not_configured";
export function groqStatusFromKeyConfiguration(keyConfigured: boolean): "configured" | "not_configured";
export function backendHealthLabel(status: "checking" | "online" | "offline"): string;
export function geminiStatusFromCategory(category: string): GeminiUiStatus;
export function providerStatusFromCategory(category: string): GroqUiStatus;
export function geminiStatusFromResponse(result: { assistant_source?: string; provider_category?: string | null; gemini_status?: string } | null | undefined): GeminiUiStatus | null;
export function groqStatusFromResponse(result: { assistant_source?: string; groq_status?: string } | null | undefined): GroqUiStatus | null;
export function geminiStatusLabel(status: GeminiUiStatus): string;
export function groqStatusLabel(status: GroqUiStatus): string;
export function assistantSourceLabel(source: "gemini" | "groq" | "local" | "not_checked"): string;
