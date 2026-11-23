import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../globals.css", import.meta.url), "utf8");
const shell = await readFile(new URL("../../components/AppShell.tsx", import.meta.url), "utf8");

test("admission type guidance explains categories, exact total, and example", () => {
  for (const text of [
    "Planned admissions are scheduled or non-emergency",
    "emergency admissions are unexpected",
    "distribution in the generated dataset",
    "must add up to exactly 100%",
    "70% planned + 30% emergency = 100%",
  ]) assert.ok(page.includes(text), `Expected admission guidance: ${text}`);
  assert.match(page, /Current total: \$\{arrivalMixTotal\}%\. Required total: 100%/);
});

test("department weights are described as optional relative weights with a neutral default tip", () => {
  for (const text of [
    "Optional department demand weights",
    "relative share of synthetic patient demand",
    "1 is neutral",
    "higher values mean relatively greater demand",
    "lower positive values mean relatively lower demand",
    "not percentages or exact patient counts",
    "scenario defaults or neutral weights apply",
    "Cardiology at 2 and Neurology at 1",
    "Keep all weights at 1. You can customize them later.",
  ]) assert.ok(page.includes(text), `Expected department weight guidance: ${text}`);
});

test("guidance-only change preserves existing arrival validation and request fields", () => {
  assert.match(page, /arrivalMixTotal === 100/);
  assert.match(page, /department_demand_weights: form\.department_demand_weights\.filter/);
  assert.match(page, /arrival_profile: form\.arrival_profile/);
});

test("patient profile controls use readable responsive age and gender cards", () => {
  for (const text of [
    "patient-age-card-grid",
    "patient-gender-card-grid",
    "Children",
    "Young adults",
    "Middle-aged adults",
    "Older adults",
    "Elderly",
    "Male",
    "Female",
    "Other",
    "age-distribution-total",
    "gender-distribution-total",
  ]) assert.ok(page.includes(text), `Expected patient profile UI: ${text}`);
  assert.match(page, /value=\{form\.patient_profile\.age_distribution\[field\.key\]\}/);
  assert.match(page, /value=\{form\.patient_profile\.gender_distribution\[field\.key\]\}/);
  assert.match(page, /AGE_PROFILE_FIELDS: \{ key: keyof AgeDistribution; label: string; range: string \}\[\]/);
  assert.match(styles, /\.patient-age-card-grid \{ grid-template-columns: repeat\(3, minmax\(0, 1fr\)\); \}/);
  assert.match(styles, /\.patient-gender-card-grid \{ grid-template-columns: repeat\(3, minmax\(0, 1fr\)\); \}/);
  assert.match(styles, /@media \(max-width: 720px\)[^\n]*patient-age-card-grid \{ grid-template-columns: repeat\(2, minmax\(0, 1fr\)\); \}/);
  assert.match(styles, /@media \(max-width: 520px\)[^\n]*patient-age-card-grid,.patient-gender-card-grid \{ grid-template-columns: 1fr; \}/);
});

test("generator relies on shared health monitoring instead of repeating the health request", () => {
  assert.doesNotMatch(page, /Backend connected|Backend unavailable|Checking backend/);
  assert.doesNotMatch(page, /generator-api-state/);
  assert.doesNotMatch(styles, /generator-api-state/);
  assert.doesNotMatch(page, /apiOnline|\/health/);
  assert.match(shell, /fetch\(`\$\{apiBase\}\/health`/);
  assert.match(shell, /setHealth\("online"\)/);
  assert.match(shell, /setHealth\("offline"\)/);
});
