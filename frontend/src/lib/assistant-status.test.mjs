import test from "node:test";
import assert from "node:assert/strict";
import {
  backendHealthLabel,
  assistantSourceLabel,
  geminiStatusFromCategory,
  geminiStatusFromKeyConfiguration,
  geminiStatusFromResponse,
  geminiStatusLabel,
  groqStatusFromKeyConfiguration,
  groqStatusFromResponse,
  groqStatusLabel,
} from "./assistant-status.mjs";

test("backend reachability is labeled separately from Gemini provider state", () => {
  assert.equal(backendHealthLabel("online"), "Backend connected");
  assert.equal(backendHealthLabel("offline"), "Backend unavailable");
  assert.equal(geminiStatusFromKeyConfiguration(true), "configured");
  assert.equal(geminiStatusFromKeyConfiguration(false), "not_configured");
  assert.equal(groqStatusFromKeyConfiguration(true), "configured");
  assert.equal(groqStatusLabel("ready"), "Groq available");
  assert.equal(geminiStatusLabel("configured"), "Gemini key configured · not yet tested");
  assert.equal(geminiStatusLabel("not_configured"), "API key not configured");
});

test("provider outcomes map to distinct user-safe Gemini states", () => {
  assert.equal(geminiStatusFromCategory("quota"), "quota");
  assert.equal(geminiStatusLabel("quota"), "Gemini quota exceeded");
  assert.equal(geminiStatusFromCategory("authentication"), "authentication");
  assert.equal(geminiStatusFromCategory("not_configured"), "not_configured");
  assert.equal(geminiStatusFromCategory("provider_unavailable"), "unavailable");
  assert.equal(geminiStatusFromCategory("network_error"), "unavailable");
  assert.equal(geminiStatusFromCategory("timeout"), "unavailable");
  assert.equal(geminiStatusFromCategory("model_not_found"), "model_error");
});

test("only a provider-backed success is labeled Gemini ready", () => {
  assert.equal(geminiStatusFromResponse({ assistant_source: "gemini" }), "ready");
  assert.equal(geminiStatusFromResponse({ assistant_source: "local", provider_category: "timeout" }), "unavailable");
  assert.equal(geminiStatusFromResponse({ assistant_source: "local", provider_category: "network_error" }), "unavailable");
  assert.equal(geminiStatusFromResponse({ assistant_source: "local", provider_category: "local_only" }), null);
  assert.equal(assistantSourceLabel("local"), "Local fallback used");
  assert.equal(assistantSourceLabel("gemini"), "Gemini response");
  assert.equal(geminiStatusFromResponse({ assistant_source: "not_checked" }), null);
});

test("Gemini and Groq response health remain separate from the selected response source", () => {
  const groqBackup = { assistant_source: "groq", gemini_status: "quota", groq_status: "ready" };
  assert.equal(geminiStatusFromResponse(groqBackup), "quota");
  assert.equal(groqStatusFromResponse(groqBackup), "ready");
  assert.equal(assistantSourceLabel("groq"), "Groq backup response");

  const local = { assistant_source: "local", gemini_status: "unavailable", groq_status: "authentication" };
  assert.equal(geminiStatusFromResponse(local), "unavailable");
  assert.equal(groqStatusFromResponse(local), "authentication");
});
