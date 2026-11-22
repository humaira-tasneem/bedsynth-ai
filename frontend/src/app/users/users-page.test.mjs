import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");

test("admin user overview presents registration metadata and selectable history", () => {
  for (const label of ["User Management", "Registered accounts", "Generation history", "Registered", "Completed datasets", "Latest generation", "Metadata only"]) {
    assert.ok(page.includes(label), `Expected user overview label: ${label}`);
  }
  assert.match(page, /aria-label=\{`View generation history for \$\{account\.email\}`\}/);
  assert.match(page, /Loading registered users/);
  assert.match(page, /No registered users yet/);
  assert.match(page, /role="alert"/);
});

test("user run inspection calls only the read-only metadata API", () => {
  assert.match(page, /\/api\/v1\/admin\/overview\$\{path\}/);
  assert.match(page, /\/users\/\$\{userId\}\?page=/);
  assert.doesNotMatch(page, /method:\s*["'](?:POST|PATCH|PUT|DELETE)["']/i);
  assert.doesNotMatch(page, /password_hash|token_hash|session_data|synthetic_patient_id|patient_id/);
  for (const label of ["Scenario", "Target admissions", "Target occupancy", "Seed", "Departments", "Patients", "Admissions", "Transfers", "Occupancy snapshots"]) {
    assert.ok(page.includes(label), `Expected safe metadata label: ${label}`);
  }
});
