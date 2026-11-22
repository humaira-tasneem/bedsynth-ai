import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

const landing = await readFile(new URL("../components/MarketingLanding.tsx", import.meta.url), "utf8");
const route = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
const shell = await readFile(new URL("../components/AppShell.tsx", import.meta.url), "utf8");
const generator = await readFile(new URL("./generate/page.tsx", import.meta.url), "utf8");

test("public landing page links to sign-in and registration without guest entry", () => {
  for (const href of ["/login", "/register"]) assert.ok(landing.includes(`href="${href}"`));
  assert.doesNotMatch(landing, /guest|Guest/i);
  assert.doesNotMatch(route, /api\/v1\/guest|continueAsGuest|startingGuest|guestError/);
});

test("landing page presents the simplified workflow and honest sample preview", () => {
  for (const text of ["Generate smarter.", "Research better.", "Synthetic dataset generation", "Hospital operations modeling", "Scenario-based generation", "Analytics", "Data quality and validation", "Dataset management", "Choose a hospital", "Configure your dataset", "Generate and analyze", "Sign in", "Create your account", "Fictional sample values"]) {
    assert.ok(landing.includes(text), `Expected landing content: ${text}`);
  }
  assert.match(landing, /useReducedMotion/);
  assert.equal(landing.includes("/api/v1/guest/sessions"), false);
});

test("sidebar contains only approved role destinations", () => {
  const adminNav = shell.slice(shell.indexOf("const adminNavigationGroups"), shell.indexOf("const userNavigationGroups"));
  const userNav = shell.slice(shell.indexOf("const userNavigationGroups"), shell.indexOf("function routeLabel"));
  for (const [path, label] of [["/hospitals", "Hospital Management"], ["/users", "User Management"], ["/generate", "Generate Dataset"], ["/datasets", "My Datasets"], ["/analytics", "Analytics"], ["/settings", "My Account"]]) {
    assert.ok(adminNav.includes(`href: "${path}"`) && adminNav.includes(`label: "${label}"`));
  }
  for (const [path, label] of [["/", "Dashboard"], ["/generate", "Generate Dataset"], ["/datasets", "My Datasets"], ["/analytics", "Analytics"], ["/validation", "Data Validation"], ["/settings", "My Account"]]) {
    assert.ok(userNav.includes(`href: "${path}"`) && userNav.includes(`label: "${label}"`));
  }
  for (const hiddenPath of ["/admin", "/admin/datasets", "/assistant", "/guest"]) {
    assert.equal(adminNav.includes(`href: "${hiddenPath}"`), false);
    assert.equal(userNav.includes(`href: "${hiddenPath}"`), false);
  }
  assert.doesNotMatch(shell, /guestNavigationGroups|guestRouteAllowed|api\/v1\/guest/);
  assert.doesNotMatch(generator, /guestMode|guestApiPrefix|api\/v1\/guest/);
});

test("retired assistant and guest pages are absent and protected routes go to sign-in", () => {
  assert.equal(existsSync(new URL("./assistant/page.tsx", import.meta.url)), false);
  assert.equal(existsSync(new URL("./guest/datasets/[runId]/page.tsx", import.meta.url)), false);
  assert.match(shell, /router\.replace\("\/login"\)/);
});
