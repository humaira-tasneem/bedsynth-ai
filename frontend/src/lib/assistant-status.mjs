export const GEMINI_STATUS_LABELS = Object.freeze({
  checking: "Checking Gemini",
  backend_offline: "Backend unavailable",
  not_configured: "API key not configured",
  configured: "Gemini key configured · not yet tested",
  ready: "Gemini ready",
  quota: "Gemini quota exceeded",
  unavailable: "Gemini unavailable",
  authentication: "Gemini authentication failed",
  model_error: "Gemini model unavailable",
});

export const GROQ_STATUS_LABELS = Object.freeze({
  checking: "Checking Groq",
  backend_offline: "Backend unavailable",
  not_configured: "Groq API key not configured",
  configured: "Groq key configured · not yet tested",
  ready: "Groq available",
  quota: "Groq quota exceeded",
  unavailable: "Groq unavailable",
  authentication: "Groq authentication failed",
  model_error: "Groq model unavailable",
  not_used: "Groq not used",
});

export function geminiStatusFromKeyConfiguration(keyConfigured) {
  return keyConfigured ? "configured" : "not_configured";
}

export function groqStatusFromKeyConfiguration(keyConfigured) {
  return keyConfigured ? "configured" : "not_configured";
}

export function backendHealthLabel(status) {
  if (status === "online") return "Backend connected";
  if (status === "offline") return "Backend unavailable";
  return "Checking backend";
}

export function geminiStatusFromCategory(category) {
  if (category === "not_configured") return "not_configured";
  if (category === "quota") return "quota";
  if (category === "authentication") return "authentication";
  if (category === "model_not_found") return "model_error";
  if (["provider_unavailable", "timeout", "network_error", "provider_error"].includes(category)) return "unavailable";
  return "unavailable";
}

export function geminiStatusFromResponse(result) {
  if (result?.gemini_status && result.gemini_status !== "not_used") return providerStatusFromCategory(result.gemini_status);
  if (result?.assistant_source === "gemini") return "ready";
  if (result?.assistant_source === "local" && result.provider_category !== "local_only") return geminiStatusFromCategory(result.provider_category);
  return null;
}

export function groqStatusFromResponse(result) {
  if (result?.groq_status && result.groq_status !== "not_used") return providerStatusFromCategory(result.groq_status);
  if (result?.assistant_source === "groq") return "ready";
  return null;
}

export function providerStatusFromCategory(category) {
  if (["not_configured", "configured", "ready", "quota", "authentication", "model_not_found", "not_used"].includes(category)) {
    return category === "model_not_found" ? "model_error" : category;
  }
  return "unavailable";
}

export function assistantSourceLabel(source) {
  return source === "local" ? "Local fallback used" : source === "groq" ? "Groq backup response" : source === "gemini" ? "Gemini response" : "Not yet used";
}

export function geminiStatusLabel(status) {
  return GEMINI_STATUS_LABELS[status] ?? GEMINI_STATUS_LABELS.checking;
}

export function groqStatusLabel(status) {
  return GROQ_STATUS_LABELS[status] ?? GROQ_STATUS_LABELS.checking;
}
