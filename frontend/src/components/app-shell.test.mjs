import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const shell = await readFile(new URL("./AppShell.tsx", import.meta.url), "utf8");

test("shared header hides backend health status for both role layouts", () => {
  const adminNavigation = shell.slice(shell.indexOf("const adminNavigationGroups"), shell.indexOf("const userNavigationGroups"));
  const userNavigation = shell.slice(shell.indexOf("const userNavigationGroups"), shell.indexOf("function routeLabel"));
  assert.match(adminNavigation, /ADMINISTRATION/);
  assert.match(userNavigation, /RESEARCH/);
  assert.match(shell, /data-backend-health=\{health\}/);
  assert.doesNotMatch(shell, /Backend connected|Backend unavailable|Checking backend|product-health/);
  assert.equal((shell.match(/<header className="product-topbar">/g) ?? []).length, 1);
  assert.match(shell, /apiBase\}\s*\/health/);
  assert.match(shell, /className="product-icon-button product-theme"/);
  assert.match(shell, /setHealth\("online"\)/);
  assert.match(shell, /setHealth\("offline"\)/);
});
